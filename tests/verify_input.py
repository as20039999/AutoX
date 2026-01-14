import time
import sys
import os

# 将 src 目录添加到路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from input import create_input

def test_input():
    print("--- 开始 Input 模块验证 ---")
    mouse = create_input(method="win32")
    
    # 获取屏幕中心
    import ctypes
    user32 = ctypes.windll.user32
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    cx, cy = sw // 2, sh // 2
    
    print(f"屏幕分辨率: {sw}x{sh}")
    print(f"1. 移动到屏幕中心 ({cx}, {cy})...")
    mouse.move_to(cx, cy)
    time.sleep(1)
    
    print("2. 执行相对移动 (正方形路径)...")
    steps = [
        (100, 0),   # 右
        (0, 100),   # 下
        (-100, 0),  # 左
        (0, -100)   # 上
    ]
    
    for dx, dy in steps:
        print(f"   相对移动: {dx}, {dy}")
        mouse.move_rel(dx, dy)
        time.sleep(0.5)
        
    print("3. 模拟点击 (请观察是否有反应)...")
    # 为了安全，这里不点任何东西，只是执行代码
    mouse.click('left')
    
    print("--- Input 模块验证完成 ---")

if __name__ == "__main__":
    test_input()
