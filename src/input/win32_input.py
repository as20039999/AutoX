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
        
        # 终极防御：限制 x, y 在 C int32 范围内，防止 OverflowError
        # mouse_event 的参数是 DWORD, LONG, LONG, DWORD, ULONG_PTR
        # LONG 是 32 位有符号整数 (-2,147,483,648 到 2,147,483,647)
        try:
            x = max(-2147483648, min(2147483647, int(x)))
            y = max(-2147483648, min(2147483647, int(y)))
            self.user32.mouse_event(flags, x, y, data, 0)
        except OverflowError:
            # 如果依然溢出（理论上 int(x) 已经解决了 Python 层面的问题），打印并跳过
            print(f"[Input] 鼠标事件坐标溢出: x={x}, y={y}")

    def move_to(self, x: int, y: int):
        self._send_mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, x, y)

    def smooth_move_to(self, x: int, y: int, duration: float = 0.1, human_curve: bool = False):
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
        
        self.smooth_move_rel(dx, dy, duration, human_curve)

    def move_rel(self, dx: int, dy: int):
        self._send_mouse_event(MOUSEEVENTF_MOVE, dx, dy)

    def smooth_move_rel(self, dx: int, dy: int, duration: float = 0.1, human_curve: bool = False):
        """
        使用正弦加速/减速曲线实现平滑移动
        :param dx: 相对 X 偏移
        :param dy: 相对 Y 偏移
        :param duration: 移动总时长 (秒)
        :param human_curve: 是否模拟人类随机曲线
        """
        if dx == 0 and dy == 0:
            return

        target_freq = 60
        steps = max(int(duration * target_freq), 1)
        interval = duration / steps
        
        # 强制最小间隔，防止过高频调用导致系统中断风暴
        if interval < 0.016:
            interval = 0.016
        
        current_dx = 0
        current_dy = 0
        
        # 如果启用人类曲线，生成一个中途的随机偏移点
        ctrl_x, ctrl_y = 0, 0
        if human_curve:
            # 在垂直于移动方向的轴上产生偏移
            dist = math.sqrt(dx**2 + dy**2)
            if dist > 10:
                offset_scale = dist * 0.1  # 偏移量约为距离的 10%
                # 垂直向量 (-dy, dx)
                v_x, v_y = -dy / dist, dx / dist
                rand_offset = random.uniform(-offset_scale, offset_scale)
                ctrl_x, ctrl_y = v_x * rand_offset, v_y * rand_offset

        for i in range(1, steps + 1):
            t = i / steps
            
            if human_curve:
                # 使用二次贝塞尔曲线公式: (1-t)^2*P0 + 2(1-t)t*P1 + t^2*P2
                # 这里 P0=(0,0), P2=(dx, dy), P1=(dx/2 + ctrl_x, dy/2 + ctrl_y)
                # target_x(t) = 2(1-t)t*(dx/2 + ctrl_x) + t^2*dx
                target_dx = 2 * (1 - t) * t * (dx / 2 + ctrl_x) + t**2 * dx
                target_dy = 2 * (1 - t) * t * (dy / 2 + ctrl_y) + t**2 * dy
            else:
                # 正弦 S 曲线
                multiplier = (1 - math.cos(t * math.pi)) / 2
                target_dx = dx * multiplier
                target_dy = dy * multiplier
            
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
        final_dx = dx - int(current_dx)
        final_dy = dy - int(current_dy)
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
