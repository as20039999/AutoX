
import multiprocessing
import time
import ctypes
import os
import sys
import random

# 必须显式添加 src 路径，否则子进程找不到模块
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(os.path.dirname(current_dir))
if src_dir not in sys.path:
    sys.path.append(src_dir)

def dd_worker_process(cmd_queue, status_queue, dll_path):
    """
    DD 驱动专用子进程
    cmd_queue: 接收 (command, args...)
    status_queue: 发送状态回执
    """
    print(f"[DD-Process] 子进程启动 (PID: {os.getpid()})")
    
    dd_dll = None
    try:
        if not os.path.exists(dll_path):
            status_queue.put(("error", f"DLL not found: {dll_path}"))
            return

        print(f"[DD-Process] Loading DLL: {dll_path}")
        dd_dll = ctypes.windll.LoadLibrary(dll_path)
        
        # 初始化函数签名
        dd_dll.DD_btn.argtypes = [ctypes.c_int]
        dd_dll.DD_btn.restype = ctypes.c_int
        dd_dll.DD_movR.argtypes = [ctypes.c_int, ctypes.c_int]
        dd_dll.DD_movR.restype = ctypes.c_int
        dd_dll.DD_mov.argtypes = [ctypes.c_int, ctypes.c_int]
        dd_dll.DD_mov.restype = ctypes.c_int
        dd_dll.DD_key.argtypes = [ctypes.c_int, ctypes.c_int]
        dd_dll.DD_key.restype = ctypes.c_int
        dd_dll.DD_str.argtypes = [ctypes.c_char_p]
        dd_dll.DD_str.restype = ctypes.c_int

        # 初始化驱动
        print("[DD-Process] Calling DD_btn(0)...")
        st = dd_dll.DD_btn(0)
        if st == 1:
            print("[DD-Process] DD 驱动初始化成功")
            status_queue.put(("ready", True))
        else:
            print(f"[DD-Process] DD 驱动初始化异常: {st}")
            status_queue.put(("ready", False)) # 即使异常也尝试继续，避免死循环

    except Exception as e:
        print(f"[DD-Process] 初始化失败: {e}")
        status_queue.put(("error", str(e)))
        return

    import heapq
    import queue

    # 待处理的延迟事件堆 (release_time, type, args...)
    pending_events = []

    # 命令循环
    last_action_time = 0.0
    # 严格遵守驱动要求：最小间隔 10ms (100Hz)
    min_action_interval = 0.010
    
    # 指令合并缓存
    pending_cmd = None

    while True:
        try:
            now = time.time()
            
            # 1. 计算当前距离“可以执行下一次操作”的时间
            time_since_last = now - last_action_time
            time_to_wait_for_interval = max(0.0, min_action_interval - time_since_last)

            # 2. 处理已到期的延迟事件
            if pending_events and pending_events[0][0] <= now:
                if time_to_wait_for_interval > 0:
                    time.sleep(time_to_wait_for_interval)
                    now = time.time()
                
                event = heapq.heappop(pending_events)
                _, event_type, *args = event
                if event_type == "key":
                    dd_dll.DD_key(*args)
                elif event_type == "btn":
                    dd_dll.DD_btn(*args)
                
                last_action_time = time.time()
                continue

            # 3. 获取新命令
            if pending_cmd is not None:
                cmd_data = pending_cmd
                pending_cmd = None
            else:
                wait_timeout = 0.01 
                if time_to_wait_for_interval > 0:
                    wait_timeout = min(wait_timeout, time_to_wait_for_interval)
                if pending_events:
                    event_wait = max(0.0, pending_events[0][0] - now)
                    wait_timeout = min(wait_timeout, event_wait)
                
                wait_timeout = max(0.001, wait_timeout)

                try:
                    cmd_data = cmd_queue.get(timeout=wait_timeout)
                except queue.Empty:
                    continue

            # 4. 指令合并逻辑 (针对 move_rel)
            # 如果当前指令是位移，则尝试合并队列中后续的所有连续位移指令
            if cmd_data[0] == "move_rel":
                merged_dx, merged_dy = cmd_data[1], cmd_data[2]
                try:
                    while True:
                        next_cmd = cmd_queue.get_nowait()
                        if next_cmd[0] == "move_rel":
                            merged_dx += next_cmd[1]
                            merged_dy += next_cmd[2]
                        else:
                            # 遇到了非位移指令，存起来下一轮处理
                            pending_cmd = next_cmd
                            break
                except queue.Empty:
                    pass
                cmd_data = ("move_rel", merged_dx, merged_dy)

            # 5. 准备执行命令，先检查并等待 10ms 间隔
            now = time.time()
            time_to_wait_for_interval = max(0.0, min_action_interval - (now - last_action_time))
            if time_to_wait_for_interval > 0:
                time.sleep(time_to_wait_for_interval)
            
            # 6. 执行命令
            cmd_type = cmd_data[0] if cmd_data is not None else "quit"
            
            if cmd_type == "move_rel":
                dd_dll.DD_movR(cmd_data[1], cmd_data[2])
            elif cmd_type == "move_to":
                dd_dll.DD_mov(cmd_data[1], cmd_data[2])
            elif cmd_type == "click":
                btn = cmd_data[1]
                dd_dll.DD_btn(btn)
                # 延迟 10-30ms 后抬起
                release_time = time.time() + random.uniform(0.01, 0.03)
                heapq.heappush(pending_events, (release_time, "btn", btn * 2))
            elif cmd_type == "btn_down":
                dd_dll.DD_btn(cmd_data[1])
            elif cmd_type == "btn_up":
                dd_dll.DD_btn(cmd_data[1])
            elif cmd_type == "key_down":
                dd_dll.DD_key(cmd_data[1], 1)
            elif cmd_type == "key_up":
                dd_dll.DD_key(cmd_data[1], 2)
            elif cmd_type == "str":
                s = cmd_data[1]
                if isinstance(s, str): s = s.encode('ascii')
                dd_dll.DD_str(s)
            elif cmd_type == "delay_event":
                heapq.heappush(pending_events, cmd_data[1:])
            elif cmd_type == "quit":
                break
            
            last_action_time = time.time()
                    
        except Exception as e:
            if isinstance(e, EOFError): # 父进程关闭管道
                 break
            print(f"[DD-Process] 执行命令循环异常: {e}")

    print("[DD-Process] 子进程退出")
