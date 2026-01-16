import os
import sys
import torch
from ultralytics import YOLO

# 将项目根目录添加到 python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def export_model(model_path, imgsz=640):
    """
    将 YOLO .pt 模型导出为 TensorRT .engine 格式
    """
    if not os.path.exists(model_path):
        print(f"错误: 找不到模型文件 {model_path}")
        return

    print(f"正在加载模型: {model_path}")
    model = YOLO(model_path)

    print(f"正在导出为 TensorRT 格式 (imgsz={imgsz}, half=True)...")
    print("注意: 首次导出可能需要几分钟时间，请耐心等待。")
    
    try:
        # 导出参数说明:
        # format='engine': 导出为 TensorRT
        # imgsz: 推理尺寸，建议与 FOV 匹配或设为 640
        # half: 开启 FP16 半精度，速度快且精度损失极小
        # simplify: 简化 ONNX 模型
        # workspace: GPU 显存占用上限 (GB)
        path = model.export(
            format='engine', 
            imgsz=imgsz, 
            half=True, 
            simplify=True,
            workspace=4 
        )
        print(f"\n导出成功! TensorRT 模型已保存至: {path}")
        print("\n现在重新启动主程序，它将自动检测并加载该 .engine 文件。")
    except Exception as e:
        print(f"\n导出失败: {e}")
        print("\n请检查是否已正确安装 tensorrt 库: pip install tensorrt")

if __name__ == "__main__":
    # 默认导出项目根目录下的 base.pt
    root_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_model = os.path.join(root_path, "base.pt")
    
    target_model = sys.argv[1] if len(sys.argv) > 1 else default_model
    target_imgsz = int(sys.argv[2]) if len(sys.argv) > 2 else 640
    
    export_model(target_model, target_imgsz)
