import threading
import time
import queue
import cv2
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
        self.capture = create_capture(method="dda")
        self._model_path = model_path
        self.device = device
        self.inference = YOLOInference(model_path=model_path, device=device)
        self.input = create_input(method="win32")
        
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
        """提升进程和线程优先级，确保在游戏高负载下仍能获得时间片"""
        try:
            import os
            import psutil
            p = psutil.Process(os.getpid())
            # 设置为高优先级 (不是实时，实时可能导致系统假死)
            p.nice(psutil.HIGH_PRIORITY_CLASS)
            print("[Core] 已将进程优先级提升至: HIGH")
        except Exception as e:
            print(f"[Core] 提升优先级失败: {e}")

    def _init_params(self):
        # 2. 线程间通信
        self.frame_queue = queue.Queue(maxsize=5)  # 采集 -> 推理 (增大以支持批处理)
        self.debug_queue = queue.Queue(maxsize=1)  # 推理 -> UI (仅用于调试)
        self.stop_event = threading.Event()
        
        # 3. 状态与配置
        self.running = False
        self.show_debug = False
        self.target_class_ids = [0]  # 默认瞄准 ID 为 0 的目标 (通常是人/person)
        self.inference.target_class_ids = self.target_class_ids # 同步给推理模块
        self.fov_size = 500         # 推理范围 (像素直径)
        self.use_fov_inference = False  # 是否启用局部 FOV 推理 (提升小目标识别)
        self.fov_center_mode = "screen" # FOV 中心模式: "screen" 或 "mouse"
        self.screen_center = (self.input.screen_width // 2, self.input.screen_height // 2)
        
        # 批处理配置
        self.batch_size = 1 # 默认批次大小 (开启批处理时动态增加)
        self.max_batch_size = 4 # 最大允许批次大小
        
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
        self.last_target_id = None      # 锁定目标的唯一性标识(基于坐标/IoU)
        self.locked_conf = 0.0
        self.locked_bad_frames = 0
        self.max_locked_bad_frames = 3
        self.on_target_frames = 0
        self.on_target_required = 1     # 降低门槛，追求“狠”
        self.fire_min_interval = 0.12   # 缩短开火间隔
        self.last_fire_time = 0.0
        self.shots_in_burst = 0
        self.burst_reset_interval = 0.5
        self.auto_fire_extra_interval = 0.01
        self.prev_raw_error_y = 0.0
        self.target_lost_frames = 0
        self.max_target_lost_frames = 10 # 预测保持时间 (短)
        self.lock_stick_frames = 120     # 锁定吸附时间 (长, 约2秒)，在此期间不切目标
        self.lock_retain_radius = 150   # 进一步扩大锁定保留范围，增强粘滞性
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
        self.recoil_start_time = 0.0

        # 运动补偿
        self.move_comp_enabled = False
        self.move_comp_strength = 1.0   # 移动补偿强度
        self.last_target_pos_time = 0.0
        self.target_velocity_x = 0.0
        self.target_velocity_y = 0.0

        # 行为设置
        self.auto_lock = True
        self.move_key = "RButton" # 默认移动触发键 (右键)
        self.move_speed = "normal"
        self.custom_speed_ms = 10
        self.custom_speed_random = 5
        self.human_curve = False
        self.offset_radius = 0
        self.mouse_sensitivity = 1.0    # 鼠标灵敏度倍率
        self.aim_offset_y = 0.3         # 瞄准点纵向偏移 (0.5 为中心, 0.2 为偏向头部)
        self.post_action = ""
        self.post_action_count = 1     # 后置操作执行次数
        self.post_action_interval = 0.01 # 后置操作执行间隔 (秒)

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
        print("[Core] 采集线程已启动")
        self.capture.start()
        try:
            while not self.stop_event.is_set():
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
        finally:
            self.capture.stop()
            print("[Core] 采集线程已停止")

    def _execute_post_action(self):
        """执行锁定后的后置操作"""
        if not self.post_action:
            return
            
        try:
            import pyautogui
            import time
            
            for _ in range(max(1, self.post_action_count)):
                # 这里简单支持键盘按键和组合键，以及鼠标按键
                # pyautogui.press 支持 "ctrl", "shift", "a", "b", "f1" 等
                # 如果是组合键，可以用 "+" 分割，如 "ctrl+a"
                if "+" in self.post_action:
                    keys = self.post_action.split("+")
                    pyautogui.hotkey(*keys)
                elif self.post_action.lower() in ["lbutton", "left"]:
                    pyautogui.click(button='left')
                elif self.post_action.lower() in ["rbutton", "right"]:
                    pyautogui.click(button='right')
                elif self.post_action.lower() in ["mbutton", "middle"]:
                    pyautogui.click(button='middle')
                else:
                    pyautogui.press(self.post_action)
                
                # 如果次数大于1，且有间隔，则等待
                if self.post_action_count > 1 and self.post_action_interval > 0:
                    time.sleep(self.post_action_interval)
        except Exception as e:
            print(f"[Core] 执行后置操作失败 ({self.post_action}): {e}")

    def _inference_loop(self):
        """推理与控制线程：消费图像并执行动作"""
        print("[Core] 推理线程已启动")
        prev_time = time.time()
        
        # 速度映射表
        SPEED_MAP = {
            "fast": 0.01,
            "fast_medium": 0.03,
            "normal": 0.02,
            "slow": 0.1,
            "custom": 0.05 # 默认为 normal，后续会被 custom_speed_ms 覆盖
        }

        while not self.stop_event.is_set():
            try:
                # A. 获取图像与上下文
                try:
                    # 动态批处理：尝试获取队列中所有可用的帧
                    batch_items = []
                    
                    # 首先阻塞获取第一帧
                    item = self.frame_queue.get(timeout=0.1)
                    batch_items.append(item)
                    
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
                        
                        # 获取 GPU 真实利用率和显存占用 (通过 nvidia-smi)
                        gpu_util = 0.0
                        gpu_mem_used = 0.0
                        try:
                            # query-gpu: utilization.gpu (%), memory.used (MiB)
                            output = subprocess.check_output(
                                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                                encoding='utf-8',
                                stderr=subprocess.DEVNULL
                            ).strip()
                            parts = output.split(',')
                            if len(parts) >= 2:
                                gpu_util = float(parts[0])
                                gpu_mem_used = float(parts[1])
                        except Exception:
                            # 降级方案：如果 nvidia-smi 失败，使用 torch 尝试
                            try:
                                gpu_util = torch.cuda.utilization()
                                free_mem, total_mem = torch.cuda.mem_get_info()
                                gpu_mem_used = (total_mem - free_mem) / 1024**2
                            except:
                                pass

                        print(f"[System] FPS: {fps:.1f} | Inf-Lat: {avg_inf:.1f}ms | Lock-Lat: {avg_lock:.1f}ms | Cap-Target: {avg_cap_lock:.1f}ms | CPU: {cpu_usage}% | GPU-Load: {gpu_util}% | MEM: {mem_info.percent}% | GPU-MEM: {gpu_mem_used:.0f}MB")
                        
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
                        # 逻辑变更：只要处于跟踪状态，始终优先锁定“粘滞目标”（稳）
                        # 强吸附策略：一旦锁定目标，除非目标彻底丢失超过吸附时间，否则不切换目标
                        if sticky_res is not None:
                            target = sticky_res
                            self.last_target_box = sticky_box
                        else:
                            # 没找到粘滞目标
                            # 如果当前处于“吸附期”（虽然没找到目标，但还没超时），强制不切新目标
                            if self.last_target_box is not None and self.target_lost_frames < self.lock_stick_frames:
                                target = None
                            else:
                                # 彻底没目标了，或者之前没锁过，才允许锁新目标
                                target = best_new_res
                                if target is not None:
                                    self.last_target_box = best_new_box
                        
                    else:
                        # 没有候选目标，清除记忆 (或进入丢失倒计时)
                        # 只有在持续按住热键且允许短时丢失时才保留
                        # 但为了简化逻辑，如果候选框都没了，就重置
                        target = None
                        self.last_target_box = None

                else:
                    # 如果未处于跟踪状态，强制清除目标锁定状态
                    target = None
                    self.last_target_box = None
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
                # 设定单帧最大移动 1000 像素
                total_dx = max(-1000.0, min(1000.0, total_dx))
                total_dy = max(-1000.0, min(1000.0, total_dy))

                step_x = int(total_dx)
                step_y = int(total_dy)
                
                self.remainder_x = total_dx - step_x
                self.remainder_y = total_dy - step_y
                
                if step_x != 0 or step_y != 0:
                    self.input.move_rel(step_x, step_y)

                # 4. 自动开火触发 (狠)
                if is_program_controlling and self.post_action:
                    now = time.time()
                    if self.on_target_frames >= self.on_target_required and now - self.last_fire_time >= self.fire_min_interval:
                        self._execute_post_action()
                        self.last_fire_time = now
                        self.on_target_frames = 0

                    # D. 绘制调试信息 (如果检测到目标，即使不移动也显示)
                    if self.show_debug and target is not None:
                        try:
                            # 确保坐标是有限的数值，且为整数
                            if not math.isfinite(target_center_x) or not math.isfinite(target_center_y):
                                raise ValueError("Invalid target coordinates (NaN/Inf)")
                                
                            draw_x, draw_y = int(target_center_x), int(target_center_y)
                            cv2.circle(frame, (draw_x, draw_y), 5, (0, 0, 255), -1)
                            cv2.putText(frame, "LOCKED", (draw_x + 10, draw_y), 
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                        except (ValueError, OverflowError) as e:
                            # 如果预判算出了非法数值，打印警告并跳过绘图
                            # print(f"[Core] 坐标异常: {e}")
                            pass

                # E. 调试信息
                if self.show_debug:
                    curr_time = time.time()
                    fps = 1 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0
                    prev_time = curr_time

                    if not self.debug_queue.full():
                        debug_data = {
                            "frame": frame.copy(),
                            "results": results,
                            "target": target,
                            "center": (center_x, center_y),
                            "fov_size": self.fov_size,
                            "fps": int(fps)
                        }
                        self.debug_queue.put(debug_data)

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
        
        self.t_cap.start()
        self.t_inf.start()
        
        self.running = True
        print("[Core] 控制器已全面启动")

    def stop(self):
        """停止控制器"""
        if not self.running:
            return
            
        print("[Core] 正在停止控制器...")
        self.stop_event.set()
        self.t_cap.join(timeout=2)
        self.t_inf.join(timeout=2)
        self.running = False
        print("[Core] 控制器已安全关闭")

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
