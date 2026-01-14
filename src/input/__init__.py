from .win32_input import Win32Input

def create_input(method="win32"):
    """
    输入模块工厂方法
    """
    if method == "win32":
        return Win32Input()
    # 未来可在此扩展驱动级输入，如: return KMBoxInput()
    return Win32Input()
