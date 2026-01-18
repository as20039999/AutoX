
import sys
import os
import time
import threading
import ctypes

# 添加 src 到路径以便导入
sys.path.append(os.path.join(os.getcwd(), 'src'))

try:
    from input.dd_input import DDInput
except ImportError:
    print("无法导入 DDInput，请检查路径")
    sys.exit(1)

def input_worker(dd_input):
    print(f"[Worker] Thread started: {threading.current_thread().name}")
    print(f"[Worker] Initializing driver...")
    
    try:
        dd_input.init_driver()
        print(f"[Worker] Driver initialized.")
    except Exception as e:
        print(f"[Worker] Init failed: {e}")
        return

    print(f"[Worker] Trying small movement...")
    for i in range(5):
        print(f"[Worker] Move {i+1}/5")
        # 往复移动，避免鼠标跑飞
        dx = 10 if i % 2 == 0 else -10
        t0 = time.perf_counter()
        dd_input.move_rel(dx, 0)
        dt = (time.perf_counter() - t0) * 1000
        print(f"[Worker] Move took {dt:.2f}ms")
        time.sleep(0.5)
    
    print(f"[Worker] Done.")

def main():
    print(f"[Main] Creating DDInput instance (lazy init)...")
    dd = DDInput()
    
    print(f"[Main] Starting worker thread...")
    t = threading.Thread(target=input_worker, args=(dd,))
    t.start()
    
    print(f"[Main] Main loop heartbeat...")
    for i in range(5):
        print(f"[Main] Heartbeat {i+1}/5")
        time.sleep(0.8)
        if not t.is_alive():
            break
            
    t.join(timeout=2.0)
    if t.is_alive():
        print(f"[Main] Worker thread stuck!")
    else:
        print(f"[Main] All threads finished cleanly.")

if __name__ == "__main__":
    main()
