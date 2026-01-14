import threading
import time
import queue
import cv2
import torch
import math
from typing import Optional

from capture import create_capture
from inference import YOLOInference
from input import create_input

class AutoXController:
    """
    AutoX 核心控制器
    负责协调采集、推理和输入模块，实现多线程高效运行。
    """
    
    def __init__(self, model_path: str = "base.pt", device: str = "cuda"):
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

    def _init_params(self):
        # 2. 线程间通信
        self.frame_queue = queue.Queue(maxsize=1)  # 采集 -> 推理
        self.debug_queue = queue.Queue(maxsize=1)  # 推理 -> UI (仅用于调试)
        self.stop_event = threading.Event()
        
        # 3. 状态与配置
        self.running = False
        self.show_debug = False
        self.target_class_ids = [0]  # 默认瞄准 ID 为 0 的目标 (通常是人/person)
        self.fov_size = 500         # 推理范围 (像素直径)
        self.use_fov_inference = False  # 是否启用局部 FOV 推理 (提升小目标识别)
        self.fov_center_mode = "screen" # FOV 中心模式: "screen" 或 "mouse"
        self.screen_center = (self.input.screen_width // 2, self.input.screen_height // 2)

        # 行为设置
        self.auto_lock = True
        self.auto_move = True
        self.move_speed = "normal"
        self.custom_speed_ms = 10
        self.custom_speed_random = 5
        self.human_curve = False
        self.offset_radius = 0
        self.post_action = ""

        # 触发控制
        self.trigger_mode = "manual"  # "manual" (手动/点击启动) 或 "hold" (长按热键)
        self.trigger_key = "Shift"    # 默认触发热键
        self._last_trigger_state = False # 上一次的触发状态 (用于日志打印)

    def _check_trigger(self):
        """检查当前是否满足触发条件 (移动鼠标)"""
        if self.trigger_mode == "manual":
            # 手动模式下，只要 start() 了 (running=True)，就一直触发
            return True
        elif self.trigger_mode == "hold":
            # 按住模式下，检查按键状态
            from utils.hotkey import is_hotkey_pressed
            
            is_active = is_hotkey_pressed(self.trigger_key)
            
            # 状态边缘检测与日志打印
            if is_active and not self._last_trigger_state:
                print(f"[Core] 长按 {self.trigger_key} 启动成功")
            elif not is_active and self._last_trigger_state:
                print(f"[Core] 松开 {self.trigger_key} 关闭")
            
            self._last_trigger_state = is_active
            return is_active
        return False

    def _capture_loop(self):
        """图像采集线程：尽力而为的高频采集"""
        print("[Core] 采集线程已启动")
        self.capture.start()
        try:
            while not self.stop_event.is_set():
                try:
                    frame = self.capture.get_frame()
                    if frame is not None:
                        # 如果队列满了，先取出旧帧，放入新帧
                        if self.frame_queue.full():
                            try:
                                self.frame_queue.get_nowait()
                            except queue.Empty:
                                pass
                        self.frame_queue.put(frame)
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
            "normal": 0.05,
            "slow": 0.1,
            "custom": 0.05 # 默认为 normal，后续会被 custom_speed_ms 覆盖
        }

        while not self.stop_event.is_set():
            try:
                try:
                    # 获取最新一帧
                    frame = self.frame_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                # A. 执行 AI 推理
                inference_frame = frame
                offset_x, offset_y = 0, 0
                
                # 动态获取中心点
                h, w = frame.shape[:2]
                if self.fov_center_mode == "mouse":
                    # 获取鼠标当前位置
                    import pyautogui
                    m_x, m_y = pyautogui.position()
                    center_x, center_y = int(m_x), int(m_y)
                else:
                    center_x, center_y = w // 2, h // 2

                if self.use_fov_inference:
                    # 计算裁剪区域 (以当前帧中心为圆心，fov_size 为边长的正方形)
                    half_fov = int(self.fov_size / 2)
                    x1_crop = max(0, center_x - half_fov)
                    y1_crop = max(0, center_y - half_fov)
                    x2_crop = min(w, center_x + half_fov)
                    y2_crop = min(h, center_y + half_fov)
                    
                    # 裁剪并确保内存连续性
                    inference_frame = frame[y1_crop:y2_crop, x1_crop:x2_crop].copy()
                    offset_x, offset_y = x1_crop, y1_crop

                # 执行推理
                results = self.inference.predict(inference_frame)
                
                # 将结果坐标映射回全屏坐标
                if self.use_fov_inference:
                    mapped_results = []
                    for res in results:
                        x1, y1, x2, y2, conf, cls = res
                        mapped_results.append([x1 + offset_x, y1 + offset_y, x2 + offset_x, y2 + offset_y, conf, cls])
                    results = mapped_results

                # B. 目标筛选与锁定 (中心距离优先 + FOV 限制)
                target = None
                min_dist = float('inf')
                
                # 只有在启用自动锁定时才寻找锁定目标
                if self.auto_lock:
                    for res in results:
                        x1, y1, x2, y2, conf, cls = res
                        if int(cls) in self.target_class_ids:
                            # 计算目标中心点
                            tx, ty = (x1 + x2) / 2, (y1 + y2) / 2
                            
                            # 计算到准星(画面中心)的距离
                            dist = math.sqrt((tx - center_x)**2 + (ty - center_y)**2)
                            
                            # FOV 过滤：只有在圆圈范围内的目标才会被锁定
                            if dist < (self.fov_size / 2):
                                if dist < min_dist:
                                    min_dist = dist
                                    target = res
                
                # C. 执行输入反馈
                # 优先检查触发状态，确保日志能正常输出 (即使没有目标)
                is_triggered = self._check_trigger()

                # 只有在检测到目标 AND 满足触发条件（如按下热键）时才移动
                if target is not None and is_triggered and self.auto_move:
                    tx1, ty1, tx2, ty2, tconf, tcls = target
                    target_center_x = (tx1 + tx2) / 2
                    target_center_y = (ty1 + ty2) / 2
                    
                    # 应用随机偏移
                    if self.offset_radius > 0:
                        import random
                        angle = random.uniform(0, 2 * math.pi)
                        r = random.uniform(0, self.offset_radius)
                        target_center_x += r * math.cos(angle)
                        target_center_y += r * math.sin(angle)
                    
                    target_center_x = int(target_center_x)
                    target_center_y = int(target_center_y)
                    
                    # 计算平滑时长
                    if self.move_speed == "custom":
                        # 基础值 + 随机偏移
                        base_ms = self.custom_speed_ms
                        random_ms = random.uniform(-self.custom_speed_random, self.custom_speed_random)
                        duration = max(1, base_ms + random_ms) / 1000.0
                    else:
                        duration = SPEED_MAP.get(self.move_speed, 0.05)
                    
                    # 拟人化平滑移动 (始终使用平滑移动，时长由速度配置决定)
                    self.input.smooth_move_to(target_center_x, target_center_y, duration, human_curve=self.human_curve) 
                    
                    # 执行后置操作
                    if self.post_action:
                        self._execute_post_action()

                    if self.show_debug:
                        cv2.circle(frame, (target_center_x, target_center_y), 5, (0, 0, 255), -1)
                        cv2.putText(frame, "LOCKED", (target_center_x + 10, target_center_y), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

                # D. 处理调试显示数据
                if self.show_debug:
                    curr_time = time.time()
                    fps = 1 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0
                    prev_time = curr_time

                    # 将原始数据发送给 UI，由 UI 决定如何绘制 (Overlay 或 预览窗口)
                    # 避免在 Core 层进行 cv2 绘图，保持数据纯净
                    if not self.debug_queue.full():
                        debug_data = {
                            "frame": frame,           # 原始图像 (用于预览窗口)
                            "results": results,       # 所有检测结果 (用于 Overlay)
                            "target": target,         # 当前锁定目标
                            "center": (center_x, center_y), # 准星/FOV中心
                            "fov_size": self.fov_size, # FOV 大小
                            "fps": int(fps)           # 当前帧率
                        }
                        self.debug_queue.put(debug_data)
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
