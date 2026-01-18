# from .win32_input import Win32Input
# from .dd_input import DDInput

def create_input(method="dd"):
    """
    输入模块工厂方法
    """
    if method == "dd":
        from .dd_input import DDInput
        return DDInput()
    elif method == "win32":
        from .win32_input import Win32Input
        return Win32Input()
    
    # 默认回退到 DD (或者可以改为报错)
    print(f"[Input] 未知输入方法 '{method}'，默认使用 DD")
    from .dd_input import DDInput
    return DDInput()
