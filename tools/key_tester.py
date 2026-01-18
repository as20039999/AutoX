import time
import sys
import os
import ctypes

# 添加 src 到路径以便导入
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from input.dd_input import DDInput

def test_keys():
    print("正在初始化 DD 驱动...")
    try:
        dd = DDInput()
    except Exception as e:
        print(f"初始化失败: {e}")
        return

    print("DD 驱动初始化成功。")
    print("请打开一个记事本窗口，并确保它是当前活动窗口。")
    print("脚本将在 3 秒后开始测试...")
    time.sleep(3)

    # 测试常用字符键
    test_chars = [
        (0x41, 'A'), (0x42, 'B'), (0x31, '1'), (0x32, '2'),
        (0x20, 'Space'), (0x0D, 'Enter'), (0x08, 'Backspace')
    ]
    
    print("\n--- 测试字符键 ---")
    for vk, name in test_chars:
        print(f"Testing {name} (VK: {hex(vk)})...")
        dd.key_down(vk)
        time.sleep(0.05)
        dd.key_up(vk)
        time.sleep(0.2)
        
    # 测试功能键
    print("\n--- 测试功能键 (不实际按下，仅打印映射) ---")
    special_keys = [
        (0x10, 'Shift'), (0x11, 'Ctrl'), (0x12, 'Alt'),
        (0x25, 'Left'), (0x26, 'Up'), (0x27, 'Right'), (0x28, 'Down')
    ]
    for vk, name in special_keys:
        dd_code = dd.VK_MAP.get(vk)
        print(f"Key: {name}, VK: {hex(vk)} -> DD: {dd_code}")

    print("\n测试完成。如果记事本中出现了 'ab12' 等字符，说明基本映射正常。")
    print("如果有特定按键异常，请记录并反馈。")

if __name__ == "__main__":
    test_keys()
