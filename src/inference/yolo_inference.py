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

# apply_torch_safety_patch()  <-- 移除了这里的全局调用

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
        
        # 在禁用同步设置后，再应用安全补丁（补丁中包含 import ultralytics.nn.tasks，可能会触发初始化）
        apply_torch_safety_patch()
        
        self.model = YOLO(self.model_path)
        self.project_root = get_root_path()
        
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
        # 创建一个空图像进行预热，确保尺寸匹配
        warmup_imgsz = self.engine_imgsz if self.is_engine else 640
        dummy_input = np.zeros((warmup_imgsz, warmup_imgsz, 3), dtype=np.uint8)
        
        try:
            self.model.predict(
                dummy_input, 
                verbose=False, 
                device=self.device, 
                half=False, 
                save=False,
                project=self.project_root,
                name=".", # 指向已存在的根目录
                exist_ok=True
            )
        except Exception as e:
            print(f"[Inference] 预热失败: {e}")
            
        print("[Inference] 模型加载并预热完成。")

    def predict(self, frame_or_frames):
        import time
        t_start = time.perf_counter()
        
        # 兼容单帧和多帧 (Batch)
        is_batch = isinstance(frame_or_frames, list)
        
        # 增加异常捕获
        try:
            # 执行推理
            # verbose=False: 减少日志
            # iou=self.iou_thres: NMS 阈值
            # conf=self.conf_thres: 置信度阈值
            
            # [DEBUG] 打印推理前时间点
            # print(f"[Inf-Debug] Start Predict: {time.perf_counter():.4f}", flush=True)
            
            # 强制同步 CUDA 流，确保之前的 GPU 操作（如 DDA 采集）已完成
            # 这有助于避免资源冲突，虽然会轻微增加 CPU 等待时间
            if self.device == 'cuda':
                torch.cuda.synchronize()

            results = self.model.predict(
                frame_or_frames, 
                verbose=False, 
                device=self.device,
                iou=self.iou_thres,
                conf=self.conf_thres,
                half=False, # 强制使用 FP32，避免 TensorRT FP16 精度问题或崩溃
                save=False,
                project=self.project_root,
                name=".",
                exist_ok=True
            )
            
            # [DEBUG] 打印推理后时间点
            # print(f"[Inf-Debug] End Predict: {time.perf_counter():.4f}", flush=True)
            
        except Exception as e:
            print(f"[Inference] 推理异常: {e}")
            return [] if is_batch else []

        t_post = time.perf_counter()
        parsed_results = []
        for result in results:
            # 提取检测框
            boxes = result.boxes
            frame_detections = []
            
            if boxes is not None:
                # 遍历所有检测到的目标
                # boxes.data 包含 (x1, y1, x2, y2, conf, cls)
                for box in boxes.data:
                    x1, y1, x2, y2, conf, cls = box.tolist()
                    
                    # 再次过滤 (双重保险)
                    if conf >= self.conf_thres:
                        # 坐标取整
                        frame_detections.append((
                            int(x1), int(y1), int(x2), int(y2), 
                            float(conf), int(cls)
                        ))
            
            parsed_results.append(frame_detections)
        
        # [DEBUG] 耗时检测
        # dt = (time.perf_counter() - t_start) * 1000
        # if dt > 50:
        #    print(f"[Inference] Slow batch: {dt:.1f}ms (Infer: {(t_post - t_start)*1000:.1f}ms)", flush=True)
            
        # 如果输入是单帧，返回单个结果列表；如果是 Batch，返回列表的列表
        if not is_batch:
            return parsed_results[0]
        return parsed_results
