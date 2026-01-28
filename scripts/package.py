
import os
import subprocess
import sys
import shutil

def package():
    # 1. 确定路径
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    entry_point = os.path.join(root_dir, "src", "main.py")
    output_dir = os.path.join(root_dir, "dist")
    
    if os.path.exists(output_dir):
        print(f"[Build] 清理旧的输出目录: {output_dir}")
        shutil.rmtree(output_dir)
    
    # 2. 构建 PyInstaller 命令
    # 设置 PYTHONPATH 确保 PyInstaller 能找到 src 和 third_party 下的模块
    env = os.environ.copy()
    src_dir = os.path.join(root_dir, 'src')
    third_party_dir = os.path.join(root_dir, 'third_party')
    env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{third_party_dir}{os.pathsep}{env.get('PYTHONPATH', '')}"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",                      # 文件夹模式 (等同于 Nuitka standalone)
        "--name=AutoX",                  # 输出文件名
        "--windowed",                    # 禁用控制台
        "--uac-admin",                   # 请求管理员权限
        "--clean",                       # 清理临时文件
        "--noconfirm",                   # 自动覆盖输出
        
        # 显式包含本地路径
        f"--add-data={src_dir};src",
        f"--add-data={os.path.join(third_party_dir, 'ultralytics', 'ultralytics')};ultralytics",
        
        # 强制收集大型库的所有文件
        "--collect-all=torch",
        "--collect-all=torchvision",
        "--collect-all=ultralytics",
        "--collect-all=cv2",
        "--collect-all=dxcam",
        "--collect-all=numpy",
        "--collect-all=tensorrt",
        
        # 排除不必要的库
        "--exclude-module=tkinter",
        "--exclude-module=matplotlib",
        "--exclude-module=pytest",
        "--exclude-module=IPython",
        "--exclude-module=notebook",
        
        # 包含资源文件夹 (Windows 下使用分号分隔)
        f"--add-data={os.path.join(root_dir, 'assets')};assets",
        f"--add-data={os.path.join(root_dir, 'configs')};configs",
        f"--add-data={os.path.join(root_dir, 'models')};models",
        f"--add-data={os.path.join(root_dir, 'docs')};docs",
        
        # 包含根目录下的模型
        f"--add-data={os.path.join(root_dir, 'base.pt')};.",
        
        # 输出路径设置
        f"--workpath={os.path.join(output_dir, 'build')}",
        f"--distpath={output_dir}",
        f"--specpath={output_dir}",
        
        entry_point
    ]
    
    print(f"[Build] 开始打包程序...")
    print(f"[Build] 命令: {' '.join(cmd)}")
    
    try:
        subprocess.check_call(cmd, cwd=root_dir, env=env)
        print(f"\n[Build] 打包完成！输出目录: {os.path.join(output_dir, 'AutoX')}")
        print(f"[Build] 请运行 {os.path.join(output_dir, 'AutoX', 'AutoX.exe')} 进行测试。")
    except subprocess.CalledProcessError as e:
        print(f"\n[Build] 打包失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    package()
