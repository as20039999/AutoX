import numpy as np
import mss
import dxcam
import ctypes
from .base import AbstractCapture

class MSSCapture(AbstractCapture):
    """
    使用 mss 库实现的图像采集（作为 DDA 失败时的备选方案）。
    """
    
    def __init__(self, region=None):
        super().__init__(region)
        self.sct = None
        self.monitor = None

    def start(self):
        self.sct = mss.mss()
        if self.region:
            # region: (x, y, w, h) -> mss: {left, top, width, height}
            self.monitor = {
                "top": self.region[1],
                "left": self.region[0],
                "width": self.region[2],
                "height": self.region[3]
            }
        else:
            self.monitor = self.sct.monitors[1]
        self.is_running = True

    def stop(self):
        if self.sct:
            self.sct.close()
            self.sct = None
        self.is_running = False

    def get_frame(self) -> np.ndarray:
        if not self.is_running:
            return None
        sct_img = self.sct.grab(self.monitor)
        # mss 返回的是 BGRA，直接切片取前三个通道即为 BGR
        # 替代 cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        return np.array(sct_img)[:, :, :3]

class DDACapture(AbstractCapture):
    """
    基于 DXCAM 实现的高性能 Desktop Duplication API (DDA) 采集。
    支持 GPU 直接读取，延迟极低。
    """
    def __init__(self, region=None, device_idx=0, output_idx=0):
        super().__init__(region)
        self.camera = None
        self.device_idx = device_idx
        self.output_idx = output_idx
        self.cuda_interop = None
        self.enable_gpu_capture = True # 标记 GPU 采集是否可用

    def start(self):
        # dxcam.create 会自动选择最佳配置
        # region 格式: (left, top, right, bottom)
        dx_region = None
        if self.region:
            dx_region = (
                self.region[0], 
                self.region[1], 
                self.region[0] + self.region[2], 
                self.region[1] + self.region[3]
            )
        
        self.camera = dxcam.create(
            device_idx=self.device_idx, 
            output_idx=self.output_idx, 
            region=dx_region,
            output_color="BGR" # 直接输出 BGR 格式，省去转换耗时
        )
        if self.camera:
            # 这里的 start/stop 是为了控制 dxcam 的生命周期，但不启动其内置线程
            # 因为 AutoXController 已经有独立的采集线程
            # 我们手动调用 grab 或 get_gpu_frame
            self.is_running = True
        else:
            raise RuntimeError("Failed to initialize DXCAM (DDA).")

    def stop(self):
        if self.camera:
            try:
                # 释放资源
                self.camera.release()
            except Exception as e:
                print(f"[Capture] DXCAM stop error: {e}")
            finally:
                del self.camera
                self.camera = None
        
        # 清理 CUDA Interop 资源
        self.cuda_interop = None
        self.is_running = False

    def get_frame(self) -> np.ndarray:
        if not self.is_running or not self.camera:
            return None
        
        # 手动采集模式：直接调用 grab
        # 这会阻塞直到获取到新帧 (或者返回 None)
        return self.camera.grab()

    def get_gpu_frame(self):
        """
        获取 GPU 显存中的图像帧 (Torch Tensor)。
        实现零拷贝 (Zero-Copy) 采集，直接用于 TensorRT 推理。
        """
        if not self.enable_gpu_capture or not self.is_running or not self.camera:
            return None
        
        try:
            # 获取内部 duplicator 对象
            duplicator = self.camera._duplicator
        except AttributeError:
            return None

        # 尝试更新帧
        # 注意：如果 DDA 采集失败，update_frame 可能会抛出错误，需捕获
        try:
            if not duplicator.update_frame():
                return None
        except Exception as e:
            # 这里的错误通常是临时的（如超时），不一定致命
            # print(f"[Capture] DDA Update Error: {e}") 
            return None
            
        if not duplicator.updated:
            return None
        
        try:
            # 延迟初始化 CUDA Interop
            if self.cuda_interop is None:
                # 使用绝对导入避免路径问题 (假设 src 在 sys.path 中)
                try:
                    from utils.cuda_interop import CUDAInterop
                except ImportError:
                    # 备用方案：如果 utils 不是顶级包
                    from src.utils.cuda_interop import CUDAInterop
                
                # self.camera.width/height 是全屏分辨率
                # self.camera.region 是截取区域 (left, top, right, bottom)
                self.cuda_interop = CUDAInterop(
                    self.camera.width, 
                    self.camera.height, 
                    self.camera.region
                )
                
                # 获取 D3D11 纹理指针
                # duplicator.texture 是 POINTER(ID3D11Texture2D)
                texture_ptr = ctypes.cast(duplicator.texture, ctypes.c_void_p).value
                self.cuda_interop.register_resource(texture_ptr)
            
            # 获取 Tensor (从 D3D11 纹理复制到 CUDA Buffer)
            tensor = self.cuda_interop.get_tensor()
            return tensor
            
        except Exception as e:
            # 捕获严重错误 (如 Error 101 设备不匹配)
            # 仅打印一次警告，并永久禁用 GPU 采集
            print(f"[Capture] 🔴 GPU 采集初始化失败: {e}")
            print("[Capture] ⚠️ 检测到跨显卡配置 (AMD采集/NVIDIA推理) 或驱动不兼容。")
            print("[Capture] 🔄 已自动回退到 CPU 采集模式 (性能稍低但稳定)。")
            self.enable_gpu_capture = False
            return None
        finally:
            # 必须释放帧，否则 DDA 会阻塞
            duplicator.release_frame()
    
        return None
