import time
import sys
import os

# 将 src 目录添加到路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from input.dd_input import DDInput

def test_dd():
    print("--- 开始 DD 驱动功能测试 ---")
    try:
        dd = DDInput()
        print(f"屏幕分辨率: {dd.screen_width}x{dd.screen_height}")
        
        cx, cy = dd.screen_width // 2, dd.screen_height // 2
        print(f"1. 移动到屏幕中心 ({cx}, {cy})...")
        dd.move_to(cx, cy)
        time.sleep(1)
        
        print("2. 相对移动 (正方形路径)...")
        steps = [(100, 0), (0, 100), (-100, 0), (0, -100)]
        for dx, dy in steps:
            print(f"   移动: {dx}, {dy}")
            dd.move_rel(dx, dy)
            time.sleep(0.5)
            
        print("3. 平滑相对移动 (拟人曲线)...")
        dd.smooth_move_rel(200, 200, duration=1.0, human_curve=True)
        time.sleep(1)
        
        print("4. 测试点击 (右键)...")
        dd.click('right')
        time.sleep(1)
        
        print("5. 测试输入 (A 键)...")
        # 0x41 是 A 键的 VK 码
        dd.key_down(0x41)
        time.sleep(0.1)
        dd.key_up(0x41)
        
        print("--- DD 驱动测试完成 ---")
    except Exception as e:
        print(f"--- 测试失败: {e}")

if __name__ == "__main__":
    test_dd()
