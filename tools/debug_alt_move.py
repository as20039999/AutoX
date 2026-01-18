import time
import sys
import os
import math

# 添加 src 到路径以便导入
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from utils.hotkey import is_hotkey_pressed
from input.dd_input import DDInput

def debug_alt_move():
    print("正在初始化 DD 驱动...")
    try:
        dd = DDInput()
    except Exception as e:
        print(f"DD 驱动初始化失败: {e}")
        return

    print("DD 驱动初始化成功。")
    print("\n--- 测试说明 ---")
    print("1. 请按住【Alt】键。")
    print("2. 如果检测到 Alt 按下，鼠标将自动画圆移动。")
    print("3. 松开 Alt 键停止移动。")
    print("4. 按【Ctrl + C】退出脚本。")
    print("----------------")

    t = 0
    try:
        while True:
            # 1. 检测 Alt 键
            is_alt = is_hotkey_pressed("Alt")
            
            # 同时也检测一下 LAlt 和 RAlt，看看具体是哪个生效
            is_lalt = is_hotkey_pressed("LAlt")
            is_ralt = is_hotkey_pressed("RAlt")
            
            status_str = f"Alt: {is_alt} (L:{is_lalt} R:{is_ralt})"
            print(f"\r{status_str}   ", end="")
            
            if is_alt:
                # 2. 执行移动
                radius = 10
                dx = int(radius * math.cos(t))
                dy = int(radius * math.sin(t))
                
                # 相对移动
                dd.move_rel(dx, dy)
                t += 0.5
            
            time.sleep(0.01)
            
    except KeyboardInterrupt:
        print("\n测试结束。")

if __name__ == "__main__":
    debug_alt_move()
