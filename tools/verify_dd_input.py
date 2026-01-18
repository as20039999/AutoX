import time
import sys
import os
import ctypes

# 添加 src 到路径以便导入
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from input.dd_input import DDInput

def verify_keys():
    print("正在初始化 DD 驱动...")
    try:
        dd = DDInput()
    except Exception as e:
        print(f"初始化失败: {e}")
        return

    print("DD 驱动初始化成功。")
    print("请打开一个【记事本】窗口，并确保它是当前活动窗口。")
    print("脚本将在 3 秒后开始输入测试...")
    time.sleep(3)

    # 1. 测试基础字母 (大小写区分测试)
    # 注意：DDInput 接受的是 VK Code。
    # 'A' 的 VK Code 是 0x41。
    # 'a' 的 ASCII 是 0x61，但这在 VK Code 中是 NumPad1！
    # 如果我们的映射表正确移除了冲突的小键盘映射，且上层逻辑传入正确的 VK Code，
    # 那么这里应该能正确工作。
    
    # 模拟输入 "Hello World"
    # 通常输入法通过 Shift + 字母来实现大写，或者直接发送大写字母的 VK
    
    print("\n--- 开始输入测试 ---")
    
    # 定义要测试的序列：(VK_CODE, 描述)
    test_sequence = [
        (0x48, 'H'), (0x45, 'E'), (0x4C, 'L'), (0x4C, 'L'), (0x4F, 'O'),
        (0x20, 'Space'),
        (0x57, 'W'), (0x4F, 'O'), (0x52, 'R'), (0x4C, 'L'), (0x44, 'D'),
        (0x0D, 'Enter')
    ]

    print("正在输入: HELLO WORLD (如果不按 Shift，显示为小写是正常的)...")
    
    for vk, char in test_sequence:
        print(f"Pressing {char} (VK: {hex(vk)})")
        dd.key_down(vk)
        time.sleep(0.05)
        dd.key_up(vk)
        time.sleep(0.1)

    # 2. 测试数字键 (主键盘区)
    print("\n正在输入数字: 12345...")
    number_sequence = [
        (0x31, '1'), (0x32, '2'), (0x33, '3'), (0x34, '4'), (0x35, '5'),
        (0x0D, 'Enter')
    ]
    for vk, char in number_sequence:
        dd.key_down(vk)
        time.sleep(0.05)
        dd.key_up(vk)
        time.sleep(0.1)

    # 3. 验证冲突修复 (测试 0x61)
    # 之前 0x61 会被映射为 NumPad1，现在如果移除了映射，应该会提示"未映射"或者无反应，
    # 而不是输出数字 '1'。
    print("\n正在验证冲突修复 (尝试输入 VK 0x61)...")
    print("预期结果：如果修复成功，这里应该没有任何字符输入，或者控制台提示'未映射'。")
    print("如果屏幕上出现了 '1'，说明冲突依然存在！")
    
    dd.key_down(0x61)
    time.sleep(0.05)
    dd.key_up(0x61)
    
    print("\n测试完成。")
    print("请检查记事本内容：")
    print("1. 应该看到 hello world (或大写)")
    print("2. 应该看到 12345")
    print("3. 最后不应该出现额外的 '1'")

if __name__ == "__main__":
    verify_keys()
