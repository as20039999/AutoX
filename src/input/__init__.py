# from .win32_input import Win32Input

def create_input(method="syscall"):
    """
    输入模块工厂方法
    """
    if method == "win32":
        from .win32_input import Win32Input
        return Win32Input()
    elif method == "syscall":
        from .syscall_input import SyscallInput
        return SyscallInput()
    
    # 默认回退到 syscall
    print(f"[Input] 未知输入方法 '{method}'，默认使用 syscall")
    from .syscall_input import SyscallInput
    return SyscallInput()
