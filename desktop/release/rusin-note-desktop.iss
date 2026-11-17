; Windows 安装包（Inno Setup 6，由 release/build.py 通过 ISCC 编译）
; /D 传入：AppVersion、SourceDir（onedir 产物目录）、IconFile（应用图标）
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\rusin-note-desktop"
#endif
#ifndef IconFile
  #define IconFile "..\data\app.ico"
#endif

#define AppName "rusin-note"
#define AppExeName "rusin-note-desktop.exe"
; 固定 AppId：升级时沿用同一安装目录与卸载项，不能随版本变化
#define AppId "{{2E9B4C63-8F1D-4A57-9C2E-6B0F3D5A71C4}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=rusin-note
AppPublisherURL=https://note.rusin7.com
AppSupportURL=https://note.rusin7.com/downloads
AppUpdatesURL=https://note.rusin7.com/downloads
DefaultDirName={localappdata}\Programs\rusin-note-desktop
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; 免管理员：装到当前用户目录，UAC 不弹窗
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#SourceDir}\..\installer
OutputBaseFilename=rusin-note-desktop-{#AppVersion}-windows-setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; 卸载时保留 %APPDATA%\rusin-note-desktop（站点地址、登录态），重装即可继续用
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
