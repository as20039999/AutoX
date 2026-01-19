
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
    
    # 2. 构建 Nuitka 命令
    # 设置 PYTHONPATH 确保 Nuitka 能找到 src 和 third_party 下的模块
    env = os.environ.copy()
    src_dir = os.path.join(root_dir, 'src')
    third_party_dir = os.path.join(root_dir, 'third_party')
    env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{third_party_dir}{os.pathsep}{env.get('PYTHONPATH', '')}"

    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",                  # 独立运行环境
        "--msvc=latest",                 # 强制使用最新的 MSVC
        "--show-memory",
        "--show-progress",
        "--follow-imports",              # 跟踪导入
        
        # 显式包含本地路径
        f"--include-package-directory={src_dir}",
        f"--include-package-directory={third_party_dir}/ultralytics",
        
        # 插件设置
        "--plugin-enable=pyside6",       # 启用 PySide6 插件
        "--plugin-enable=multiprocessing",# 启用多进程支持
        
        # 强制收集大型库的所有文件 (解决 2MB 只有空壳的问题)
        "--collect-all=torch",
        "--collect-all=torchvision",
        "--collect-all=ultralytics",
        "--collect-all=cv2",
        "--collect-all=dxcam",
        "--collect-all=numpy",
        "--collect-all=tensorrt",
        
        # 排除不必要的库 (减小体积和加快分析)
        "--nofollow-import-to=tkinter",
        "--nofollow-import-to=matplotlib",
        "--nofollow-import-to=pytest",
        "--nofollow-import-to=IPython",
        "--nofollow-import-to=notebook",
        
        # 性能与速度优化
        "--lto=no",                      # 必须关闭，否则链接会极慢
        f"--jobs={os.cpu_count()}",      # 全力使用 CPU
        
        # 包含资源文件夹 (使用绝对路径 source)
        f"--include-data-dir={os.path.join(root_dir, 'assets')}=assets",
        f"--include-data-dir={os.path.join(root_dir, 'configs')}=configs",
        f"--include-data-dir={os.path.join(root_dir, 'models')}=models",
        f"--include-data-dir={os.path.join(root_dir, 'docs')}=docs",
        
        # 包含根目录下的模型
        f"--include-data-file={os.path.join(root_dir, 'base.pt')}=base.pt",
        
        # 界面优化
        "--windows-disable-console",     # 禁用控制台窗口 (GUI 应用)
        "--windows-uac-admin",           # 如果需要管理员权限 (Syscall 通常需要)
        
        # 输出设置
        f"--output-dir={output_dir}",
        "--output-filename=AutoX",       # 输出文件名
        
        # 生成报告，方便调试
        f"--report={os.path.join(output_dir, 'build_report.xml')}",
        
        # 其他
        "--assume-yes-for-downloads",    # 自动下载 Nuitka 需要的组件
        entry_point
    ]
    
    print(f"[Build] 开始打包程序...")
    print(f"[Build] 命令: {' '.join(cmd)}")
    
    try:
        subprocess.check_call(cmd, cwd=root_dir, env=env)
        print(f"\n[Build] 打包完成！输出目录: {os.path.join(output_dir, 'main.dist')}")
        print(f"[Build] 请运行 {os.path.join(output_dir, 'main.dist', 'AutoX.exe')} 进行测试。")
    except subprocess.CalledProcessError as e:
        print(f"\n[Build] 打包失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    package()
