import sys
import os
import time

# 必须在导入 PySide6 之前导入 torch 和 cv2，防止显卡驱动初始化冲突 (WinError 1114)
try:
    import torch
    import cv2
except ImportError:
    pass

import ctypes
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

# 确保 src 目录在路径中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from security.license import LicenseManager
from utils.config import ConfigManager
from gui.main_window import MainWindow
import queue

class AutoXApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.config = ConfigManager()
        self.controller = None
        self.window = None
        self._excluded_windows = set()
        
        # UI 更新定时器 (用于处理 OpenCV 渲染)
        self.ui_timer = QTimer()
        self.ui_timer.timeout.connect(self._process_debug_view)

    def _exclude_from_capture(self, window_name=None, hwnd=None):
        """设置窗口不被截屏软件捕捉，防止递归采集"""
        try:
            if window_name:
                hwnd = ctypes.windll.user32.FindWindowW(None, window_name)
            
            if hwnd and hwnd not in self._excluded_windows:
                # WDA_EXCLUDEFROMCAPTURE = 0x00000011 (Win10 2004+)
                # 尝试设置为排除模式，如果失败则回退到 WDA_MONITOR
                if not ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x00000011):
                    ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x00000001)
                self._excluded_windows.add(hwnd)
                print(f"[Main] 已将窗口 {window_name or hwnd} 排除在采集之外")
        except Exception as e:
            print(f"[Main] 排除窗口采集失败: {e}")

    def run(self):
        print("========================================")
        print("        AutoX - AI 自动化控制系统        ")
        print("========================================")
        
        # 1. 安全授权检查
        print("[Main] 正在进行安全环境检查...")
        if not LicenseManager.verify_local_license():
            print("\n[!] 错误: 未检测到有效授权，请先运行验证脚本生成测试 Key。")
            return

        # 2. 初始化核心控制器
        try:
            from core.controller import AutoXController
            model_path = self.config.get("inference.model_path", "yolov8n.pt")
            device = self.config.get("inference.device", "cuda")
            self.controller = AutoXController(model_path=model_path, device=device)
        except (OSError, ImportError) as e:
            if "1114" in str(e):
                print("\n[!] 系统错误: 显卡驱动初始化失败 (WinError 1114)")
                print("    原因: 通常是由于 Windows 电源模式限制了显卡性能。")
                print("    解决: 1. 插上电源; 2. 在 'Windows设置 -> 图形设置' 中将 Python 设置为 '高性能'。")
            else:
                print(f"\n[!] 操作系统错误: {e}")
            return
        except Exception as e:
            print(f"\n[!] 初始化失败: {e}")
            return

        # 3. 初始化 GUI
        self.window = MainWindow(self.controller, self.config)
        self.window.show()
        
        # 将主窗口排除在采集之外
        self._exclude_from_capture(hwnd=self.window.winId())
        
        # 4. 启动 UI 轮询
        self.ui_timer.start(10) # 10ms 频率检查队列

        # 5. 进入 Qt 事件循环
        return self.app.exec()

    def _process_debug_view(self):
        """在主线程处理 OpenCV 窗口更新"""
        if self.controller and self.controller.show_debug:
            try:
                window_name = "AutoX Debug View"
                
                # 尝试从控制器的调试队列中获取渲染后的画面
                frame_to_show = None
                while not self.controller.debug_queue.empty():
                    frame_to_show = self.controller.debug_queue.get_nowait()
                
                if frame_to_show is not None:
                    cv2.imshow(window_name, frame_to_show)
                    # 首次创建窗口后，将其排除在采集之外
                    self._exclude_from_capture(window_name=window_name)
                    
                # 响应 OpenCV 内部事件
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    self.controller.show_debug = False
                    cv2.destroyWindow(window_name)
                    # 窗口销毁后，从记录中移除
                    self._excluded_windows.clear() # 简单处理，下次重建会重新加入
            except Exception as e:
                print(f"[Main] 预览更新错误: {e}")
        else:
            # 如果关闭了预览，确保窗口被销毁
            try:
                # 检查窗口是否存在再销毁，防止报错
                if cv2.getWindowProperty("AutoX Debug View", cv2.WND_PROP_VISIBLE) >= 0:
                    cv2.destroyWindow("AutoX Debug View")
                    self._excluded_windows.clear()
            except Exception:
                pass

if __name__ == "__main__":
    app_instance = AutoXApp()
    sys.exit(app_instance.run())
