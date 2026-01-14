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

# 确保 src 目录在路径中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from security.license import LicenseManager
from utils.config import ConfigManager
from gui.main_window import MainWindow

class AutoXApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.config = ConfigManager()
        self.controller = None
        self.window = None
        
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
            model_path = self.config.get("inference.model_path", "base.pt")
            device = self.config.get("inference.device", "cuda")
            self.controller = AutoXController(model_path=model_path, device=device)
        except (OSError, ImportError) as e:
            if "1114" in str(e):
                print("\n[!] 系统错误: 显卡驱动初始化失败 (WinError 1114)")
                print("    原因: 通常是由于 Windows 电源模式限制了显卡性能。")
                print("    解决: 1. 插上电源; 2. 在 'Windows设置 -> 图形设置' 中将 Python 设置为 '高性能'。")
            elif "No such file" in str(e) or "FileNotFound" in str(e):
                print(f"\n[!] 错误: 找不到模型文件")
                print(f"    详情: {e}")
                print(f"    解决: 请确保模型文件 (如 base.pt) 存在于项目根目录，或在配置文件中更正路径。")
            else:
                print(f"\n[!] 操作系统错误: {e}")
            return
        except Exception as e:
            print(f"\n[!] 初始化失败: {e}")
            return

        # 3. 初始化 GUI
        self.window = MainWindow(self.controller, self.config)
        self.window.show()
        
        # 4. 进入 Qt 事件循环
        return self.app.exec()

if __name__ == "__main__":
    app_instance = AutoXApp()
    sys.exit(app_instance.run())
