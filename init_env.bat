@echo off
setlocal enabledelayedexpansion

echo ========================================
echo        AutoX 环境初始化工具 (内置 Python)
echo ========================================

set PYTHON_RUNTIME=python_runtime
set PY_ZIP=python_embed.zip
set PY_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip
set GET_PIP_URL=https://bootstrap.pypa.io/get-pip.py
set VC_REDIST_EXE=VC_redist.x64.exe
set VC_REDIST_URL=https://aka.ms/vs/17/release/vc_redist.x64.exe

:: 1. 检查并安装 Visual C++ 运行库
echo [*] 正在检查 Visual C++ 运行库...
if not exist "%VC_REDIST_EXE%" (
    echo [*] 正在下载 Visual C++ 运行库...
    curl -L -o %VC_REDIST_EXE% %VC_REDIST_URL%
)

if exist "%VC_REDIST_EXE%" (
    echo [*] 正在启动 Visual C++ 运行库安装 (静默模式)...
    start /wait "" "%VC_REDIST_EXE%" /install /quiet /norestart
    echo [+] Visual C++ 运行库处理完成。
)

:: 2. 准备 Python 运行时环境
if not exist "%PYTHON_RUNTIME%" (
    if exist "%PY_ZIP%" (
        echo [+] 检测到本地 Python 嵌入式包，正在使用本地文件...
    ) else (
        echo [*] 正在从官网下载 Python 3.11.9 嵌入式包...
        curl -L -o "%PY_ZIP%" "%PY_URL%"
        if %errorlevel% neq 0 (
            echo [!] 错误: 下载 Python 失败，请检查网络。
            pause
            exit /b 1
        )
    )

    echo [*] 正在解压到 %PYTHON_RUNTIME%...
    if not exist "%PYTHON_RUNTIME%" mkdir "%PYTHON_RUNTIME%"
    powershell -Command "Expand-Archive -Path '%PY_ZIP%' -DestinationPath '%PYTHON_RUNTIME%' -Force"
    
    :: 修改 ._pth 文件以支持 site-packages
    echo [*] 正在配置 Python 环境...
    set PTH_FILE=%PYTHON_RUNTIME%\python311._pth
    if exist "!PTH_FILE!" (
        powershell -Command "(Get-Content '!PTH_FILE!') -replace '#import site', 'import site' | Set-Content '!PTH_FILE!'"
    )
    
    :: 下载并安装 pip
    echo [*] 正在安装 pip...
    if not exist "get-pip.py" (
        curl -L -o get-pip.py %GET_PIP_URL%
    )
    "%PYTHON_RUNTIME%\python.exe" get-pip.py --no-warn-script-location
    
    :: 清理临时文件 (可选，保留压缩包可方便下次快速重装)
    :: del get-pip.py
    
    echo [+] Python 运行时环境初始化成功。
) else (
    echo [*] Python 运行时环境已存在，跳过。
)

:: 2. 安装依赖
echo [*] 正在安装依赖 (这可能需要几分钟，请保持网络畅通)...
echo [*] 使用清华大学镜像源加速安装...

"%PYTHON_RUNTIME%\python.exe" -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
"%PYTHON_RUNTIME%\python.exe" -m pip install -r requirements_deploy.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

if %errorlevel% neq 0 (
    echo [!] 错误: 依赖安装过程中出现问题。
    pause
    exit /b 1
)

echo.
echo [+] 环境初始化完成！
echo [+] 现在你可以运行打包好的 AutoX.exe 了。
echo.
pause
