import threading
import time
import queue
# import cv2 # 移除 opencv 依赖，防止被检测
import torch
import math
import random
import pyautogui
import ctypes
import psutil
import subprocess
from typing import Optional

from capture import create_capture
from inference import YOLOInference
from input import create_input
from utils.hotkey import is_hotkey_pressed
from utils.kalman import KalmanFilter
from utils.config import ConfigManager
from core.mouse_monitor import MouseMonitor

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class AutoXController:
    """
    AutoX 核心控制器
    负责协调采集、推理和输入模块，实现多线程高效运行。
    """
    
    def __init__(self, model_path: str = "base.pt", device: str = "cuda"):
        # 0. 提升进程优先级
        self._set_high_priority()
        
        # 1. 初始化各子模块
        print("[Core] 正在初始化核心控制器...")
        self.config = ConfigManager() # 加载配置
        self.capture = create_capture(method="dda")
        self._model_path = model_path
        self.device = device
        self.inference = YOLOInference(model_path=model_path, device=device)
        
        input_method = self.config.get("input.input_method", "dd")
        print(f"[Core] Input Method: {input_method}")
        self.input = create_input(method=input_method)
        
        # 初始化参数和状态
        self._init_params()

    @property
    def model_path(self):
        return self._model_path

    @model_path.setter
    def model_path(self, path):
        if path != self._model_path:
            print(f"[Core] 模型路径变更: {path}")
            self._model_path = path
            # 更新推理模块的模型
            self.inference.model_path = path
            self.inference.load_model()

    def _set_high_priority(self):
        """(已禁用) 提升进程和线程优先级"""
        # 移除高优先级设置，防止系统驱动(如 DD)饥饿导致死锁
        print("[Core] 进程优先级保持默认 (NORMAL)")
        pass
        # try:
        #     import os
        #     import psutil
        #     p = psutil.Process(os.getpid())
        #     # 设置为高优先级 (不是实时，实时可能导致系统假死)
        #     p.nice(psutil.HIGH_PRIORITY_CLASS)
        #     print("[Core] 已将进程优先级提升至: HIGH")
        # except Exception as e:
        #     print(f"[Core] 提升优先级失败: {e}")

    def _init_params(self):
        # 2. 线程间通信
        self.frame_queue = queue.Queue(maxsize=5)  # 采集 -> 推理 (增大以支持批处理)
        self.debug_queue = queue.Queue(maxsize=1)  # 推理 -> UI (仅用于调试)
        self.stop_event = threading.Event()
        
        # [已移除] 全局安全锁：强制推理和输入操作互斥
        # 采用多进程 DD 驱动方案，天然隔离资源，无需锁
        # self.safety_lock = threading.Lock()
        
        # 3. 状态与配置
        self.running = False
        self.show_debug = False
        self.target_class_ids = [0]  # 默认瞄准 ID 为 0 的目标 (通常是人/person)
        self.inference.target_class_ids = self.target_class_ids # 同步给推理模块
        self.fov_size = 500         # 推理范围 (像素直径)
        self.use_fov_inference = False  # 是否启用局部 FOV 推理 (提升小目标识别)
        self.fov_center_mode = "screen" # FOV 中心模式: "screen" 或 "mouse"
        self.screen_center = (self.input.screen_width // 2, self.input.screen_height // 2)
        
        # FPS 限制
        self.max_fps = self.config.get("inference.max_fps", 60)
        self.last_frame_time = 0
        
        # 批处理配置
        self.batch_size = 1 # 默认批次大小 (开启批处理时动态增加)
        self.max_batch_size = 4 # 最大允许批次大小
        
        # FPS 限制
        self.target_fps = 60

        # 4. 鼠标运动监控 (防抖与用户优先策略)
        # 阈值 30px, 冷却 50ms (0.05s)
        self.mouse_monitor = MouseMonitor(threshold=30, timeout=0.05)
        
        # 进阶控制算法
        self.kf = KalmanFilter()
        self.kalman_enabled = False     # 默认关闭，响应用户要求
        self.ema_enabled = False        # 默认关闭，响应用户要求
        self.ema_alpha = 0.7
        
        # 动态 PID 配置
        self.dynamic_pid_enabled = True # 开启动态 PID
        self.pid_kp_min = 0.45          # 近距离时的 KP (追求稳)
        self.pid_kp_max = 0.85          # 远距离时的 KP (追求狠)
        self.pid_kp = self.pid_kp_min
        self.pid_ki = 0.00
        self.pid_kd = 0.08
        self.last_target_center = None
        self.last_target_box = None
        self.locked_conf = 0.0
        self.on_target_frames = 0
        self.on_target_required = 1     # 降低门槛，追求“狠”
        self.fire_min_interval = 0.12   # 缩短开火间隔
        self.last_fire_time = 0
        self.prev_raw_error_y = 0.0
        self.target_lost_frames = 0
        self.max_target_lost_frames = 10 # 预测保持时间 (短)
        self.lock_stick_frames = 120     # 锁定吸附时间 (长, 约2秒)，在此期间不切目标
        self.lock_retain_radius = 150   # 进一步扩大锁定保留范围，增强粘滞性
        self.switch_delay_frames = 0    # 目标切换防抖计数器
        self.switch_threshold = 5       # 目标切换防抖阈值 (帧)，约 80-100ms
        self.error_sum_x = 0
        self.error_sum_y = 0
        self.last_error_x = 0
        self.last_error_y = 0
        self.remainder_x = 0.0
        self.remainder_y = 0.0

        # 后坐力抑制设置
        self.recoil_enabled = False
        self.recoil_strength = 2.0      # 每帧向下补偿的像素基础值
        self.recoil_x_jitter = 0.5      # 随机左右抖动补偿

        # 运动补偿
        self.move_comp_enabled = False
        self.move_comp_strength = 1.0   # 移动补偿强度

        # 行为设置
        self.auto_lock = True
        self.move_key = "RButton" # 默认移动触发键 (右键)
        self.mouse_sensitivity = 1.0    # 鼠标灵敏度倍率
        self.aim_offset_y = 0.3         # 瞄准点纵向偏移 (0.5 为中心, 0.2 为偏向头部)
        self.post_action = ""
        self.post_action_count = 1     # 后置操作执行次数
        self.post_action_interval = 0.01 # 后置操作执行间隔 (秒)

        # 共享指令变量 (用于线程间通信)
        # 1. 鼠标移动 (覆盖式，只保留最新)
        self.latest_move_cmd = None
        self.move_cmd_lock = threading.Lock()
        
        # 2. 按键动作 (队列式，保证不漏)
        self.action_queue = queue.Queue(maxsize=10)

        # 系统状态监控 (每 10s 打印一次)
        self.last_report_time = time.perf_counter()
        self.frame_count = 0
        self.total_inf_latency = 0.0
        self.inf_count = 0
        self.total_lock_latency = 0.0
        self.lock_count = 0
        self.total_capture_to_lock_latency = 0.0
        self.capture_to_lock_count = 0

    def _check_trigger(self):
        """检查当前是否满足触发条件"""
        # 移除长按模式，默认始终为 True (只要运行中就执行推理逻辑)
        return True

    def _capture_loop(self):
        """图像采集线程：尽力而为的高频采集"""
        print(f"[Core] 采集线程已启动 (Target FPS: {self.target_fps})")
        self.capture.start()
        try:
            while not self.stop_event.is_set():
                loop_start = time.perf_counter()
                try:
                    frame = self.capture.get_frame()
                    capture_time = time.perf_counter()
                    if frame is not None:
                        # 如果队列满了，先取出旧帧，放入新帧
                        if self.frame_queue.full():
                            try:
                                self.frame_queue.get_nowait()
                            except queue.Empty:
                                pass
                        self.frame_queue.put((frame, capture_time))
                except Exception as e:
                    print(f"[Core] 采集异常: {e}")
                    time.sleep(0.01)
                
                # 优化：移除硬性 sleep，依靠 capture.get_frame() 的内部频率控制
                # 或采用极短休眠避免空转 CPU
                if self.target_fps > 0:
                    elapsed = time.perf_counter() - loop_start
                    # 提高容忍度，只有当明显超过目标频率时才休眠
                    wait_time = (1.0 / self.target_fps) - elapsed
                    if wait_time > 0.001: # 只有大于 1ms 才休眠
                        time.sleep(wait_time)
                    else:
                        # 即使不休眠，也给系统调度一点机会
                        time.sleep(0.0001) 

        finally:
            self.capture.stop()
            print("[Core] 采集线程已停止")

    def _input_loop(self):
        """输入控制线程：独立处理鼠标移动和按键，避免阻塞推理线程"""
        print(f"[Core] 输入线程已启动 (Thread: {threading.current_thread().name})")
        
        # --- 关键修改：在输入线程内部初始化 DD 驱动 ---
        # 确保 DD_btn(0) 和 DD_movR 在同一个线程执行，避免跨线程调用导致的死锁
        try:
            if hasattr(self.input, 'init_driver'):
                print("[Core] 正在输入线程中初始化 DD 驱动...")
                self.input.init_driver()
        except Exception as e:
            print(f"[Core] 🔴 DD 驱动线程内初始化失败: {e}")

        last_move_time = 0.0
        # 优化：降低指令间隔限制。
        # 此前 0.030 (33Hz) 限制过死导致卡顿。
        # 现在设为 0.002 (500Hz)，实际频率受限于推理速度和 DD 子进程的内部限制。
        min_interval = 0.002
        
        while not self.stop_event.is_set():
            try:
                # --- 1. 处理鼠标移动 (优先级高，需流畅) ---
                cmd = None
                with self.move_cmd_lock:
                    if self.latest_move_cmd:
                        cmd = self.latest_move_cmd
                        self.latest_move_cmd = None
                
                if cmd:
                    timestamp, dx, dy = cmd
                    now = time.perf_counter()
                    
                    if now - timestamp < 0.2:
                        if now - last_move_time >= min_interval:
                            # 增加异常捕获，防止驱动底层错误导致线程静默退出
                            try:
                                self.input.move_rel(dx, dy)
                            except Exception as e:
                                print(f"[Core] Move failed: {e}")
                            last_move_time = now
                        else:
                            # 频率限制，丢弃微小移动
                            pass
                
                # --- 2. 处理按键动作 (优先级次之) ---
                try:
                    # 非阻塞获取动作
                    action_item = self.action_queue.get_nowait()
                    self._perform_action(action_item)
                except queue.Empty:
                    pass
                
                # 短暂休眠，避免空转占用 CPU
                # 调整休眠时间为 1ms，保持极高响应速度 (1000Hz)
                time.sleep(0.001)
                    
            except Exception as e:
                print(f"[Core] 输入线程异常: {e}")
                time.sleep(0.01)
        print("[Core] 输入线程已停止")

    def _perform_action(self, action_data):
        """在输入线程中实际执行按键操作"""
        try:
            action_type = action_data.get('type')
            
            if action_type == 'click':
                btn = action_data.get('button')
                self.input.click(btn)
                
            elif action_type == 'key_sequence':
                keys = action_data.get('keys', [])
                interval = action_data.get('interval', 0.03)
                
                # 导入映射表
                from utils.hotkey import KEY_MAP
                vk_codes = []
                
                # 按下
                for k in keys:
                    vk = KEY_MAP.get(k)
                    if vk:
                        self.input.key_down(vk)
                        vk_codes.append(vk)
                
                time.sleep(interval)
                
                # 抬起 (反向)
                for vk in reversed(vk_codes):
                    self.input.key_up(vk)
                    
        except Exception as e:
            print(f"[Core] 执行按键动作失败: {e}")

    def _execute_post_action(self):
        """将后置操作放入队列，由输入线程执行"""
        if not self.post_action:
            return
            
        try:
            # 如果队列已满，说明输入线程处理不过来，丢弃本次开火以防积压
            if self.action_queue.full():
                return

            for _ in range(max(1, self.post_action_count)):
                action_lower = self.post_action.lower()
                
                try:
                    if action_lower in ["lbutton", "left"]:
                        self.action_queue.put_nowait({'type': 'click', 'button': 'left'})
                    elif action_lower in ["rbutton", "right"]:
                        self.action_queue.put_nowait({'type': 'click', 'button': 'right'})
                    elif action_lower in ["mbutton", "middle"]:
                        self.action_queue.put_nowait({'type': 'click', 'button': 'middle'})
                    else:
                        # 键盘按键处理
                        keys = self.post_action.split("+") if "+" in self.post_action else [self.post_action]
                        cleaned_keys = []
                        for k in keys:
                            k = k.strip()
                            if k.lower() == "ctrl": k = "Ctrl"
                            elif k.lower() == "alt": k = "Alt"
                            elif k.lower() == "shift": k = "Shift"
                            elif len(k) == 1: k = k.upper()
                            cleaned_keys.append(k)
                            
                        self.action_queue.put_nowait({
                            'type': 'key_sequence', 
                            'keys': cleaned_keys,
                            'interval': random.uniform(0.02, 0.04)
                        })
                except queue.Full:
                    pass # 队列满则丢弃
                
                
                # 如果有多次操作，这里不再 sleep，而是让输入线程去处理
                # 但为了逻辑简单，我们只发一次，或者循环发多次
                # 注意：这里发多次会瞬间填满队列
                
        except Exception as e:
            print(f"[Core] 提交后置操作失败 ({self.post_action}): {e}")

    def _inference_loop(self):
        """推理与控制线程：消费图像并执行动作"""
        print("[Core] 推理线程已启动")
        prev_time = time.time()
        
        last_log_time = time.time()
        while not self.stop_event.is_set():
            try:
                # FPS 频率控制
                if self.max_fps > 0:
                    min_interval = 1.0 / self.max_fps
                    elapsed = time.perf_counter() - self.last_frame_time
                    if elapsed < min_interval:
                        time.sleep(min_interval - elapsed)
                self.last_frame_time = time.perf_counter()

                # A. 获取图像与上下文
                
                # 更新鼠标监控状态
                self.mouse_monitor.update()
                
                try:
                    # 动态批处理：尝试获取队列中所有可用的帧
                    batch_items = []
                    
                    # 首先阻塞获取第一帧
                    # 减小超时时间，增加检查频率
                    try:
                        item = self.frame_queue.get(timeout=0.01)
                        batch_items.append(item)
                    except queue.Empty:
                        continue # 没有帧，继续循环检查 stop_event
                    
                    # 如果还有剩余帧，且未达到最大批次，则继续非阻塞获取
                    # 注意：对于固定 Batch=1 的 TensorRT 模型，多帧推理会变成顺序执行，增加延迟
                    while not self.frame_queue.empty() and len(batch_items) < self.max_batch_size:
                        try:
                            batch_items.append(self.frame_queue.get_nowait())
                        except queue.Empty:
                            break
                    
                    # 性能优化：如果模型不支持批处理，为了降低延迟，我们只保留最新的一帧，丢弃旧帧
                    if self.batch_size == 1 and len(batch_items) > 1:
                        batch_items = [batch_items[-1]]
                    
                    # 解包 batch_items -> batch_frames
                    batch_frames = [x[0] for x in batch_items]
                    # 获取当前用于控制的帧的采集时间（最后一帧）
                    current_frame_capture_time = batch_items[-1][1]
                    
                    # 我们只对批次中的最后一帧（最新帧）计算控制上下文
                    frame = batch_frames[-1]
                    h, w = frame.shape[:2]
                    
                    if self.fov_center_mode == "mouse":
                        pt = POINT()
                        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                        # 修复：将全局鼠标坐标转换为相对于采集窗口的坐标
                        # 这里假设 capture.region 包含了 (left, top, width, height)
                        # 如果是全屏采集，region 为 None 或 (0,0,w,h)
                        if hasattr(self.capture, 'region') and self.capture.region:
                            center_x = pt.x - self.capture.region[0]
                            center_y = pt.y - self.capture.region[1]
                        else:
                            # 默认假设是主屏幕采集
                            center_x, center_y = pt.x, pt.y
                    else:
                        center_x, center_y = w // 2, h // 2

                    inference_frame = frame
                    offset_x, offset_y = 0, 0
                    
                    if self.use_fov_inference:
                        half_fov = int(self.fov_size / 2)
                        x1_crop = max(0, center_x - half_fov)
                        y1_crop = max(0, center_y - half_fov)
                        x2_crop = min(w, center_x + half_fov)
                        y2_crop = min(h, center_y + half_fov)
                        inference_frame = frame[y1_crop:y2_crop, x1_crop:x2_crop]
                        offset_x, offset_y = x1_crop, y1_crop

                    # 推理与控制
                    if len(batch_frames) > 1:
                        if self.use_fov_inference:
                            # 批量裁剪
                            batch_inference_frames = [f[y1_crop:y2_crop, x1_crop:x2_crop] for f in batch_frames]
                        else:
                            batch_inference_frames = batch_frames
                        
                        # 执行批推理
                        batch_results = self.inference.predict(batch_inference_frames)
                        # 我们只关心最后一帧的结果
                        results = batch_results[-1]
                        inf_batch = len(batch_inference_frames)
                    else:
                        # 单帧推理
                        results = self.inference.predict(inference_frame)
                        inf_batch = 1
                    
                    # 更新帧计数用于 FPS 计算
                    self.frame_count += inf_batch
                    
                    # 统计推理延迟 (Capture -> Inference Done)
                    now = time.perf_counter()
                    inf_latency_ms = (now - current_frame_capture_time) * 1000
                    self.total_inf_latency += inf_latency_ms
                    self.inf_count += 1

                    # 检查是否卡顿超过 100ms
                    if inf_latency_ms > 100:
                         print(f"[Core] Warning: High Latency Detected! Inf-Lat: {inf_latency_ms:.1f}ms (Possible Freeze)", flush=True)

                    # 每 10 秒打印一次系统资源报告
                    curr_time = now
                    if curr_time - self.last_report_time >= 10.0:
                        elapsed = curr_time - self.last_report_time
                        fps = self.frame_count / elapsed
                        avg_inf = self.total_inf_latency / self.inf_count if self.inf_count > 0 else 0
                        avg_lock = self.total_lock_latency / self.lock_count if self.lock_count > 0 else 0
                        avg_cap_lock = self.total_capture_to_lock_latency / self.capture_to_lock_count if self.capture_to_lock_count > 0 else 0
                        
                        # 优化：打印更直观的系统资源报告
                        cpu_usage = psutil.cpu_percent()
                        mem_info = psutil.virtual_memory()
                        
                        # 获取 GPU 显存占用 (仅使用 torch 避免 subprocess 阻塞)
                        gpu_mem_used = 0.0
                        try:
                            # free_mem, total_mem = torch.cuda.mem_get_info()
                            # gpu_mem_used = (total_mem - free_mem) / 1024**2
                            pass # 暂时禁用 GPU 信息查询以避免阻塞
                        except:
                            pass

                        print(f"[System] FPS: {fps:.1f} | Inf-Lat: {avg_inf:.1f}ms | Lock-Lat: {avg_lock:.1f}ms | Cap-Target: {avg_cap_lock:.1f}ms | CPU: {cpu_usage}% | MEM: {mem_info.percent}%", flush=True)
                        
                        self.frame_count = 0
                        self.total_inf_latency = 0.0
                        self.inf_count = 0
                        self.total_lock_latency = 0.0
                        self.lock_count = 0
                        self.total_capture_to_lock_latency = 0.0
                        self.capture_to_lock_count = 0
                        self.last_report_time = curr_time
                
                except queue.Empty:
                    continue
                
                # B. 目标筛选与锁定 (中心距离优先 + FOV 限制)
                # 优化：在局部坐标系下进行筛选，减少映射开销
                target = None
                min_dist = float('inf')
                
                if not self.auto_lock:
                    self.kf.reset() # 未锁定目标时重置滤波器
                
                # 计算当前推理帧中的中心点（即准星在局部帧中的位置）
                if self.use_fov_inference:
                    local_center_x = center_x - offset_x
                    local_center_y = center_y - offset_y
                    # 局部推理时，FOV 限制在裁剪区域内
                    fov_radius_sq = (self.fov_size / 2) ** 2
                else:
                    # 全屏推理时，坐标系就是帧坐标系
                    local_center_x = center_x
                    local_center_y = center_y
                    # 全屏模式下，用户可能设置了 FOV 范围。如果没设置，默认全屏。
                    if self.fov_size > 0:
                        fov_radius_sq = (self.fov_size / 2) ** 2
                    else:
                        # 默认全屏：使用屏幕对角线作为 FOV 半径的平方
                        fov_radius_sq = w**2 + h**2

                # 获取移动触发键状态 (长按 move_key 触发锁定逻辑)
                move_triggered = is_hotkey_pressed(self.move_key)
                
                # 判定是否处于“跟踪状态”
                # 跟踪状态 = (开启了自动跟踪) 或 (按住了移动热键)
                # 只有在跟踪状态下，才进行目标选择和锁定；否则只进行纯推理（显示框但不锁定）
                is_tracking = self.auto_lock or move_triggered

                if is_tracking:
                    def iou(box1, box2):
                        x11, y11, x12, y12 = box1
                        x21, y21, x22, y22 = box2
                        ix1 = max(x11, x21)
                        iy1 = max(y11, y21)
                        ix2 = min(x12, x22)
                        iy2 = min(y12, y22)
                        iw = max(0.0, ix2 - ix1)
                        ih = max(0.0, iy2 - iy1)
                        inter = iw * ih
                        if inter <= 0:
                            return 0.0
                        a1 = max(0.0, x12 - x11) * max(0.0, y12 - y11)
                        a2 = max(0.0, x22 - x21) * max(0.0, y22 - y21)
                        union = a1 + a2 - inter
                        if union <= 0:
                            return 0.0
                        return inter / union

                    candidates = []
                    for res in results:
                        x1, y1, x2, y2, conf, cls = res
                        if int(cls) in self.target_class_ids:
                            tx, ty = (x1 + x2) / 2, (y1 + y2) / 2
                            dist_sq = (tx - local_center_x) ** 2 + (ty - local_center_y) ** 2
                            if dist_sq < fov_radius_sq:
                                if self.use_fov_inference:
                                    fx1 = x1 + offset_x
                                    fy1 = y1 + offset_y
                                    fx2 = x2 + offset_x
                                    fy2 = y2 + offset_y
                                else:
                                    fx1, fy1, fx2, fy2 = x1, y1, x2, y2
                                candidates.append((res, dist_sq, (fx1, fy1, fx2, fy2)))

                    if candidates:
                        # 策略优化：分离“粘滞目标”查找和“最佳新目标”查找
                        
                        # A. 寻找粘滞目标 (Sticky Target)
                        # 尝试在当前帧中找到与上一帧目标匹配的候选框
                        sticky_res = None
                        sticky_box = None
                        sticky_dist_sq = float('inf')
                        
                        if self.last_target_box is not None:
                            best_iou = 0.0
                            min_dist_to_last = float('inf')
                            match_res_by_dist = None
                            match_box_by_dist = None
                            
                            last_tx = (self.last_target_box[0] + self.last_target_box[2]) / 2
                            last_ty = (self.last_target_box[1] + self.last_target_box[3]) / 2

                            for res, dist_sq, full_box in candidates:
                                # 1. IoU 匹配
                                v = iou(self.last_target_box, full_box)
                                if v > best_iou:
                                    best_iou = v
                                    sticky_res = res
                                    sticky_box = full_box
                                    sticky_dist_sq = dist_sq
                                
                                # 2. 距离匹配 (作为 IoU 失败的备选)
                                curr_tx = (full_box[0] + full_box[2]) / 2
                                curr_ty = (full_box[1] + full_box[3]) / 2
                                d_to_last = (curr_tx - last_tx)**2 + (curr_ty - last_ty)**2
                                if d_to_last < min_dist_to_last:
                                    min_dist_to_last = d_to_last
                                    match_res_by_dist = res
                                    match_box_by_dist = full_box
                                    match_dist_sq = dist_sq

                            # 判定粘滞是否成功
                            # 宽松的阈值，确保尽量不丢目标
                            iou_threshold = 0.05 if not self.use_fov_inference else 0.1
                            retain_radius_sq = (self.lock_retain_radius * (1.5 if not self.use_fov_inference else 1.0))**2
                            
                            if sticky_res is None or best_iou < iou_threshold:
                                # IoU 匹配失败，尝试距离匹配
                                if match_res_by_dist is not None and min_dist_to_last < retain_radius_sq:
                                    sticky_res = match_res_by_dist
                                    sticky_box = match_box_by_dist
                                    sticky_dist_sq = match_dist_sq
                                else:
                                    # 彻底跟丢
                                    sticky_res = None
                                    sticky_box = None

                        # B. 寻找最佳新目标 (Best New Target)
                        # 用户要求：锁定第一个识别到的，不用管得分。
                        # 这样可以避免在两个目标间反复跳变
                        best_new_res = None
                        best_new_box = None
                        
                        if candidates:
                            # 直接取第一个，简单粗暴，防止挑选导致的跳变
                            best_new_res = candidates[0][0]
                            best_new_box = candidates[0][2]

                        # C. 最终决策
                        # 逻辑变更：引入目标切换防抖 (Switch Delay)
                        # 1. 如果找到了粘滞目标 (T1)，立即锁定，重置切换计数器
                        if sticky_res is not None:
                            target = sticky_res
                            self.last_target_box = sticky_box
                            self.switch_delay_frames = 0
                        else:
                            # 2. 没找到粘滞目标 (T1 丢失)
                            # 检查是否应该切换到新目标 (T2)
                            should_switch = False
                            
                            # 只有在有新目标的情况下，才进行切换判定
                            if best_new_res is not None:
                                self.switch_delay_frames += 1
                                # 如果新目标持续存在超过阈值 (如 5 帧)，才允许切换
                                if self.switch_delay_frames > self.switch_threshold:
                                    should_switch = True
                            else:
                                # 连新目标都没有，重置切换计数
                                self.switch_delay_frames = 0
                            
                            if should_switch:
                                # 允许切换
                                target = best_new_res
                                if target is not None:
                                    self.last_target_box = best_new_box
                                    # 注意：切换目标后，target_lost_frames 会在循环末尾自动重置为 0
                                    self.switch_delay_frames = 0
                            else:
                                # 不允许切换，保持吸附 (等待 T1 重现)
                                # 除非超时 (lock_stick_frames)，否则 target 为 None (不瞄准)
                                if self.last_target_box is not None and self.target_lost_frames < self.lock_stick_frames:
                                    target = None
                                else:
                                    # 超时了，彻底放弃 T1，允许立即切换到 T2 (如果有)
                                    target = best_new_res
                                    if target is not None:
                                        self.last_target_box = best_new_box
                                        self.switch_delay_frames = 0
                        
                    else:
                        # 没有候选目标，清除记忆 (或进入丢失倒计时)
                        # 但为了简化逻辑，如果候选框都没了，就重置
                        target = None
                        self.last_target_box = None
                        self.switch_delay_frames = 0

                else:
                    # 如果未处于跟踪状态，强制清除目标锁定状态
                    target = None
                    self.last_target_box = None
                    self.switch_delay_frames = 0
                    self.kf.reset()
                
                if target is not None:
                    # 统计捕获延迟 (Capture -> Target Locked)
                    cap_lock_latency_ms = (time.perf_counter() - current_frame_capture_time) * 1000
                    self.total_capture_to_lock_latency += cap_lock_latency_ms
                    self.capture_to_lock_count += 1

                    tx1, ty1, tx2, ty2, tconf, tcls = target
                    if self.use_fov_inference:
                        tx1, ty1, tx2, ty2 = tx1 + offset_x, ty1 + offset_y, tx2 + offset_x, ty2 + offset_y
                    
                    # 使用卡尔曼滤波进行预测 (准)
                    if self.kalman_enabled:
                        pos = self.kf.update([(tx1 + tx2) / 2, (ty1 + ty2) / 2])
                        if pos is not None:
                            tw, th = (tx2 - tx1), (ty2 - ty1)
                            target = [pos[0] - tw/2, pos[1] - th/2, pos[0] + tw/2, pos[1] + th/2, tconf, tcls]
                        else:
                            target = [tx1, ty1, tx2, ty2, tconf, tcls]
                    else:
                        target = [tx1, ty1, tx2, ty2, tconf, tcls]

                    # 计算最终瞄准中心点 (保持 float 精度减少舍入晃动)
                    tx1, ty1, tx2, ty2, tconf, tcls = target
                    raw_target_x = (tx1 + tx2) / 2.0
                    target_height = ty2 - ty1
                    raw_target_y = ty1 + (target_height * self.aim_offset_y)
                    
                    # 2. 引入指数平滑 (EMA)，进一步过滤高频抖动 (稳)
                    if self.ema_enabled:
                        if self.last_target_center is not None:
                            target_center_x = self.ema_alpha * raw_target_x + (1 - self.ema_alpha) * self.last_target_center[0]
                            target_center_y = self.ema_alpha * raw_target_y + (1 - self.ema_alpha) * self.last_target_center[1]
                        else:
                            target_center_x = raw_target_x
                            target_center_y = raw_target_y
                    else:
                        target_center_x = raw_target_x
                        target_center_y = raw_target_y
                    
                    self.last_target_center = (target_center_x, target_center_y)
                    self.last_target_box = (tx1, ty1, tx2, ty2)
                    self.target_lost_frames = 0
                else:
                    self.target_lost_frames += 1
                    # 稳：在短时间内保持上一帧位置 (用于平滑预测)
                    if self.target_lost_frames > self.max_target_lost_frames:
                        self.last_target_center = None
                        # 注意：这里不清除 last_target_box，直到超过 lock_stick_frames 才清除
                        # self.last_target_box = None 
                        self.locked_conf = 0.0
                        self.prev_raw_error_y = 0.0
                    
                    # 只有超时很久，才彻底放弃锁定记忆，允许寻找新目标
                    if self.target_lost_frames > self.lock_stick_frames:
                        self.last_target_box = None

                # C. 执行输入反馈
                is_triggered = self._check_trigger()
                move_triggered = is_hotkey_pressed(self.move_key)
                
                # 程序是否正在接管鼠标/画面镜头
                # 只要目标存在（意味着已在跟踪状态）且全局触发开启，就执行接管
                # is_tracking = self.auto_lock or move_triggered
                is_program_controlling = target is not None and is_triggered and is_tracking
                
                # 用户优先策略：如果检测到用户正在移动鼠标，暂时让出控制权
                if is_program_controlling and self.mouse_monitor.is_user_active():
                    is_program_controlling = False
                    # 重置 PID 误差，防止恢复控制时发生剧烈跳变
                    self.last_error_x, self.last_error_y = 0.0, 0.0
                
                # 检测是否正在开火 (手动按住左键，或程序正在自动开火且处于连发状态)
                now = time.time()
                is_firing = is_hotkey_pressed("LButton") or (self.post_action and (now - self.last_fire_time < 0.2))

                dx, dy = 0, 0
                duration = 0.02 # 默认步进时间

                # 1. 计算瞄准移动量 (准)
                if is_program_controlling:
                    # 终极防御：限制目标中心点在合理范围内，防止异常坐标导致溢出
                    target_center_x = max(-2000.0, min(float(self.input.screen_width) + 2000.0, float(target_center_x)))
                    target_center_y = max(-2000.0, min(float(self.input.screen_height) + 2000.0, float(target_center_y)))
                    
                    error_x = target_center_x - center_x
                    error_y = target_center_y - center_y
                    dist = math.sqrt(error_x**2 + error_y**2)
                    
                    # 动态 PID 核心逻辑：根据距离调整 KP (稳准狠)
                    if self.dynamic_pid_enabled:
                        # 距离越远，KP 越大 (狠)；距离越近，KP 越小 (稳)
                        # 设定 100 像素为最大增益距离
                        scale = min(1.0, dist / 100.0)
                        current_kp = self.pid_kp_min + (self.pid_kp_max - self.pid_kp_min) * scale
                    else:
                        current_kp = self.pid_kp

                    deadzone = 1.5  # 略微增大死区，配合 EMA 平滑
                    if dist < deadzone:
                        self.on_target_frames += 1
                        error_x, error_y = 0.0, 0.0
                        # 进入死区时清空误差项，防止 derivative 产生抖动
                        self.last_error_x, self.last_error_y = 0.0, 0.0
                    else:
                        if dist < 5.0: self.on_target_frames += 1
                        else: self.on_target_frames = 0

                    p_out_x = error_x * current_kp
                    p_out_y = error_y * current_kp
                    d_out_x = (error_x - self.last_error_x) * self.pid_kd
                    d_out_y = (error_y - self.last_error_y) * self.pid_kd
                    
                    self.last_error_x, self.last_error_y = error_x, error_y
                    
                    dx = (p_out_x + d_out_x) * self.mouse_sensitivity
                    dy = (p_out_y + d_out_y) * self.mouse_sensitivity

                    # 2. 我方移动补偿 (解决我方移动不稳)
                    if self.move_comp_enabled:
                        # 监测 WASD 键状态
                        # 0x41: A, 0x44: D, 0x57: W, 0x53: S
                        # 如果按住 A (左移)，画面中的目标会向右移，准星需要向右补偿 (dx > 0)
                        if is_hotkey_pressed("A"):
                            dx += 2.0 * self.move_comp_strength
                        if is_hotkey_pressed("D"):
                            dx -= 2.0 * self.move_comp_strength
                        if is_hotkey_pressed("W"):
                            dy -= 1.0 * self.move_comp_strength
                        if is_hotkey_pressed("S"):
                            dy += 1.0 * self.move_comp_strength

                    # 全屏模式下的微调：如果距离很近，减小移动步长，防止反复横跳
                    if not self.use_fov_inference and dist < 10:
                        dx *= 0.8
                        dy *= 0.8

                    # 动态时间
                    if dist > 50: duration = 0.005
                    elif dist > 10: duration = 0.01
                else:
                    self.last_error_x, self.last_error_y = 0, 0

                # 2. 计算后坐力补偿量 (稳)
                # 核心修正：压枪的前提是用户已经开启了系统 (is_triggered) 且正在按下辅助按键 (move_triggered)
                # 只有在辅助激活的情况下，我们才执行开火检测和下压补偿
                is_assist_active = is_triggered and is_tracking
                is_recoil_active = self.recoil_enabled and is_firing and is_assist_active and (target is not None or self.target_lost_frames < self.max_target_lost_frames)
                
                if is_recoil_active:
                    # 基础下压
                    recoil_dy = self.recoil_strength
                    # 随机左右抖动抑制
                    recoil_dx = random.uniform(-self.recoil_x_jitter, self.recoil_x_jitter)
                    
                    dx += recoil_dx
                    dy += recoil_dy

                # 3. 执行最终移动 (带小数累加)
                # 在高频循环中，直接使用 move_rel 配合 PID 本身就是最平滑的。
                # smooth_move_rel 适用于单次大跨度移动。
                total_dx = dx + self.remainder_x
                total_dy = dy + self.remainder_y
                
                # 检查最终移动增量是否合法
                if not math.isfinite(total_dx) or not math.isfinite(total_dy):
                    total_dx, total_dy = 0.0, 0.0
                
                # 再次限制移动增量的物理极限，防止单帧移动过大触发 OverflowError 或导致视角飞掉
                # DD 驱动或游戏输入协议可能限制单次移动为 8-bit ([-127, 127])，超过会导致反向移动 (Overflow)
                # 因此将单帧最大移动限制在安全范围 (例如 100)
                limit = 100.0
                total_dx = max(-limit, min(limit, total_dx))
                total_dy = max(-limit, min(limit, total_dy))

                step_x = int(total_dx)
                step_y = int(total_dy)
                
                self.remainder_x = total_dx - step_x
                self.remainder_y = total_dy - step_y
                
                if step_x != 0 or step_y != 0:
                    # 将移动指令发送到输入线程
                    # 频率限制由输入线程负责，这里只负责发送最新指令
                    # 使用非阻塞锁获取，避免影响推理速度
                    if self.move_cmd_lock.acquire(blocking=False):
                        try:
                            self.latest_move_cmd = (time.perf_counter(), step_x, step_y)
                            # 关键：向监视器报告程序指令，以抵消余额，防止误判为用户移动
                            self.mouse_monitor.report_command(step_x, step_y)
                        finally:
                            self.move_cmd_lock.release()
                    else:
                        # 如果锁被占用（极少情况，因为输入线程持有锁的时间很短），
                        # 选择跳过本次更新，而不是阻塞等待
                        pass

                # 4. 自动开火触发 (狠)
                if is_program_controlling and self.post_action:
                    now = time.time()
                    
                    # 强制最小点击间隔保护 (Cooldown)，防止 10ms 这种极端设置导致系统卡死
                    # 限制为最快每秒 50 次 (20ms)
                    min_safe_interval = max(0.02, self.fire_min_interval)
                    
                    if self.on_target_frames >= self.on_target_required and now - self.last_fire_time >= min_safe_interval:
                        self._execute_post_action()
                        self.last_fire_time = now
                        self.on_target_frames = 0

                # E. 调试信息
                if self.show_debug:
                    curr_time = time.time()
                    fps = 1 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0
                    prev_time = curr_time

                    # 如果启用了局部推理，需要将所有检测框坐标映射回全局坐标用于显示
                    display_results = results
                    if self.use_fov_inference and results:
                        display_results = []
                        for (x1, y1, x2, y2, conf, cls) in results:
                            display_results.append((
                                x1 + offset_x, 
                                y1 + offset_y, 
                                x2 + offset_x, 
                                y2 + offset_y, 
                                conf, 
                                cls
                            ))

                    if not self.debug_queue.full():
                        debug_data = {
                            "frame": frame, # 直接传递原始帧 (NumPy 数组)
                            "results": display_results,
                            "target": target,
                            "center": (center_x, center_y),
                            "fov_size": self.fov_size,
                            "fps": int(fps)
                        }
                        try:
                            self.debug_queue.put_nowait(debug_data)
                        except queue.Full:
                            pass # 队列满则丢弃，保证推理不阻塞

                # 统计锁定延迟 (Capture -> Action Loop Done)
                # 即使没有执行移动，也记录整个处理循环的耗时，作为系统端到端延迟的参考
                now = time.perf_counter()
                lock_latency_ms = (now - current_frame_capture_time) * 1000
                self.total_lock_latency += lock_latency_ms
                self.lock_count += 1

            except Exception as e:
                print(f"[Core] 推理循环异常: {e}")
                time.sleep(0.01) # 避免死循环占用过多 CPU

        print("[Core] 推理线程已停止")

    def start(self, show_debug: bool = False):
        """启动控制器"""
        if self.running:
            return
            
        self.show_debug = show_debug
        self.stop_event.clear()
        
        self.t_cap = threading.Thread(target=self._capture_loop, daemon=True)
        self.t_inf = threading.Thread(target=self._inference_loop, daemon=True)
        self.t_input = threading.Thread(target=self._input_loop, daemon=True)
        
        self.t_cap.start()
        self.t_inf.start()
        self.t_input.start()
        
        self.running = True
        print("[Core] 控制器已全面启动")

    def stop(self):
        """停止控制器"""
        if not self.running:
            return
            
        print("[Core] 正在停止控制器...")
        self.running = False
        self.stop_event.set()
        
        # 1. 快速等待线程退出 (带更短的超时，避免 GUI 长时间挂起)
        # 推理线程通常最重，给予 1.5s
        if hasattr(self, 't_inf') and self.t_inf.is_alive():
            self.t_inf.join(timeout=1.5)
            if self.t_inf.is_alive():
                print("[Core] 警告: 推理线程未能在超时时间内正常退出")
                
        # 采集线程通常很快，给予 0.5s
        if hasattr(self, 't_cap') and self.t_cap.is_alive():
            self.t_cap.join(timeout=0.5)
            
        # 输入线程给予 0.5s
        if hasattr(self, 't_input') and self.t_input.is_alive():
            self.t_input.join(timeout=0.5)
            if self.t_input.is_alive():
                print("[Core] 警告: 输入线程未能在超时时间内正常退出")

        # 最终状态检查
        active_threads = []
        if hasattr(self, 't_inf') and self.t_inf.is_alive(): active_threads.append("Inference")
        if hasattr(self, 't_cap') and self.t_cap.is_alive(): active_threads.append("Capture")
        if hasattr(self, 't_input') and self.t_input.is_alive(): active_threads.append("Input")
        
        if active_threads:
            print(f"[Core] 警告: 以下线程仍处于活跃状态: {', '.join(active_threads)}，可能因驱动或 CUDA 阻塞。")

        # 2. 释放输入资源 (DD 驱动子进程)
        if hasattr(self.input, 'cleanup'):
            try:
                # DDInput.cleanup 会调用 stop()，内部已有强制终止逻辑
                self.input.cleanup()
            except Exception as e:
                print(f"[Core] Input cleanup failed: {e}")

        # 3. 清理队列（防止内存泄漏和挂起）
        # 注意：这里只清理我们自己创建的 queue.Queue
        try:
            while not self.frame_queue.empty():
                self.frame_queue.get_nowait()
            while not self.action_queue.empty():
                self.action_queue.get_nowait()
        except:
            pass

        print("[Core] 控制器已停止")

if __name__ == "__main__":
    # 简单的本地冒烟测试
    ctrl = AutoXController()
    try:
        ctrl.start(show_debug=True)
        # 运行 10 秒后自动停止
        time.sleep(10)
    except KeyboardInterrupt:
        pass
    finally:
        ctrl.stop()
