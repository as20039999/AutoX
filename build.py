import os
import subprocess
import sys

def build():
    """
    使用 PyInstaller 进行打包
    """
    print("========================================")
    print("        AutoX PyInstaller 打包工具")
    print("========================================")

    # 1. 确保安装了 PyInstaller
    try:
        import PyInstaller
    except ImportError:
        print("[*] 正在安装 PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 2. 定义排除的重型依赖 (由 python_runtime 环境提供)
    excludes = [
        'torch', 'torchvision', 'PySide6', 'numpy', 'cv2', 
        'matplotlib', 'PIL', 'pywin32', 'mss', 'dxcam', 
        'pyautogui', 'tensorrt', 'onnx', 'cuda', 'PyQt5', 'PyQt6'
    ]
    
    # 3. 构建 PyInstaller 命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                 # 单文件模式
        "--windowed",                # 禁用控制台 (等同于 --noconsole)
        "--name=AutoX",              # 输出文件名
        "--clean",                   # 清理临时文件
        "--noconfirm",               # 覆盖输出目录而不询问
    ]

    # 排除模块
    for mod in excludes:
        cmd.append(f"--exclude-module={mod}")

    # 包含资源与源码 (Windows 下使用分号分隔)
    # PyInstaller add-data 语法: source;target
    cmd.append("--add-data=src;src")
    cmd.append("--add-data=third_party/ultralytics/ultralytics;ultralytics")
    cmd.append("--add-data=configs;configs")
    cmd.append("--add-data=assets;assets")

    # 入口文件
    cmd.append("launcher.py")

    print(f"[*] 执行打包命令: {' '.join(cmd)}")
    
    try:
        subprocess.check_call(cmd)
        
        print("\n[+] 打包成功！可执行文件位于 dist/AutoX.exe")
        print("[+] 请确保运行目录下已通过 init_env.bat 初始化了 python_runtime 环境。")
    except subprocess.CalledProcessError as e:
        print(f"\n[!] 打包失败: {e}")

if __name__ == "__main__":
    build()
