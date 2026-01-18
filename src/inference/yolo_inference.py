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
        
        # 检查是否为 GPU Tensor 输入
        is_gpu_input = False
        if is_batch and len(frame_or_frames) > 0 and isinstance(frame_or_frames[0], torch.Tensor):
            is_gpu_input = True
        elif isinstance(frame_or_frames, torch.Tensor):
            is_gpu_input = True
        
        # 增加异常捕获
        try:
            # 执行推理
            # verbose=False: 减少日志
            # iou=self.iou_thres: NMS 阈值
            # conf=self.conf_thres: 置信度阈值
            
            # [DEBUG] 打印推理前时间点
            # print(f"[Inf-Debug] Start Predict: {time.perf_counter():.4f}", flush=True)
            
            # 优化：移除强制同步，改用异步流 (需上层保证数据准备完毕)
            # if self.device == 'cuda':
            #     torch.cuda.synchronize()

            if is_gpu_input:
                results = self._predict_gpu(frame_or_frames)
            else:
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

    def _predict_gpu(self, frame_or_frames):
        """专门处理 GPU Tensor 输入的推理流程"""
        # 1. 预处理 (HWC uint8 -> BCHW float32 normalized & resized)
        # 支持 Batch
        if isinstance(frame_or_frames, list):
            # Stack tensors
            if not frame_or_frames: return []
            input_tensor = torch.stack(frame_or_frames)
        else:
            input_tensor = frame_or_frames.unsqueeze(0)
            
        # 记录原始尺寸 (H, W)
        orig_shape = input_tensor.shape[1:3]
        
        # 预处理
        preprocessed_tensor, ratio_pad = self._preprocess_tensor_gpu(input_tensor)
        
        # 2. 推理
        results = self.model.predict(
            preprocessed_tensor, 
            verbose=False, 
            device=self.device,
            iou=self.iou_thres,
            conf=self.conf_thres,
            half=False,
            save=False,
            project=self.project_root,
            name=".",
            exist_ok=True
        )
        
        # 3. 后处理 (Box Rescaling)
        # 手动将 resize/pad 后的坐标映射回原图
        for res in results:
             if res.boxes is not None:
                 self._scale_boxes_gpu(res.boxes.data, ratio_pad, orig_shape)
                 
        return results

    def _preprocess_tensor_gpu(self, batch_tensor):
        # batch_tensor: (B, H, W, C) uint8
        
        target_size = self.engine_imgsz if self.is_engine else 640
        B, H, W, C = batch_tensor.shape
        
        # Permute to BCHW
        img = batch_tensor.permute(0, 3, 1, 2)
        
        # Float & Norm
        img = img.float() / 255.0
        
        # Resize (LetterBox logic)
        r = min(target_size / H, target_size / W)
        new_unpad = (int(round(W * r)), int(round(H * r)))
        dw, dh = target_size - new_unpad[0], target_size - new_unpad[1]
        dw /= 2
        dh /= 2
        
        if r != 1:
            img = torch.nn.functional.interpolate(img, size=(new_unpad[1], new_unpad[0]), mode='bilinear', align_corners=False)
            
        # Pad
        top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
        left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
        img = torch.nn.functional.pad(img, (left, right, top, bottom), value=0.447)
        
        return img, (r, (dw, dh))

    def _scale_boxes_gpu(self, boxes, ratio_pad, orig_shape):
        # boxes: (N, 6)
        ratio, (dw, dh) = ratio_pad
        H, W = orig_shape
        
        # Undo padding
        boxes[:, [0, 2]] -= dw
        boxes[:, [1, 3]] -= dh
        
        # Undo scaling
        boxes[:, :4] /= ratio
        
        # Clip
        boxes[:, [0, 2]] = boxes[:, [0, 2]].clamp(0, W)
        boxes[:, [1, 3]] = boxes[:, [1, 3]].clamp(0, H)
