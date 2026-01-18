from abc import ABC, abstractmethod

class AbstractInput(ABC):
    """
    输入模拟抽象基类
    """
    
    @abstractmethod
    def move_to(self, x: int, y: int):
        """移动鼠标到绝对坐标"""
        pass

    @abstractmethod
    def smooth_move_to(self, x: int, y: int, duration: float = 0.1, human_curve: bool = False):
        """平滑地移动鼠标到绝对坐标 (拟人化)"""
        pass

    @abstractmethod
    def move_rel(self, dx: int, dy: int):
        """相对移动鼠标"""
        pass

    @abstractmethod
    def smooth_move_rel(self, dx: int, dy: int, duration: float = 0.1, human_curve: bool = False):
        """平滑地相对移动鼠标 (拟人化)"""
        pass

    @abstractmethod
    def click(self, button: str = 'left'):
        """点击鼠标"""
        pass

    @abstractmethod
    def key_down(self, key_code: int):
        """按下按键"""
        pass

    @abstractmethod
    def key_up(self, key_code: int):
        """抬起按键"""
        pass

    def cleanup(self):
        """资源清理 (可选)"""
        pass
