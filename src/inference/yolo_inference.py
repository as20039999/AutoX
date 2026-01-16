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
        
        # 处理模型路径：如果是相对路径（只是个文件名），则拼接到项目根目录下的 models 文件夹
        if not os.path.isabs(self.model_path):
            # 优先从 models 文件夹查找，如果没有，再尝试从根目录找
            local_model_path = get_abs_path(os.path.join("models", self.model_path))
            if os.path.exists(local_model_path):
                self.model_path = local_model_path
            else:
                self.model_path = get_abs_path(self.model_path)
            
        # 优先尝试加载同名的 .engine 文件 (TensorRT)
        engine_path = self.model_path.rsplit('.', 1)[0] + '.engine'
        use_trt = False
        
        if os.path.exists(engine_path):
            print(f"[Inference] 检测到 TensorRT 模型: {engine_path}")
            self.model_path = engine_path
            use_trt = True
        elif not os.path.exists(self.model_path):
            print(f"[Inference] 错误: 找不到模型文件 {self.model_path}")
            # 尝试回退到 base.pt
            fallback_path = get_abs_path("base.pt")
            if os.path.exists(fallback_path) and self.model_path != fallback_path:
                print(f"[Inference] 尝试回退到默认模型: {fallback_path}")
                self.model_path = fallback_path
            else:
                raise FileNotFoundError(f"找不到模型文件: {self.model_path}")

        print(f"[Inference] 正在加载模型: {self.model_path}")
        
        # 禁用 ultralytics 的自动设置更新和全局路径查找，确保自包含
        try:
            from ultralytics.utils import SETTINGS as settings
            settings.update({'sync': False, 'settings_version': '0.0.0'}) # 避免同步到全局配置
        except ImportError:
            try:
                from ultralytics.utils import settings
                settings.update({'sync': False, 'settings_version': '0.0.0'})
            except ImportError:
                pass
        
        self.model = YOLO(self.model_path)
        
        # 强制检查设备
        if self.device == 'cuda' and not torch.cuda.is_available():
            print("[Inference] 警告: 指定了 CUDA 但不可用，回退到 CPU 模式")
            self.device = 'cpu'
            
        mode_name = "TensorRT" if use_trt else "PyTorch"
        print(f">>> 运行模式: {mode_name} (Device: {self.device}) <<<")

        # 记录是否为 Engine 以及其固定的 imgsz
        self.is_engine = use_trt
        if self.is_engine:
            # TensorRT 通常有固定的输入尺寸
            self.engine_imgsz = self.model.overrides.get('imgsz', 640)
            if isinstance(self.engine_imgsz, (list, tuple)):
                self.engine_imgsz = max(self.engine_imgsz)
            print(f"[Inference] TensorRT 固定输入尺寸: {self.engine_imgsz}")
            
        # 模型预热 (Warmup)
        # TensorRT 模型在第一次运行会有一定的初始化耗时
        warmup_size = self.engine_imgsz if self.is_engine else 640
        warmup_img = np.zeros((warmup_size, warmup_size, 3), dtype=np.uint8)
        self.model.predict(
            warmup_img, 
            device=self.device, 
            half=(self.device == 'cuda'), # 仅在 GPU 上使用 FP16
            imgsz=warmup_size,
            verbose=False
        )
        print("[Inference] 模型加载并预热完成。")

    def predict(self, frame_or_list):
        """
        执行推理并返回标准化的检测结果。
        支持单帧 (np.ndarray) 或多帧 (List[np.ndarray]) 批处理。
        返回格式: 
            如果是单帧: List[tuple] (detections)
            如果是多帧: List[List[tuple]] (batch_detections)
        """
        if self.model is None:
            return [] if isinstance(frame_or_list, np.ndarray) else [[] for _ in frame_or_list]

        is_batch = isinstance(frame_or_list, (list, tuple))
        frames = frame_or_list if is_batch else [frame_or_list]

        # 动态计算 imgsz (取第一帧，假设批次内尺寸一致)
        if self.is_engine:
            imgsz = self.engine_imgsz
        else:
            h, w = frames[0].shape[:2]
            max_dim = max(h, w)
            # 优化：平衡精度与性能
            # 即使在全屏模式下，也不要超过 640，除非显卡非常强。
            # 960 会导致推理耗时翻倍，产生明显的卡顿感。
            # 为了解决不精准问题，我们依赖 sub-pixel 坐标，而不是单纯增加分辨率。
            imgsz = max(320, min(640, ((max_dim + 31) // 32) * 32))

        # 执行推理
        try:
            # 进一步精简参数，确保 TensorRT 运行在最快路径
            results = self.model.predict(
                source=frames,
                imgsz=imgsz,
                conf=self.conf_thres,
                iou=self.iou_thres,
                device=self.device,
                half=True,
                verbose=False,
                show=False,
                save=False,
                stream=False,
                augment=False,
                agnostic_nms=False,
                max_det=10,        # 进一步减少检测数，FPS 游戏通常只需要前几个目标
                classes=self.target_class_ids if hasattr(self, 'target_class_ids') else None, # 在推理层过滤类别，减少后处理
                rect=True          # 开启矩形推理，减少填充导致的无效计算
            )
        except Exception as e:
            # 如果批处理失败（通常是 TensorRT Engine 固定了 batch size）
            if is_batch:
                # 降级为循环单次推理
                results = []
                for f in frames:
                    res = self.model.predict(
                        source=f, imgsz=imgsz, conf=self.conf_thres, iou=self.iou_thres,
                        device=self.device, half=True, verbose=False, max_det=20
                    )
                    results.extend(res)
            else:
                raise e

        batch_detections = []
        for result in results:
            detections = []
            if result.boxes is not None:
                # 优化：直接从 tensor 批量转换 numpy
                boxes_data = result.boxes.data.cpu().numpy()
                for i in range(len(boxes_data)):
                    b = boxes_data[i]
                    detections.append((int(b[0]), int(b[1]), int(b[2]), int(b[3]), b[4], int(b[5])))
            batch_detections.append(detections)
        
        return batch_detections if is_batch else batch_detections[0]
