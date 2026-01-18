import ctypes
import time
import math

class MouseMonitor:
    """
    鼠标运动监控器 (Leaky Bucket 算法)
    用于区分“程序自动移动”和“用户手动移动”。
    
    原理:
    维护一个“位移余额” (Balance)。
    - 当程序发出移动指令 (dx, dy) 时，余额减去 (dx, dy)。
    - 当检测到鼠标实际移动 (real_dx, real_dy) 时，余额加上 (real_dx, real_dy)。
    - 理想情况下，程序移动会被抵消，余额接近 0。
    - 如果用户移动鼠标，余额会显著偏离 0。
    - 余额会随时间衰减 (Leaky)，确保误差不累积，并实现“用户停止后自动恢复”的逻辑。
    """
    
    def __init__(self, threshold=30, decay=0.7, timeout=0.05):
        self.base_threshold = threshold  # 基础阈值
        self.decay = decay          # 余额衰减系数
        self.timeout = timeout      # 冷却时间
        
        self.x_balance = 0.0
        self.y_balance = 0.0
        self.last_cmd_magnitude = 0.0 # 上一次指令的幅度
        
        self.last_pos = self._get_cursor_pos()
        self.last_user_move_time = 0
        
        # 调试统计
        self.max_balance = 0
        
    def _get_cursor_pos(self):
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return (pt.x, pt.y)
        
    def report_command(self, dx, dy):
        """
        报告程序发出的移动指令
        """
        self.x_balance -= dx
        self.y_balance -= dy
        # 记录指令幅度，用于动态阈值 (应对延迟导致的虚高余额)
        self.last_cmd_magnitude = math.hypot(dx, dy)
        
    def update(self):
        """
        更新当前状态 (需每帧调用)
        """
        curr_pos = self._get_cursor_pos()
        
        real_dx = curr_pos[0] - self.last_pos[0]
        real_dy = curr_pos[1] - self.last_pos[1]
        
        self.last_pos = curr_pos
        
        # 更新余额
        self.x_balance += real_dx
        self.y_balance += real_dy
        
        # 衰减余额
        self.x_balance *= self.decay
        self.y_balance *= self.decay
        self.last_cmd_magnitude *= self.decay # 指令影响也衰减
        
        # 计算总偏差能量
        energy = math.hypot(self.x_balance, self.y_balance)
        if energy > self.max_balance:
            self.max_balance = energy
            
        # 动态阈值: 基础阈值 + 指令幅度的 1.5 倍
        # (假设延迟可能导致 1-2 帧的指令未被抵消)
        current_threshold = self.base_threshold + self.last_cmd_magnitude * 1.5
            
        # 判定是否为用户移动
        if energy > current_threshold:
            self.last_user_move_time = time.time()
            # print(f"[Monitor] User Active! E={energy:.1f}, Th={current_threshold:.1f}")
            return True # Active
            
        return False # Inactive
        
    def is_user_active(self):
        """
        检查用户是否处于活跃状态 (或冷却期内)
        """
        energy = math.hypot(self.x_balance, self.y_balance)
        current_threshold = self.base_threshold + self.last_cmd_magnitude * 1.5
        
        if energy > current_threshold:
            self.last_user_move_time = time.time()
            return True
            
        if time.time() - self.last_user_move_time < self.timeout:
            return True
            
        return False
        
    def reset(self):
        self.x_balance = 0
        self.y_balance = 0
        self.last_pos = self._get_cursor_pos()
