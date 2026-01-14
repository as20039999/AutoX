import cv2
import sys
import os
import time

# 将 src 目录添加到路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from capture import create_capture

def test_capture():
    print("--- 开始 Capture 模块验证 ---")
    
    # 测试 DDA (默认)
    print("1. 测试 DDA 采集...")
    cap = create_capture(method="dda")
    cap.start()
    
    # 给一点时间初始化
    time.sleep(1)
    
    frame = cap.get_frame()
    if frame is not None:
        cv2.imwrite("debug_dda_capture.png", frame)
        print(f"   DDA 采集成功，已保存至 debug_dda_capture.png (尺寸: {frame.shape[1]}x{frame.shape[0]})")
    else:
        print("   错误: DDA 采集失败")
    
    cap.stop()
    
    # 测试 MSS
    print("2. 测试 MSS 采集...")
    cap_mss = create_capture(method="mss")
    cap_mss.start()
    
    frame = cap_mss.get_frame()
    if frame is not None:
        cv2.imwrite("debug_mss_capture.png", frame)
        print(f"   MSS 采集成功，已保存至 debug_mss_capture.png (尺寸: {frame.shape[1]}x{frame.shape[0]})")
    else:
        print("   错误: MSS 采集失败")
        
    cap_mss.stop()
    
    print("--- Capture 模块验证完成 ---")

if __name__ == "__main__":
    test_capture()
