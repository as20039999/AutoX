import os
import sys
import time

# 将当前目录加入路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import syscall_input_lib
    print("成功加载 syscall_input_lib 模块！")
    
    # 测试：向右移动 1 个像素
    # type=0 (MOUSE), dx=1, dy=0, flags=1 (RELATIVE MOVE)
    print("尝试模拟鼠标移动 (Syscall)...")
    status = syscall_input_lib.send_input([
        {"type": 0, "dx": 1, "dy": 0, "flags": 1}
    ])
    print(f"执行状态 (NTSTATUS): {hex(status if status >= 0 else (1<<32)+status)}")
    
except Exception as e:
    print(f"测试失败: {e}")
