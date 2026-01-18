import time
import math
import sys
import os

# 添加 src 目录到路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from input.dd_input import DDInput
from utils.hotkey import is_hotkey_pressed

def main():
    print("=== DD 驱动与热键测试脚本 ===")
    print("功能：")
    print("1. 检测 Alt 键状态")
    print("2. 按住 Alt 键时，鼠标会自动画圆运动")
    print("3. 监控循环延迟，检测驱动是否阻塞")
    print("\n正在初始化 DD 驱动...")
    
    try:
        dd = DDInput()
        # 检查是否真的初始化成功
        if not dd._is_initialized: # 注意：这里访问了私有变量，仅用于调试
            print("\n[ERROR] 驱动未正确初始化 (DD_btn(0) != 1)")
            print("请尝试以管理员身份运行，或检查是否有其他程序占用驱动。")
            # return # 暂时不退出，看看能否强制工作
        
        # 预热
        dd.move_rel(0, 0)
        print("驱动初始化完成！")
    except Exception as e:
        print(f"驱动初始化失败: {e}")
        return

    print("\n开始测试 loop (按 Ctrl+C 退出)...")
    
    center_x, center_y = 0, 0
    radius = 50
    angle = 0
    
    try:
        while True:
            loop_start = time.perf_counter()
            
            # 1. 检测 Alt 键
            is_alt = is_hotkey_pressed("Alt")
            
            # 2. 如果按下 Alt，移动鼠标
            if is_alt:
                # 计算画圆的相对移动
                # 简单的简谐运动
                angle += 0.1
                dx = int(math.cos(angle) * 10)
                dy = int(math.sin(angle) * 10)
                
                # 调用驱动
                dd_start = time.perf_counter()
                dd.move_rel(dx, dy)
                dd_cost = (time.perf_counter() - dd_start) * 1000
                
                print(f"\r[Alt PRESSED] Move: ({dx}, {dy}) | Driver Cost: {dd_cost:.2f}ms", end="")
            else:
                print(f"\r[Alt Released] Waiting...                                 ", end="")
            
            # 3. 循环频率控制
            time.sleep(0.01) # 10ms
            
            total_cost = (time.perf_counter() - loop_start) * 1000
            # 如果总耗时显著超过 sleep 时间，说明有阻塞
            if total_cost > 20:
                print(f"\n[WARNING] Loop lag detected: {total_cost:.2f}ms")

    except KeyboardInterrupt:
        print("\n测试结束。")
    except Exception as e:
        print(f"\n测试出错: {e}")

if __name__ == "__main__":
    main()
