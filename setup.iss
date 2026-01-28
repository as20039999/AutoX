; AutoX 安装包脚本 (Inno Setup)

[Setup]
; 项目基本信息
AppName=AutoX
AppVersion=1.0
AppPublisher=AutoX Team
DefaultDirName={autopf}\AutoX
DefaultGroupName=AutoX
; 允许用户选择安装目录
DisableDirPage=no
; 输出安装包文件名
OutputDir=dist
OutputBaseFilename=AutoX_Setup_v1.0
; 压缩算法
Compression=lzma2/max
SolidCompression=yes
; 卸载图标
UninstallDisplayIcon={app}\AutoX.exe
; 窗口图标
SetupIconFile=assets\logo.ico
; 要求管理员权限进行安装
PrivilegesRequired=admin

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 核心程序和脚本 (从 release_staging 目录读取)
Source: "release_staging\AutoX.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "release_staging\init_env.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "release_staging\requirements_deploy.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "release_staging\VC_redist.x64.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "release_staging\python_embed.zip"; DestDir: "{app}"; Flags: ignoreversion

; 配置文件
Source: "release_staging\configs\*"; DestDir: "{app}\configs"; Flags: ignoreversion recursesubdirs createallsubdirs

; 资源文件 (可选)
Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AutoX"; Filename: "{app}\AutoX.exe"
Name: "{commondesktop}\AutoX"; Filename: "{app}\AutoX.exe"; Tasks: desktopicon

[Run]
; 安装完成后自动执行初始化环境脚本
Filename: "{app}\init_env.bat"; Description: "初始化运行环境 (下载并安装重型依赖，约需5-10分钟)"; Flags: postinstall shellexec waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python_runtime"
Type: filesandordirs; Name: "{app}\*.log"
