import sys
import os
import traceback

def setup_runtime():
    """
    配置运行时环境：关联虚拟环境并加载必要的源码路径
    """
    # 1. 获取当前程序运行目录
    if getattr(sys, 'frozen', False):
        # 如果是 Nuitka 打包后的 EXE
        # base_dir 是 EXE 所在的物理目录
        base_dir = os.path.dirname(sys.executable)
        # bundle_dir 是资源文件被释放/映射的目录 (Nuitka 中通常就是 __file__ 所在目录)
        bundle_dir = os.path.dirname(os.path.abspath(__file__))
    else:
        # 如果是直接运行脚本
        base_dir = os.path.dirname(os.path.abspath(__file__))
        bundle_dir = base_dir

    # 2. 寻找并激活内置运行时环境
    runtime_path = os.path.join(base_dir, "python_runtime")
    if os.path.exists(runtime_path):
        # 嵌入式 Python 的 site-packages 通常位于 Lib/site-packages
        site_packages = os.path.join(runtime_path, "Lib", "site-packages")
        if not os.path.exists(site_packages):
            # 如果不存在 Lib 目录，尝试根目录 (取决于 pip 安装位置)
            site_packages = runtime_path
            
        # 将运行时的库路径插入到最前面，确保优先使用内置环境中的重型依赖
        if site_packages not in sys.path:
            sys.path.insert(0, site_packages)
        
        # 设置环境变量，确保子进程也能找到路径
        os.environ['PYTHONPATH'] = site_packages + os.pathsep + os.environ.get('PYTHONPATH', '')
        
        # 关键：告诉 Python 解释器使用这个运行时的标准库
        if runtime_path not in sys.path:
            sys.path.insert(0, runtime_path)
    else:
        # 如果找不到运行时环境，给出友好提示
        import ctypes
        message = "未检测到内置运行环境 (python_runtime)！\n\n请先运行 'init_env.bat' 初始化环境后再启动程序。"
        ctypes.windll.user32.MessageBoxW(0, message, "启动错误", 0x10)
        sys.exit(1)

    # 3. 加载打包在 EXE 内部的内容 (业务逻辑 + 本地依赖包)
    # 将 src 目录加入路径
    src_dir = os.path.join(bundle_dir, "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    
    # 由于 ultralytics 已在 build.py 中被打包至 bundle_dir 根目录，
    # 且 PyInstaller 默认会将 bundle_dir 加入 sys.path，
    # 因此这里不需要再手动为 ultralytics 注入路径。
    # 我们只需要确保 bundle_dir 的优先级高于虚拟环境即可。
    if bundle_dir not in sys.path:
        sys.path.insert(0, bundle_dir)

def main():
    try:
        setup_runtime()
        
        # 延迟导入主程序逻辑，确保路径已经配置好
        from main import AutoXApp
        
        app = AutoXApp()
        app.run()
    except Exception as e:
        import ctypes
        error_msg = f"程序启动失败!\n\n错误详情:\n{traceback.format_exc()}"
        print(error_msg)
        ctypes.windll.user32.MessageBoxW(0, error_msg, "运行时错误", 0x10)
        sys.exit(1)

if __name__ == "__main__":
    # 解决多进程打包问题，必须在最开始调用
    import multiprocessing
    multiprocessing.freeze_support()
    main()
