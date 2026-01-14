from abc import ABC, abstractmethod
import numpy as np

class AbstractInference(ABC):
    """
    AI 推理引擎基类
    """
    
    def __init__(self, model_path, conf_thres=0.25, iou_thres=0.45):
        self.model_path = model_path
        self.conf_thres = conf_thres
        self.iou_thres = iou_thres
        self.model = None

    @abstractmethod
    def load_model(self):
        """加载模型"""
        pass

    @abstractmethod
    def predict(self, frame: np.ndarray):
        """
        对单帧图像进行推理
        :param frame: BGR 图像
        :return: 检测结果列表 (x1, y1, x2, y2, conf, cls)
        """
        pass
