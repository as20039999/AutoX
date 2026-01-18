import time
import sys
import os
import ctypes

# 添加 src 到路径以便导入
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from input.dd_input import DDInput

def verify_special_keys():
    print("正在初始化 DD 驱动...")
    try:
        dd = DDInput()
    except Exception as e:
        print(f"初始化失败: {e}")
        return

    print("DD 驱动初始化成功。")
    print("请打开一个【记事本】窗口，并确保它是当前活动窗口。")
    print("脚本将在 3 秒后开始测试组合键...")
    time.sleep(3)

    print("\n--- 开始特殊按键测试 ---")

    # 1. 测试 Shift 组合键 (输入符号)
    # 按住 Shift 输入 '1' -> 应该是 '!'
    print("\n1. 测试 Shift 组合键: Shift + 1 -> '!'")
    dd.key_down(0x10) # Shift Down
    time.sleep(0.1)
    dd.key_down(0x31) # 1 Down
    time.sleep(0.05)
    dd.key_up(0x31)   # 1 Up
    time.sleep(0.1)
    dd.key_up(0x10)   # Shift Up
    
    # 2. 测试 Ctrl 组合键 (全选)
    # Ctrl + A -> 全选
    print("\n2. 测试 Ctrl 组合键: Ctrl + A -> 全选")
    time.sleep(1) # 给用户一点时间观察
    dd.key_down(0x11) # Ctrl Down
    time.sleep(0.1)
    dd.key_down(0x41) # A Down
    time.sleep(0.05)
    dd.key_up(0x41)   # A Up
    time.sleep(0.1)
    dd.key_up(0x11)   # Ctrl Up

    # 3. 测试 Ctrl + C (复制) 和 Ctrl + V (粘贴)
    # 注意：这需要剪贴板交互，可能不可见，我们用简单的复制粘贴测试
    print("\n3. 测试复制粘贴: Ctrl+C -> End -> Enter -> Ctrl+V")
    # Ctrl + C
    dd.key_down(0x11) # Ctrl
    dd.key_down(0x43) # C
    time.sleep(0.05)
    dd.key_up(0x43)
    dd.key_up(0x11)
    time.sleep(0.5)
    
    # End (取消全选并移动到末尾)
    dd.key_down(0x23) # End
    dd.key_up(0x23)
    time.sleep(0.1)
    
    # Enter (换行)
    dd.key_down(0x0D)
    dd.key_up(0x0D)
    time.sleep(0.1)
    
    # Ctrl + V
    dd.key_down(0x11) # Ctrl
    dd.key_down(0x56) # V
    time.sleep(0.05)
    dd.key_up(0x56)
    dd.key_up(0x11)
    
    # 4. 测试 Alt 键 (Alt + F4 关闭窗口 - 慎用！改用 Alt 菜单)
    # Alt (激活菜单栏)
    print("\n4. 测试 Alt 键: 按下 Alt 激活菜单栏")
    dd.key_down(0x12) # Alt
    time.sleep(0.1)
    dd.key_up(0x12)
    
    print("\n测试完成。")
    print("请验证：")
    print("1. 是否输入了 '!'")
    print("2. 是否执行了全选 (Ctrl+A)")
    print("3. 是否成功复制粘贴了内容")
    print("4. 记事本菜单栏是否被激活 (首字母带下划线)")

if __name__ == "__main__":
    verify_special_keys()
