
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
    # 优化：最小间隔设为 3ms (约 333Hz)
    # 既能保证视觉上的平滑，又能大幅减轻驱动子进程的轮询压力
    min_action_interval = 0.003

    while True:
        try:
            now = time.time()
            
            # 1. 频率保护：如果刚执行完动作，强制休息
            time_since_last = now - last_action_time
            if time_since_last < min_action_interval:
                time.sleep(min_action_interval - time_since_last)
                now = time.time()

            # 2. 计算阻塞等待时间
            timeout = None
            if pending_events:
                # 如果有待处理事件，等待直到最近的一个事件到期
                timeout = max(0.0, pending_events[0][0] - now)
                # 优化：如果 timeout 极小，直接处理而不进入 get()，避免频繁唤醒
                if timeout < 0.001:
                    timeout = 0
            
            # 3. 阻塞获取新命令
            got_command = False
            cmd_data = None
            
            try:
                # 仅当没有到期事件需要立即处理时，才进行带超时的阻塞
                if timeout is None:
                    cmd_data = cmd_queue.get()
                    got_command = True
                elif timeout > 0:
                    cmd_data = cmd_queue.get(timeout=timeout)
                    got_command = True
                else:
                    # timeout 为 0，说明有事件到期，非阻塞尝试获取新命令
                    cmd_data = cmd_queue.get_nowait()
                    got_command = True
            except queue.Empty:
                got_command = False
            
            # 4. 处理新命令
            if got_command:
                if cmd_data is None: # 退出信号
                    break

                cmd = cmd_data[0]
                args = cmd_data[1:]
                
                # 在执行任何新指令前，先清理队列中过期的移动指令 (仅保留最新的 move_rel)
                # 这是一个优化策略：如果队列里积压了 10 个移动指令，我们只关心最新的那个
                # 注意：不能清理 click 或 key 指令，否则会漏键
                if cmd == 'move_rel':
                    try:
                        while True:
                            # 尝试查看队列下一个是不是也是 move_rel
                            # 注意：这里不能用 get_nowait 随意取，因为如果是 click 就得放回去，比较麻烦
                            # 简单的策略是：只要我们处理得够快，这里不需要复杂的 peek 逻辑
                            # 依靠主进程的 put_nowait 和队列长度限制即可
                            break
                    except:
                        pass

                if cmd == 'move_rel':
                    dx, dy = args
                    try:
                        c_dx = ctypes.c_int(int(dx))
                        c_dy = ctypes.c_int(int(dy))
                        ret = dd_dll.DD_movR(c_dx, c_dy)
                        last_action_time = time.time()
                    except Exception as e:
                        print(f"[DD-Process] move_rel error: {e}")
                    
                elif cmd == 'move_to':
                    x, y = args
                    dd_dll.DD_mov(int(x), int(y))
                    last_action_time = time.time()
                    
                elif cmd == 'click':
                    btn = args[0] # 1(L), 4(R), 16(M)
                    
                    # [修复] 频率保护：如果待处理的 btn_up 太多，说明之前点击还没结束
                    # 为了防止 DD 驱动崩溃，我们在这里做一个简单的流控
                    # 如果堆积超过 5 个未释放的按键，就丢弃本次点击 (50ms 的积压)
                    if len(pending_events) > 5:
                        continue
                        
                    # DD_btn 按下
                    dd_dll.DD_btn(btn)
                    last_action_time = time.time()
                    
                    # 计划抬起事件
                    # 确保 delay 至少有一点点，比如 10ms-30ms
                    delay = random.uniform(0.01, 0.03)
                    release_time = time.time() + delay
                    heapq.heappush(pending_events, (release_time, 'btn_up', btn * 2))
                    
                elif cmd == 'btn_down':
                    btn = args[0]
                    dd_dll.DD_btn(btn)
                    last_action_time = time.time()
                    
                elif cmd == 'btn_up':
                    btn = args[0]
                    dd_dll.DD_btn(btn)
                    last_action_time = time.time()
                    
                elif cmd == 'key_down':
                    code = args[0]
                    dd_dll.DD_key(code, 1)
                    last_action_time = time.time()
                    
                elif cmd == 'key_up':
                    code = args[0]
                    dd_dll.DD_key(code, 2)
                    last_action_time = time.time()
                    
                elif cmd == 'str':
                    s = args[0]
                    if isinstance(s, str):
                        s = s.encode('ascii')
                    dd_dll.DD_str(s)
                    last_action_time = time.time()
            
            # 2. 处理到期的延迟事件
            now = time.time()
            while pending_events and pending_events[0][0] <= now:
                _, evt_type, evt_arg = heapq.heappop(pending_events)
                
                if evt_type == 'btn_up':
                    dd_dll.DD_btn(evt_arg)
                    last_action_time = time.time()
                    
        except Exception as e:
            if isinstance(e, EOFError): # 父进程关闭管道
                 break
            print(f"[DD-Process] 执行命令循环异常: {e}")

    print("[DD-Process] 子进程退出")
