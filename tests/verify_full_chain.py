import cv2
import time
import sys
import os
import torch

# 将 src 目录添加到路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from capture import create_capture
from inference import YOLOInference
from input import create_input

def main():
    print("--- 开始全流程集成验证 (Capture -> Inference -> Input) ---")
    
    # 1. 初始化输入模块
    mouse = create_input(method="win32")
    
    # 2. 初始化图像采集 (DDA)
    cap = create_capture(method="dda")
    cap.start()
    
    # 3. 初始化推理引擎
    model_path = "base.pt" 
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    infer = YOLOInference(model_path=model_path, device=device, conf_thres=0.4)

    # 4. 创建显示窗口
    window_name = "AutoX_Vision_Monitor"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1280, 720)

    print("\n验证提示：")
    print("1. 屏幕上出现的物体将被识别。")
    print("2. [自瞄测试]：鼠标将自动移动到检测到的第一个目标的中心。")
    print("3. 按 'q' 键退出。")
    
    try:
        while True:
            # A. 采集
            frame = cap.get_frame()
            if frame is None:
                continue

            # B. 推理
            results = infer.predict(frame)

            # C. 输入 (动作)
            if len(results) > 0:
                # 获取第一个目标的中心
                x1, y1, x2, y2, conf, cls = results[0]
                target_x = int((x1 + x2) / 2)
                target_y = int((y1 + y2) / 2)
                
                # 执行移动
                mouse.move_to(target_x, target_y)
                
                # 在画面上标记锁定目标
                cv2.circle(frame, (target_x, target_y), 5, (0, 0, 255), -1)
                cv2.putText(frame, "LOCKED", (target_x + 10, target_y), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            # 绘制所有检测结果
            for (x1, y1, x2, y2, conf, cls) in results:
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                label = f"ID:{int(cls)} {conf:.2f}"
                cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            # 显示窗口
            cv2.imshow(window_name, frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
                
    finally:
        cap.stop()
        cv2.destroyAllWindows()
        print("--- 集成验证结束 ---")

if __name__ == "__main__":
    main()
