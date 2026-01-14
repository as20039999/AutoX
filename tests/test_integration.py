import cv2
import time
import sys
import os

# 将 src 目录添加到路径，确保可以导入模块
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from capture import create_capture
from inference import YOLOInference

def main():
    # 1. 初始化图像采集 (默认使用高性能 DDA)
    print("正在初始化采集模块...")
    cap = create_capture(method="dda")
    cap.start()

    # 2. 初始化推理引擎
    print("正在初始化推理引擎...")
    model_path = "yolov8n.pt" 
    infer = YOLOInference(model_path=model_path, conf_thres=0.3)

    # 3. 创建固定的显示窗口，防止重复创建
    window_name = "AutoX_Debug_View"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 800, 600)

    print("\n--- 验证开始 ---")
    print("操作提示：")
    print("1. 屏幕上出现的物体将被识别并框选。")
    print("2. [注意]：由于采集的是屏幕，显示窗口内会出现'画中画'现象，这是正常的。")
    print("3. 按下键盘上的 'q' 键退出验证。")
    
    prev_time = time.time()
    
    try:
        while True:
            # 获取一帧图像
            frame = cap.get_frame()
            if frame is None:
                continue

            # 执行 AI 推理
            results = infer.predict(frame)

            # 在图像上绘制结果
            for (x1, y1, x2, y2, conf, cls) in results:
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                label = f"ID:{cls} {conf:.2f}"
                cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            # 计算 FPS
            curr_time = time.time()
            fps = 1 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0
            prev_time = curr_time
            cv2.putText(frame, f"FPS: {int(fps)}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

            # 显示到固定窗口
            cv2.imshow(window_name, frame)

            # 检测退出键
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    finally:
        # 释放资源
        cap.stop()
        cv2.destroyAllWindows()
        print("--- 验证结束 ---")

if __name__ == "__main__":
    main()
