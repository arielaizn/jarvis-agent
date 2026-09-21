[Setup]
AppId=ai.jarvisagent.desktop
AppName=Jarvis Agent
AppVersion=1.0.0
DefaultDirName={localappdata}\Programs\Jarvis Agent
DefaultGroupName=Jarvis Agent
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=Jarvis-Agent-1.0.0-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\JarvisAgent.exe
LicenseFile=..\LICENSE
[Files]
Source: "..\dist\JarvisAgent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Jarvis Agent"; Filename: "{app}\JarvisAgent.exe"
Name: "{autodesktop}\Jarvis Agent"; Filename: "{app}\JarvisAgent.exe"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
[Run]
Filename: "{app}\JarvisAgent.exe"; Description: "Launch Jarvis Agent"; Flags: nowait postinstall skipifsilent
