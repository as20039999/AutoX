import numpy as np
import mss
import dxcam
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
            # 启动缓存循环
            # target_fps 设为 60，以支持更高刷新率，确保推理模块获取最新帧
            # video_mode=True 对于高频采集很有帮助
            self.camera.start(target_fps=60, video_mode=True)
            self.is_running = True
        else:
            raise RuntimeError("Failed to initialize DXCAM (DDA).")

    def stop(self):
        if self.camera:
            try:
                # 显式停止采集循环
                self.camera.stop()
            except Exception as e:
                print(f"[Capture] DXCAM stop error: {e}")
            finally:
                # 销毁对象，释放显存/显存映射
                del self.camera
                self.camera = None
        self.is_running = False

    def get_frame(self) -> np.ndarray:
        if not self.is_running or not self.camera:
            return None
        
        # get_latest_frame 获取最近的一帧
        return self.camera.get_latest_frame()
