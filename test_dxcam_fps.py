
import dxcam
import time

try:
    camera = dxcam.create(output_color="BGR")
    camera.start(target_fps=0, video_mode=True)
    print("DXCAM started, waiting 2 seconds...")
    time.sleep(2)
    camera.stop()
    print("DXCAM stopped")
except Exception as e:
    print(f"Error: {e}")
