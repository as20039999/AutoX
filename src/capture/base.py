from abc import ABC, abstractmethod
import numpy as np

class AbstractCapture(ABC):
    """
    图像采集基类，定义统一的接口。
    """
    
    def __init__(self, region=None):
        """
        :param region: 采集区域 (x, y, width, height)，None 表示全屏
        """
        self.region = region
        self.is_running = False

    @abstractmethod
    def start(self):
        """开始采集"""
        pass

    @abstractmethod
    def stop(self):
        """停止采集"""
        pass

    @abstractmethod
    def get_frame(self) -> np.ndarray:
        """
        获取当前帧图像
        :return: BGR 格式的 numpy 数组
        """
        pass
