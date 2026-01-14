import cv2
import sys
import os
import torch

# 将 src 目录添加到路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from inference import YOLOInference

def test_inference():
    print("--- 开始 Inference 模块验证 ---")
    
    model_path = "base.pt"
    if not os.path.exists(model_path):
        print(f"警告: 找不到模型文件 {model_path}，将自动下载 (首次运行可能较慢)...")
    
    # 实例化推理引擎
    # 默认设备会根据 cuda 是否可用自动选择
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f"1. 初始化模型 (Device: {device})...")
    infer = YOLOInference(model_path=model_path, device=device)
    
    # 找一个测试图像
    test_img_path = "debug_dda_capture.png"
    if not os.path.exists(test_img_path):
        # 如果没有采集的图，创建一个全黑图模拟
        import numpy as np
        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        print("   使用空白图像进行冒烟测试...")
    else:
        frame = cv2.imread(test_img_path)
        print(f"   加载图像: {test_img_path}")
    
    # 执行预测
    print("2. 执行预测...")
    results = infer.predict(frame)
    
    print(f"   检测到目标数量: {len(results)}")
    for i, (x1, y1, x2, y2, conf, cls) in enumerate(results):
        print(f"   目标 {i}: 类别={cls}, 置信度={conf:.2f}, 坐标=({x1}, {y1}, {x2}, {y2})")
        
    print("--- Inference 模块验证完成 ---")

if __name__ == "__main__":
    test_inference()
