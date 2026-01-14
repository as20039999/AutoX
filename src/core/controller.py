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
    
    def __init__(self, model_path: str = "yolov8n.pt", device: str = "cuda"):
        # 1. 初始化各子模块
        print("[Core] 正在初始化核心控制器...")
        self.capture = create_capture(method="dda")
        self.inference = YOLOInference(model_path=model_path, device=device)
        self.input = create_input(method="win32")
        
        # 2. 线程间通信
        self.frame_queue = queue.Queue(maxsize=1)  # 采集 -> 推理
        self.debug_queue = queue.Queue(maxsize=1)  # 推理 -> UI (仅用于调试)
        self.stop_event = threading.Event()
        
        # 3. 状态与配置
        self.running = False
        self.show_debug = False
        self.target_class_ids = [0]  # 默认瞄准 ID 为 0 的目标 (通常是人/person)
        self.smooth_move = True     # 是否启用平滑移动
        self.smooth_duration = 0.05 # 平滑移动时长 (秒)
        self.fov_size = 300         # 锁定范围 (像素直径)
        self.screen_center = (self.input.screen_width // 2, self.input.screen_height // 2)
        
    def _capture_loop(self):
        """图像采集线程：尽力而为的高频采集"""
        print("[Core] 采集线程已启动")
        self.capture.start()
        try:
            while not self.stop_event.is_set():
                frame = self.capture.get_frame()
                if frame is not None:
                    # 如果队列满了，先取出旧帧，放入新帧
                    if self.frame_queue.full():
                        try:
                            self.frame_queue.get_nowait()
                        except queue.Empty:
                            pass
                    self.frame_queue.put(frame)
        finally:
            self.capture.stop()
            print("[Core] 采集线程已停止")

    def _inference_loop(self):
        """推理与控制线程：消费图像并执行动作"""
        print("[Core] 推理线程已启动")
        prev_time = time.time()
        
        while not self.stop_event.is_set():
            try:
                # 获取最新一帧
                frame = self.frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # A. 执行 AI 推理
            results = self.inference.predict(frame)
            
            # B. 目标筛选与锁定 (中心距离优先 + FOV 限制)
            target = None
            min_dist = float('inf')
            
            for res in results:
                x1, y1, x2, y2, conf, cls = res
                if int(cls) in self.target_class_ids:
                    # 计算目标中心点
                    tx, ty = (x1 + x2) / 2, (y1 + y2) / 2
                    
                    # 计算到准星(屏幕中心)的距离
                    dist = math.sqrt((tx - self.screen_center[0])**2 + (ty - self.screen_center[1])**2)
                    
                    # FOV 过滤：只有在圆圈范围内的目标才会被锁定
                    if dist < (self.fov_size / 2):
                        if dist < min_dist:
                            min_dist = dist
                            target = res
            
            # C. 执行输入反馈
            if target is not None:
                x1, y1, x2, y2, conf, cls = target
                center_x = int((x1 + x2) / 2)
                center_y = int((y1 + y2) / 2)
                
                # 拟人化平滑移动
                if self.smooth_move:
                    self.input.smooth_move_to(center_x, center_y, self.smooth_duration) 
                else:
                    self.input.move_to(center_x, center_y)
                
                if self.show_debug:
                    cv2.circle(frame, (center_x, center_y), 5, (0, 0, 255), -1)
                    cv2.putText(frame, "LOCKED", (center_x + 10, center_y), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            # D. 处理调试显示数据
            if self.show_debug:
                # 绘制 FOV 范围圆圈
                cv2.circle(frame, self.screen_center, int(self.fov_size / 2), (255, 255, 255), 1)
                
                # 在画面上绘制所有识别框
                for (x1, y1, x2, y2, conf, cls) in results:
                    color = (0, 255, 0)
                    # 如果是当前目标，用不同颜色标识
                    if target is not None and all(target == [x1, y1, x2, y2, conf, cls]):
                        color = (0, 0, 255)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                
                curr_time = time.time()
                fps = 1 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0
                prev_time = curr_time
                cv2.putText(frame, f"FPS: {int(fps)}", (10, 30), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                
                # 将处理后的帧放入调试队列
                if self.debug_queue.full():
                    try:
                        self.debug_queue.get_nowait()
                    except queue.Empty:
                        pass
                self.debug_queue.put(frame)

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
