import sys
import os

def get_root_path():
    """获取项目的根目录，兼容脚本运行和打包后的 EXE 运行"""
    # Nuitka 会设置 __compiled__，PyInstaller 会设置 sys.frozen
    if getattr(sys, 'frozen', False) or '__compiled__' in globals():
        # 如果是打包后的环境
        # sys.executable 是 EXE 的路径 (例如: D:\AutoX\AutoX.exe)
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        # 如果是开发环境 (python main.py)
        # 当前文件在 src/utils/paths.py，向上找三层到达根目录
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_abs_path(relative_path):
    """获取相对于根目录的绝对路径"""
    return os.path.join(get_root_path(), relative_path)

def get_asset_path(relative_path):
    """获取相对于 assets 目录的绝对路径"""
    return os.path.join(get_root_path(), "assets", relative_path)
