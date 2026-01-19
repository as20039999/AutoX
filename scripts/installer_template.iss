
; AutoX Installer Script for Inno Setup
; To build: Install Inno Setup and compile this script.

[Setup]
AppName=AutoX
AppVersion=1.0
DefaultDirName={autopf}\AutoX
DefaultGroupName=AutoX
UninstallDisplayIcon={app}\AutoX.exe
Compression=lzma2
SolidCompression=yes
OutputDir=dist\installer
OutputBaseFilename=AutoX_Setup_v1.0
; PrivilegesRequired=admin ; Already handled by AutoX.exe uac-admin

[Files]
; The main distribution folder from Nuitka
Source: "dist\main.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AutoX"; Filename: "{app}\AutoX.exe"
Name: "{commondesktop}\AutoX"; Filename: "{app}\AutoX.exe"

[Run]
Filename: "{app}\AutoX.exe"; Description: "Launch AutoX"; Flags: nowait postinstall skipifsilent
