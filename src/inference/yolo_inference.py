import numpy as np
import torch
from ultralytics import YOLO
from .base import AbstractInference



# 兼容 PyTorch 2.6+ 的安全加载机制
# 如果版本低于 2.9 或 ultralytics 未能处理安全加载，保留此补丁
def apply_torch_safety_patch():
    try:
        import torch.nn as nn
        from ultralytics.nn.tasks import DetectionModel
        if hasattr(torch.serialization, 'add_safe_globals'):
            torch.serialization.add_safe_globals([
                nn.modules.container.Sequential,
                nn.modules.container.ModuleList,
                DetectionModel
            ])
    except Exception:
        pass

apply_torch_safety_patch()

class YOLOInference(AbstractInference):
    """
    基于 Ultralytics YOLOv8 的推理实现
    直接使用 PyTorch (.pt) 格式，支持 CUDA 加速。
    """
    
    def __init__(self, model_path, conf_thres=0.25, iou_thres=0.45, device='cuda'):
        super().__init__(model_path, conf_thres, iou_thres)
        self.device = device
        self.load_model()

    def load_model(self):
        import os
        from utils.paths import get_root_path, get_abs_path
        
        # 处理模型路径：如果是相对路径（只是个文件名），则拼接到项目根目录
        if not os.path.isabs(self.model_path):
            self.model_path = get_abs_path(self.model_path)
            
        print(f"[Inference] 正在加载模型: {self.model_path}")
        
        # 检查模型文件是否存在
        if not os.path.exists(self.model_path):
            print(f"[Inference] 错误: 找不到模型文件 {self.model_path}")
            # 尝试回退到 base.pt
            fallback_path = get_abs_path("base.pt")
            if os.path.exists(fallback_path) and self.model_path != fallback_path:
                print(f"[Inference] 尝试回退到默认模型: {fallback_path}")
                self.model_path = fallback_path
            else:
                raise FileNotFoundError(f"找不到模型文件: {self.model_path}")

        # 直接使用 YOLO 加载 .pt 文件
        self.model = YOLO(self.model_path)
        
        # 强制检查设备
        if self.device == 'cuda' and not torch.cuda.is_available():
            print("[Inference] 警告: 指定了 CUDA 但不可用，回退到 CPU 模式")
            self.device = 'cpu'
            
        print(f">>> 运行模式: PyTorch (Device: {self.device}) <<<")
            
        # 模型预热 (Warmup)
        # 使用 1x3x640x640 的随机数据进行一次前向传播
        self.model.predict(
            np.zeros((640, 640, 3), dtype=np.uint8), 
            device=self.device, 
            half=(self.device == 'cuda'), # 仅在 GPU 上使用 FP16
            verbose=False
        )
        print("[Inference] 模型加载并预热完成。")

    def predict(self, frame: np.ndarray):
        """
        执行推理并返回标准化的检测结果
        """
        if self.model is None:
            return []

        # 执行推理
        # task='detect' 显式指定检测任务
        results = self.model.predict(
            source=frame,
            conf=self.conf_thres,
            iou=self.iou_thres,
            device=self.device,
            half=True,  # 使用 FP16 半精度加速
            verbose=False,
            show=False,      # 显式关闭内部显示
            save=False       # 显式关闭保存
        )

        detections = []
        for result in results:
            boxes = result.boxes.cpu().numpy()
            for box in boxes:
                # 获取坐标 (x1, y1, x2, y2), 置信度, 类别
                r = box.xyxy[0].astype(int)
                conf = box.conf[0]
                cls = int(box.cls[0])
                detections.append((r[0], r[1], r[2], r[3], conf, cls))
        
        return detections
