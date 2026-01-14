import sys
import os

def get_root_path():
    """获取项目的根目录，兼容脚本运行和打包后的 EXE 运行"""
    if getattr(sys, 'frozen', False):
        # 如果是打包后的环境 (PyInstaller / Nuitka)
        # sys.executable 是 EXE 的路径
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        # 如果是开发环境 (python main.py)
        # 假设 src/utils/paths.py 在 src 目录下，根目录是 src 的父目录
        # 但目前 src 在 sys.path 中，我们通过 main.py 的位置来确定更稳妥
        # 或者直接根据当前文件位置向上找两级
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_abs_path(relative_path):
    """获取相对于根目录的绝对路径"""
    return os.path.join(get_root_path(), relative_path)
