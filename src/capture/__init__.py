from .base import AbstractCapture
from .dda_capture import DDACapture, MSSCapture

def create_capture(method="dda", region=None) -> AbstractCapture:
    """
    图像采集工厂方法
    :param method: 'dda' 或 'mss'
    :param region: (x, y, w, h)
    """
    if method.lower() == "dda":
        try:
            return DDACapture(region=region)
        except Exception as e:
            print(f"DDA 启动失败，切换到 MSS 模式: {e}")
            return MSSCapture(region=region)
    return MSSCapture(region=region)

__all__ = ['AbstractCapture', 'DDACapture', 'MSSCapture', 'create_capture']
