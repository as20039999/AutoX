import os
import sys
import time
import math
import ctypes
import random
import struct
from .base import AbstractInput

class SyscallInput(AbstractInput):
    """
    基于 Direct Syscall (内核直接调用) 的实现
    参考 DD Input 的平滑移动逻辑进行优化，解决 3D 游戏画面移动不准的问题
    """
    
    def __init__(self):
        self.lib = None
        try:
            lib_path = os.path.join(os.path.dirname(__file__), "syscall_wrapper")
            if lib_path not in sys.path:
                sys.path.append(lib_path)
            
            import syscall_input_lib
            self.lib = syscall_input_lib
            
            # 动态检测当前系统的 NtUserSendInput SSN
            ssn = self._detect_ssn()
            if ssn:
                self.lib.set_ssn(ssn)
                print(f"[Input] 成功加载 Syscall 驱动，检测到 SSN: {hex(ssn)}")
            else:
                print("[Input] 错误：无法检测到当前系统的 Syscall ID")
                self.lib = None
        except Exception as e:
            print(f"[Input] 加载 Syscall 驱动异常: {e}")
            self.lib = None

        user32 = ctypes.windll.user32
        self.screen_width = user32.GetSystemMetrics(0)
        self.screen_height = user32.GetSystemMetrics(1)

    def _detect_ssn(self) -> int:
        """动态追踪 user32.dll 以获取 NtUserSendInput 的系统调用号"""
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
            kernel32.GetModuleHandleW.restype = ctypes.c_void_p
            kernel32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            kernel32.GetProcAddress.restype = ctypes.c_void_p
            
            h_user32 = kernel32.GetModuleHandleW("user32.dll")
            if not h_user32:
                h_user32 = kernel32.LoadLibraryW("user32.dll")
            
            addr = kernel32.GetProcAddress(h_user32, b"SendInput")
            if not addr: return None
            
            # 读取指令寻找跳转
            buf = (ctypes.c_ubyte * 32)()
            ctypes.memmove(buf, addr, 32)
            
            target_addr = 0
            # 模式 1: ff 25 offset (jmp qword ptr [rip + offset])
            if buf[0] == 0xFF and buf[1] == 0x25:
                offset = struct.unpack("<i", bytes(buf[2:6]))[0]
                jmp_target_ptr = addr + 6 + offset
                target_addr = struct.unpack("<Q", ctypes.string_at(jmp_target_ptr, 8))[0]
            # 模式 2: 48 ff 25 offset (rex.w jmp qword ptr [rip + offset])
            elif buf[0] == 0x48 and buf[1] == 0xFF and buf[2] == 0x25:
                offset = struct.unpack("<i", bytes(buf[3:7]))[0]
                jmp_target_ptr = addr + 7 + offset
                target_addr = struct.unpack("<Q", ctypes.string_at(jmp_target_ptr, 8))[0]
            
            if not target_addr: return None
            
            # 读取跳转目标处的指令，寻找 mov eax, SSN (B8 XX XX XX XX)
            target_buf = (ctypes.c_ubyte * 16)()
            ctypes.memmove(target_buf, target_addr, 16)
            for i in range(len(target_buf) - 5):
                if target_buf[i] == 0xB8:
                    return struct.unpack("<I", bytes(target_buf[i+1:i+5]))[0]
            return None
        except:
            return None

    def _send_mouse_event(self, flags, x=0, y=0, data=0):
        if not self.lib:
            return

        # 绝对坐标处理
        if flags & 0x8000: # MOUSEEVENTF_ABSOLUTE
            x = int(x * 65535 / self.screen_width)
            y = int(y * 65535 / self.screen_height)

        try:
            # 强制转换为 int32 范围
            x = max(-2147483648, min(2147483647, int(x)))
            y = max(-2147483648, min(2147483647, int(y)))
            
            self.lib.send_input([{
                "type": 0, # INPUT_MOUSE
                "dx": x,
                "dy": y,
                "flags": flags,
                "data": data
            }])
        except Exception as e:
            print(f"[SyscallInput] 发送指令异常: {e}")

    def move_to(self, x: int, y: int):
        self._send_mouse_event(0x0001 | 0x8000, x, y)

    def move_rel(self, dx: int, dy: int):
        """相对移动"""
        if dx == 0 and dy == 0:
            return
        self._send_mouse_event(0x0001, dx, dy)

    def smooth_move_to(self, x: int, y: int, duration: float = 0.1, human_curve: bool = False):
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        
        dx = x - pt.x
        dy = y - pt.y
        self.smooth_move_rel(dx, dy, duration, human_curve)

    def smooth_move_rel(self, dx: int, dy: int, duration: float = 0.1, human_curve: bool = False):
        if dx == 0 and dy == 0:
            return
        if not self.lib:
            return

        target_freq = 60
        steps = max(int(duration * target_freq), 2)
        interval = duration / steps
        
        if interval < 0.016:
            interval = 0.016
        
        current_dx = 0.0
        current_dy = 0.0
        
        ctrl_x, ctrl_y = 0.0, 0.0
        if human_curve:
            dist = math.sqrt(dx**2 + dy**2)
            if dist > 10:
                offset_scale = dist * 0.1
                v_x, v_y = -dy / dist, dx / dist
                rand_offset = random.uniform(-offset_scale, offset_scale)
                ctrl_x, ctrl_y = v_x * rand_offset, v_y * rand_offset

        for i in range(1, steps + 1):
            t = i / steps
            
            if human_curve:
                target_dx = 2 * (1 - t) * t * (dx / 2 + ctrl_x) + t**2 * dx
                target_dy = 2 * (1 - t) * t * (dy / 2 + ctrl_y) + t**2 * dy
            else:
                multiplier = (1 - math.cos(t * math.pi)) / 2
                target_dx = dx * multiplier
                target_dy = dy * multiplier
                
            step_dx = target_dx - current_dx
            step_dy = target_dy - current_dy
            
            if i < steps:
                step_dx += random.uniform(-0.5, 0.5)
                step_dy += random.uniform(-0.5, 0.5)
            
            actual_move_x = int(step_dx)
            actual_move_y = int(step_dy)
            
            if actual_move_x != 0 or actual_move_y != 0:
                self.move_rel(actual_move_x, actual_move_y)
                current_dx += actual_move_x
                current_dy += actual_move_y
            
            time.sleep(interval)

        final_dx = int(dx - current_dx)
        final_dy = int(dy - current_dy)
        if final_dx != 0 or final_dy != 0:
            self.move_rel(final_dx, final_dy)

    def click(self, button: str = 'left'):
        if not self.lib: return
        down_flag = 0x0002 if button == 'left' else 0x0008
        up_flag = 0x0004 if button == 'left' else 0x0010
        self._send_mouse_event(down_flag)
        time.sleep(random.uniform(0.01, 0.03))
        self._send_mouse_event(up_flag)

    def key_down(self, key_code: int):
        if not self.lib: return
        self.lib.send_input([{"type": 1, "vk": key_code, "flags": 0}])

    def key_up(self, key_code: int):
        if not self.lib: return
        self.lib.send_input([{"type": 1, "vk": key_code, "flags": 2}])
