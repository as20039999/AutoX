import numpy as np

class KalmanFilter:
    """
    一个简单的二维卡尔曼滤波器，用于预测目标位置。
    """
    def __init__(self):
        # 状态向量 [x, y, vx, vy]
        self.dt = 1.0  # 时间步长
        
        # 状态转移矩阵 A
        self.A = np.array([
            [1, 0, self.dt, 0],
            [0, 1, 0, self.dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ])
        
        # 观测矩阵 H
        self.H = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0]
        ])
        
        # 过程噪声协方差 Q (降低过程噪声，相信状态转移模型)
        self.Q = np.eye(4) * 0.05
        
        # 观测噪声协方差 R (增加观测噪声，减少对单帧跳动观测值的依赖)
        self.R = np.eye(2) * 5.0
        
        # 误差协方差矩阵 P
        self.P = np.eye(4)
        
        # 初始状态
        self.x = None

    def update(self, z):
        """
        更新观测值 z = [x, y]
        """
        if self.x is None:
            self.x = np.array([z[0], z[1], 0, 0])
            return z

        # 预测
        self.x = self.A @ self.x
        self.P = self.A @ self.P @ self.A.T + self.Q

        # 更新
        y = z - self.H @ self.x  # 测量残差
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)  # 卡尔曼增益
        self.x = self.x + K @ y
        self.P = (np.eye(4) - K @ self.H) @ self.P

        return self.x[:2]

    def predict(self, steps=1):
        """
        预测未来几步的位置
        """
        if self.x is None:
            return None
        
        x_pred = self.x
        for _ in range(steps):
            x_pred = self.A @ x_pred
        return x_pred[:2]

    def reset(self):
        self.x = None
