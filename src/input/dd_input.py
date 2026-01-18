
import ctypes
import time
import math
import random
import os
import multiprocessing
import atexit
import threading
from .base import AbstractInput
from utils.paths import get_asset_path

class DDInput(AbstractInput):
    """
    基于 ddxoft (DD 虚拟键盘鼠标) 的驱动级输入实现
    [重构版] 使用独立子进程运行驱动，彻底隔离 CUDA 与驱动的冲突
    """
    
    def __init__(self, enabled=True):
        # 启用 DD 驱动
        self.enabled = enabled 
        self.is_stopping = False
        self.process = None
        self.cmd_queue = None
        self.status_queue = None

        if self.enabled:
            # 加载 DLL
            dll_path = get_asset_path("ddxoft/ddhid60400.dll")
            if not os.path.exists(dll_path):
                raise FileNotFoundError(f"[Input] 未找到 DD 驱动 DLL: {dll_path}")
            
            # 初始化多进程通信
            self.cmd_queue = multiprocessing.Queue()
            self.status_queue = multiprocessing.Queue()
            
            # 导入子进程函数
            from .dd_process import dd_worker_process
            
            # 启动子进程
            print(f"[Input] Starting DD driver process...")
            self.process = multiprocessing.Process(
                target=dd_worker_process, 
                args=(self.cmd_queue, self.status_queue, dll_path),
                daemon=True # 守护进程，主进程死则死
            )
            self.process.start()
            
            # 等待初始化结果
            try:
                status, msg = self.status_queue.get(timeout=5.0)
                if status == "ready":
                    if msg:
                        print("[Input] DD 驱动子进程初始化成功")
                    else:
                        print("[Input] DD 驱动子进程报告异常，但继续运行")
                else:
                    print(f"[Input] DD 驱动子进程初始化失败: {msg}")
                    self.enabled = False
            except Exception as e:
                print(f"[Input] 等待 DD 子进程超时: {e}")
                self.enabled = False

            # 注册退出清理
            atexit.register(self.stop)
                
        else:
            print("[Input] DD 驱动已禁用 (隔离模式)")

        # 获取屏幕分辨率
        user32 = ctypes.windll.user32
        self.screen_width = user32.GetSystemMetrics(0)
        self.screen_height = user32.GetSystemMetrics(1)
        
        # DD 键码映射表 (Windows VK -> DD Code)
        self.VK_MAP = {
            # Function Keys
            0x1B: 100,    # ESC
            0x70: 101, 0x71: 102, 0x72: 103, 0x73: 104, # F1-F4
            0x74: 105, 0x75: 106, 0x76: 107, 0x77: 108, # F5-F8
            0x78: 109, 0x79: 110, 0x7A: 111, 0x7B: 112, # F9-F12
            
            # Numbers Row
            0xC0: 200,    # ~
            0x31: 201, 0x32: 202, 0x33: 203, 0x34: 204, 0x35: 205,
            0x36: 206, 0x37: 207, 0x38: 208, 0x39: 209, 0x30: 210,
            0xBD: 211,    # -
            0xBB: 212,    # =
            0xDC: 213,    # \
            0x08: 214,    # Backspace
            
            # Row 2 (Q-P)
            0x09: 300,    # Tab
            0x51: 301,    # Q
            0x57: 302,    # W
            0x45: 303,    # E
            0x52: 304,    # R
            0x54: 305,    # T
            0x59: 306,    # Y
            0x55: 307,    # U
            0x49: 308,    # I
            0x4F: 309,    # O
            0x50: 310,    # P
            0xDB: 311,    # [
            0xDD: 312,    # ]
            0x0D: 313,    # Enter
            
            # Row 3 (A-L)
            0x14: 400,    # Caps Lock
            0x41: 401,    # A
            0x53: 402,    # S
            0x44: 403,    # D
            0x46: 404,    # F
            0x47: 405,    # G
            0x48: 406,    # H
            0x4A: 407,    # J
            0x4B: 408,    # K
            0x4C: 409,    # L
            0xBA: 410,    # ;
            0xDE: 411,    # '
            
            # Row 4 (Z-M)
            0xA0: 500,    # L-Shift
            0x10: 500,    # Shift (Map to L-Shift)
            0x5A: 501,    # Z
            0x58: 502,    # X
            0x43: 503,    # C
            0x56: 504,    # V
            0x42: 505,    # B
            0x4E: 506,    # N
            0x4D: 507,    # M
            0xBC: 508,    # ,
            0xBE: 509,    # .
            0xBF: 510,    # /
            0xA1: 511,    # R-Shift
            
            # Bottom Row
            0xA2: 600,    # L-Ctrl
            0x11: 600,    # Ctrl (Map to L-Ctrl)
            0x5B: 601,    # L-Win
            0xA4: 602,    # L-Alt
            0x12: 602,    # Alt (Map to L-Alt)
            0x20: 603,    # Space
            0xA5: 604,    # R-Alt
            0x5C: 605,    # R-Win
            0x5D: 606,    # Apps/Menu
            0xA3: 607,    # R-Ctrl
            
            # Navigation & Others
            0x2C: 700,    # Print Screen
            0x91: 701,    # Scroll Lock
            0x13: 702,    # Pause
            0x2D: 703,    # Insert
            0x24: 704,    # Home
            0x21: 705,    # Page Up
            0x2E: 706,    # Delete
            0x23: 707,    # End
            0x22: 708,    # Page Down
            0x26: 709,    # Up
            0x25: 710,    # Left
            0x28: 711,    # Down
            0x27: 712,    # Right
            
            # Numpad (Based on common DD mapping)
            0x60: 800, 0x61: 801, 0x62: 802, 0x63: 803, 0x64: 804,
            0x65: 805, 0x66: 806, 0x67: 807, 0x68: 808, 0x69: 809,
            0x6A: 810, # *
            0x6B: 811, # +
            0x6D: 812, # -
            0x6E: 813, # .
            0x6F: 814, # /
            0x90: 815, # NumLock
        }

    def stop(self):
        """停止子进程"""
        self.is_stopping = True
        if self.process:
            if self.process.is_alive():
                print("[Input] 正在停止 DD 驱动子进程...")
                try:
                    # 1. 立即标记队列不再阻塞 join
                    if self.cmd_queue:
                        self.cmd_queue.cancel_join_thread()
                    if self.status_queue:
                        self.status_queue.cancel_join_thread()

                    # 2. 尝试发送退出信号 (带极短超时，防止队列满导致挂起)
                    if self.cmd_queue:
                        try:
                            self.cmd_queue.put(None, block=True, timeout=0.1)
                        except Exception:
                            pass # 队列满或其它错误，直接跳过，准备强制终止
                    
                    # 3. 等待进程退出
                    self.process.join(timeout=1.0)
                    
                    # 4. 如果超时未退出，强制终止
                    if self.process.is_alive():
                        print("[Input] DD 子进程未响应，正在强制终止...")
                        self.process.terminate()
                        # 给一点时间让 OS 回收资源
                        self.process.join(timeout=0.5)
                        if self.process.is_alive():
                            # 如果 terminate 还不死（极少见），使用 kill
                            try: self.process.kill()
                            except: pass
                    else:
                        print("[Input] DD 子进程已正常退出")
                        
                except Exception as e:
                    print(f"[Input] 停止 DD 子进程出错: {e}")
            else:
                # 进程虽然已退出 (is_alive=False)，但必须 join 才能回收僵尸进程
                print("[Input] 正在清理已崩溃/退出的 DD 子进程资源...")
                try:
                    if self.cmd_queue: self.cmd_queue.cancel_join_thread()
                    if self.status_queue: self.status_queue.cancel_join_thread()
                    self.process.join(timeout=0.5)
                except Exception as e:
                    print(f"[Input] 清理僵尸进程失败: {e}")
            
        # 5. 清理队列资源
        try:
            if self.cmd_queue:
                self.cmd_queue.close()
        except Exception:
            pass
            
        try:
            if self.status_queue:
                self.status_queue.close()
        except Exception:
            pass
            
        self.process = None
        self.cmd_queue = None
        self.status_queue = None

    def init_driver(self):
        """
        初始化驱动：重置停止状态并确保子进程正在运行
        """
        self.is_stopping = False
        # 清除所有单次日志标记，允许在新会话中重新打印
        for attr in ['_logged_disabled', '_logged_process_dead', '_logged_queue_full']:
            if hasattr(self, attr):
                delattr(self, attr)

        if self.enabled and (self.process is None or not self.process.is_alive()):
            print("[DDInput] 检测到子进程未运行，正在初始化/重启...")
            self._restart_process()

    def move_to(self, x: int, y: int):
        """绝对移动"""
        if self.enabled and self.cmd_queue:
            # 模仿 Win32 逻辑：强制转 int 并防止溢出
            try:
                x = max(-2147483648, min(2147483647, int(x)))
                y = max(-2147483648, min(2147483647, int(y)))
                self.cmd_queue.put(('move_to', x, y))
            except Exception as e:
                print(f"[DDInput] move_to 参数错误: {e}")

    def move_rel(self, dx: int, dy: int):
        """相对移动"""
        if not self.enabled:
            if not hasattr(self, '_logged_disabled'):
                print("[DDInput] 警告: DD 驱动未启用或初始化失败，无法执行移动")
                self._logged_disabled = True
            return

        # 检查子进程状态，如果挂了尝试重启 (且未在停止过程中)
        if not self.is_stopping and (self.process is None or not self.process.is_alive()):
             print("[DDInput] 检测到 DD 子进程已退出，正在尝试重启...")
             self._restart_process()

        if self.process and self.process.is_alive() and self.cmd_queue:
            try:
                # 模仿 Win32 逻辑：强制转 int 并防止溢出
                dx = max(-2147483648, min(2147483647, int(dx)))
                dy = max(-2147483648, min(2147483647, int(dy)))
                
                # 过滤无效移动，减轻驱动负担
                if dx == 0 and dy == 0:
                    return
                
                # 使用非阻塞 put，防止队列满时阻塞主线程
                # 移动指令可以丢弃，因为下一帧会产生新的修正指令
                self.cmd_queue.put_nowait(('move_rel', dx, dy))
            except queue.Full:
                # 队列满，静默丢弃 (或仅打印一次警告)
                if not hasattr(self, '_logged_queue_full'):
                    print("[DDInput] 警告: 指令队列已满，正在丢弃移动帧 (系统负载过高)")
                    self._logged_queue_full = True
            except Exception as e:
                print(f"[DDInput] move_rel 异常: {e}")
        else:
            if not hasattr(self, '_logged_process_dead'):
                print("[DDInput] 错误: DD 子进程未运行，无法发送指令")
                self._logged_process_dead = True

    def _restart_process(self):
        """重启子进程"""
        try:
            # 清理旧进程
            self.stop()
            # 必须重置停止标志，否则后续无法发送指令
            self.is_stopping = False
            
            # 重新初始化
            dll_path = get_asset_path("ddxoft/ddhid60400.dll")
            if not os.path.exists(dll_path):
                 print(f"[DDInput] 重启失败: DLL 未找到")
                 return

            self.cmd_queue = multiprocessing.Queue()
            self.status_queue = multiprocessing.Queue()
            
            from .dd_process import dd_worker_process
            print(f"[Input] Restarting DD driver process...")
            self.process = multiprocessing.Process(
                target=dd_worker_process, 
                args=(self.cmd_queue, self.status_queue, dll_path),
                daemon=True
            )
            self.process.start()
            
            # 简单等待，不阻塞太久
            time.sleep(0.5)
            if self.process.is_alive():
                 print("[DDInput] 子进程重启成功")
                 if hasattr(self, '_logged_process_dead'):
                     del self._logged_process_dead
            else:
                 print("[DDInput] 子进程重启失败")
                 
        except Exception as e:
            print(f"[DDInput] 重启过程异常: {e}")

    def smooth_move_to(self, x: int, y: int, duration: float = 0.1, human_curve: bool = False):
        """平滑绝对移动 (基于相对移动实现)"""
        # 获取当前位置 (使用 Windows API)
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        
        dx = x - pt.x
        dy = y - pt.y
        self.smooth_move_rel(dx, dy, duration, human_curve)

    def smooth_move_rel(self, dx: int, dy: int, duration: float = 0.1, human_curve: bool = False):
        """
        平滑地相对移动鼠标 (拟人化)
        """
        if dx == 0 and dy == 0:
            return

        # 步数计算 (限制频率为 60Hz，避免 DD 驱动过载导致系统卡顿)
        target_freq = 60
        steps = max(int(duration * target_freq), 2)
        interval = duration / steps
        
        # 强制最小间隔，防止过高频调用
        if interval < 0.016:
            interval = 0.016
        
        current_dx = 0
        current_dy = 0
        
        # 贝塞尔曲线控制点 (拟人化)
        ctrl_x, ctrl_y = 0, 0
        if human_curve:
            dist = math.sqrt(dx**2 + dy**2)
            if dist > 10:
                offset_scale = dist * 0.1
                # 垂直向量
                v_x, v_y = -dy / dist, dx / dist
                rand_offset = random.uniform(-offset_scale, offset_scale)
                ctrl_x, ctrl_y = v_x * rand_offset, v_y * rand_offset

        for i in range(1, steps + 1):
            t = i / steps
            
            if human_curve:
                # 二阶贝塞尔曲线
                target_dx = 2 * (1 - t) * t * (dx / 2 + ctrl_x) + t**2 * dx
                target_dy = 2 * (1 - t) * t * (dy / 2 + ctrl_y) + t**2 * dy
            else:
                # 余弦平滑 (S型曲线)
                multiplier = (1 - math.cos(t * math.pi)) / 2
                target_dx = dx * multiplier
                target_dy = dy * multiplier
                
            step_dx = target_dx - current_dx
            step_dy = target_dy - current_dy
            
            # 加入微小随机抖动
            if i < steps:
                step_dx += random.uniform(-0.5, 0.5)
                step_dy += random.uniform(-0.5, 0.5)
            
            self.move_rel(int(step_dx), int(step_dy))
            
            current_dx += int(step_dx)
            current_dy += int(step_dy)
            time.sleep(interval)

        # 补偿最后一步的取整误差
        final_dx = dx - int(current_dx)
        final_dy = dy - int(current_dy)
        if final_dx != 0 or final_dy != 0:
            self.move_rel(final_dx, final_dy)

    def click(self, button: str = 'left'):
        """
        1 =左键按下 ，2 =左键放开
        4 =右键按下 ，8 =右键放开
        """
        if not (self.enabled and self.cmd_queue):
            return

        btn_map = {
            'left': 1,
            'right': 4,
            'middle': 16
        }
        btn_code = btn_map.get(button.lower(), 1)
        try:
            # 点击操作比移动重要，给予极短的超时时间 (2ms)
            # 如果 2ms 还没塞进去，说明队列真的堵死了，只能丢弃以保命
            self.cmd_queue.put(('click', btn_code), timeout=0.002)
        except queue.Full:
            print(f"[DDInput] 警告: 指令队列拥堵，丢弃点击操作 ({button})")
        except Exception as e:
            print(f"[DDInput] click 异常: {e}")

    def key_down(self, key_code: int):
        """按下按键 (将 VK 码转换为 DD 码)"""
        if not (self.enabled and self.cmd_queue):
            return

        dd_code = self.VK_MAP.get(key_code)
        if dd_code:
            self.cmd_queue.put(('key_down', int(dd_code)))
        else:
            print(f"[Input] DD 未映射的按键代码: {hex(key_code)}")

    def key_up(self, key_code: int):
        """抬起按键 (将 VK 码转换为 DD 码)"""
        if not (self.enabled and self.cmd_queue):
            return

        dd_code = self.VK_MAP.get(key_code)
        if dd_code:
            self.cmd_queue.put(('key_up', int(dd_code)))
        else:
            print(f"[Input] DD 未映射的按键代码: {hex(key_code)}")

    def press_key(self, key_name: str):
        """
        通过名称按下按键 (DD 直接支持字符串输入)
        注意：DD_str 仅支持可见字符
        """
        if not (self.enabled and self.cmd_queue):
            return

        if len(key_name) == 1:
            self.cmd_queue.put(('str', key_name))
        else:
            print(f"[Input] DD 暂不支持功能键名称: {key_name}")

    def cleanup(self):
        """释放 DD 驱动资源"""
        self.stop()
