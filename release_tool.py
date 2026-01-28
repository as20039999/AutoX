import os
import shutil
import subprocess
import urllib.request

def collect_release():
    """
    自动化收集发布所需的所有文件，准备制作安装包
    """
    staging_dir = "release_staging"
    dist_dir = "dist"
    
    print("========================================")
    print("        AutoX 发布包准备工具")
    print("========================================")

    # 1. 确保构建产物存在
    if not os.path.exists(os.path.join(dist_dir, "AutoX.exe")):
        print("[!] 错误: 未发现 dist/AutoX.exe，请先运行 python build.py")
        return

    # 2. 创建暂存目录
    if os.path.exists(staging_dir):
        shutil.rmtree(staging_dir)
    os.makedirs(staging_dir)
    os.makedirs(os.path.join(staging_dir, "configs"), exist_ok=True)

    # 3. 复制核心文件
    print("[*] 正在收集核心文件...")
    files_to_copy = [
        (os.path.join(dist_dir, "AutoX.exe"), "AutoX.exe"),
        ("init_env.bat", "init_env.bat"),
        ("requirements_deploy.txt", "requirements_deploy.txt"),
    ]
    
    for src, dst in files_to_copy:
        shutil.copy2(src, os.path.join(staging_dir, dst))
        print(f"  [+] 已复制: {dst}")

    # 复制配置文件夹
    if os.path.exists("configs"):
        for item in os.listdir("configs"):
            s = os.path.join("configs", item)
            d = os.path.join(staging_dir, "configs", item)
            if os.path.isfile(s):
                shutil.copy2(s, d)
        print("  [+] 已复制: configs/")

    # 4. 下载/准备预置环境包 (提升用户体验的关键)
    external_deps = [
        {
            "name": "VC_redist.x64.exe",
            "url": "https://aka.ms/vs/17/release/vc_redist.x64.exe"
        },
        {
            "name": "python_embed.zip",
            "url": "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
        }
    ]

    for dep in external_deps:
        target_path = os.path.join(staging_dir, dep["name"])
        # 如果本地根目录已有，直接复制
        if os.path.exists(dep["name"]):
            print(f"[*] 发现本地 {dep['name']}，正在复制...")
            shutil.copy2(dep["name"], target_path)
        else:
            # 否则尝试下载
            print(f"[*] 正在下载 {dep['name']} (约 {('24MB' if 'VC' in dep['name'] else '10MB')})...")
            try:
                urllib.request.urlretrieve(dep["url"], target_path)
                print(f"  [+] 下载成功: {dep['name']}")
            except Exception as e:
                print(f"  [!] 下载失败: {e}。用户安装时脚本将尝试再次下载。")

    print("\n========================================")
    print(f"[+] 准备就绪！发布文件位于: {os.path.abspath(staging_dir)}")
    print("[+] 下一步：")
    print("    1. 确保安装了 Inno Setup")
    print("    2. 使用 Inno Setup 编译项目根目录下的 setup.iss")
    print("========================================")

if __name__ == "__main__":
    collect_release()
