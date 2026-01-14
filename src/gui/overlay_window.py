import win32gui
import win32con
import win32api
from PySide6.QtWidgets import QWidget, QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QFont

class OverlayWindow(QWidget):
    """
    全屏透明覆盖窗口 (Overlay/ESP)
    用于在屏幕顶层绘制识别框，同时允许鼠标穿透操作。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        # 1. 设置窗口标志
        self.setWindowFlags(
            Qt.FramelessWindowHint |       # 无边框
            Qt.WindowStaysOnTopHint |      # 置顶
            Qt.Tool |                      # 工具窗口（不在任务栏显示）
            Qt.WindowTransparentForInput   # 鼠标穿透 (Qt 5.10+ 支持)
        )
        
        # 2. 设置背景透明
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating) # 显示时不抢焦点
        self.setAttribute(Qt.WA_TransparentForMouseEvents) # 确保 Qt 层面也忽略鼠标
        
        # 3. 设置全屏几何
        self.resize_to_screen()
        
        # 数据缓存
        self.boxes = [] # [(x1, y1, x2, y2, conf, cls), ...]
        self.target_box = None # 当前锁定的目标
        self.fov_radius = 0
        self.fov_center = (0, 0)
        self.fps = 0
        
        # 4. Windows API 强制穿透 (双重保险)
        self.set_click_through()

    def resize_to_screen(self):
        """调整大小以覆盖主屏幕 (避开任务栏/Available Geometry)"""
        screen = QApplication.primaryScreen()
        rect = screen.availableGeometry()
        self.setGeometry(rect)

    def set_click_through(self):
        """使用 Windows API 设置窗口为透传模式"""
        try:
            hwnd = self.winId()
            # 获取当前样式
            styles = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            # 添加 WS_EX_LAYERED (分层) 和 WS_EX_TRANSPARENT (透传)
            # 注意：WS_EX_TRANSPARENT 实际上意味着“点击时穿透我”，而不是“我是透明的”
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, styles | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT)
        except Exception as e:
            print(f"[Overlay] Set click through failed: {e}")

    def update_data(self, boxes, target_box, fov_center, fov_radius, fps=0):
        """更新绘制数据并刷新"""
        self.boxes = boxes
        self.target_box = target_box
        self.fov_center = fov_center
        self.fov_radius = fov_radius
        self.fps = fps
        self.update() # 触发 paintEvent

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 0. 绘制 FPS (左上角)
        if self.fps > 0:
            painter.setPen(QColor(0, 255, 0))
            painter.setFont(QFont("Arial", 12, QFont.Bold))
            painter.drawText(10, 30, f"FPS: {self.fps}")

        # 1. 绘制 FOV 圈 (白色虚线，半透明)
        if self.fov_radius > 0:
            pen_fov = QPen(QColor(255, 255, 255, 100)) 
            pen_fov.setWidth(1)
            pen_fov.setStyle(Qt.DashLine)
            painter.setPen(pen_fov)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(
                int(self.fov_center[0] - self.fov_radius), 
                int(self.fov_center[1] - self.fov_radius), 
                int(self.fov_radius * 2), 
                int(self.fov_radius * 2)
            )

        # 2. 绘制所有识别到的目标 (绿色)
        pen_box = QPen(QColor(0, 255, 0, 200)) # 绿色
        pen_box.setWidth(2)
        
        for box in self.boxes:
            x1, y1, x2, y2, conf, cls = box
            w = x2 - x1
            h = y2 - y1
            
            painter.setPen(pen_box)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(int(x1), int(y1), int(w), int(h))

        # 3. 绘制当前锁定的目标 (红色，加粗)
        if self.target_box:
            x1, y1, x2, y2, conf, cls = self.target_box
            w = x2 - x1
            h = y2 - y1
            
            pen_target = QPen(QColor(255, 0, 0, 255)) # 红色
            pen_target.setWidth(3)
            painter.setPen(pen_target)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(int(x1), int(y1), int(w), int(h))
            
            # 绘制 "LOCKED" 文字
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(int(x1), int(y1) - 5, "LOCKED")
