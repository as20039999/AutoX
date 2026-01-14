import ctypes
import time
import math
import random
from .base import AbstractInput

# Windows API 常量定义
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

class Win32Input(AbstractInput):
    """
    基于 Windows SendInput API 的输入实现
    """
    
    def __init__(self):
        self.user32 = ctypes.windll.user32
        # 获取屏幕分辨率，用于绝对坐标转换
        self.screen_width = self.user32.GetSystemMetrics(0)
        self.screen_height = self.user32.GetSystemMetrics(1)

    def _send_mouse_event(self, flags, x=0, y=0, data=0):
        """内部封装 SendInput 鼠标事件"""
        # 绝对坐标需要转换到 0-65535 范围
        if flags & MOUSEEVENTF_ABSOLUTE:
            x = int(x * 65535 / self.screen_width)
            y = int(y * 65535 / self.screen_height)
            
        self.user32.mouse_event(flags, x, y, data, 0)

    def move_to(self, x: int, y: int):
        self._send_mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, x, y)

    def smooth_move_to(self, x: int, y: int, duration: float = 0.1):
        """
        平滑移动到绝对坐标 (基于当前位置计算相对增量)
        """
        # 获取当前鼠标位置
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        
        pt = POINT()
        self.user32.GetCursorPos(ctypes.byref(pt))
        
        dx = x - pt.x
        dy = y - pt.y
        
        self.smooth_move_rel(dx, dy, duration)

    def move_rel(self, dx: int, dy: int):
        self._send_mouse_event(MOUSEEVENTF_MOVE, dx, dy)

    def smooth_move_rel(self, dx: int, dy: int, duration: float = 0.1):
        """
        使用正弦加速/减速曲线实现平滑移动
        :param dx: 相对 X 偏移
        :param dy: 相对 Y 偏移
        :param duration: 移动总时长 (秒)
        """
        if dx == 0 and dy == 0:
            return

        steps = max(int(duration * 100), 5)  # 至少 5 步，频率约 100Hz
        interval = duration / steps
        
        current_dx = 0
        current_dy = 0
        
        for i in range(1, steps + 1):
            # 使用正弦函数实现 S 型曲线 (0 到 1)
            # t = i / steps
            # multiplier = (1 - math.cos(t * math.pi)) / 2
            
            # 更简单的线性插值配合一点点随机抖动
            t = i / steps
            target_dx = int(dx * t)
            target_dy = int(dy * t)
            
            # 计算这一步需要移动的增量
            step_dx = target_dx - current_dx
            step_dy = target_dy - current_dy
            
            # 注入极小的随机微调 (0.5 像素级别)
            if i < steps:
                step_dx += random.uniform(-0.5, 0.5)
                step_dy += random.uniform(-0.5, 0.5)
            
            self.move_rel(int(step_dx), int(step_dy))
            
            current_dx += int(step_dx)
            current_dy += int(step_dy)
            
            time.sleep(interval)
            
        # 确保最后补偿到精确位置
        final_dx = dx - current_dx
        final_dy = dy - current_dy
        if final_dx != 0 or final_dy != 0:
            self.move_rel(final_dx, final_dy)

    def click(self, button: str = 'left'):
        if button == 'left':
            self._send_mouse_event(MOUSEEVENTF_LEFTDOWN)
            time.sleep(0.01) # 模拟真实点击延迟
            self._send_mouse_event(MOUSEEVENTF_LEFTUP)
        elif button == 'right':
            self._send_mouse_event(MOUSEEVENTF_RIGHTDOWN)
            time.sleep(0.01)
            self._send_mouse_event(MOUSEEVENTF_RIGHTUP)

    def key_down(self, key_code: int):
        self.user32.keybd_event(key_code, 0, 0, 0)

    def key_up(self, key_code: int):
        self.user32.keybd_event(key_code, 0, 2, 0)
