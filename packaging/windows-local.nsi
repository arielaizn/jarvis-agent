Unicode true
Name "Jarvis Agent"
OutFile "${OUTPUT}/Jarvis-Agent-1.0.0-Windows-x64-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\Jarvis Agent"
RequestExecutionLevel user
SetCompressor zlib
!include "MUI2.nsh"
!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${BUNDLE}/LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
Section "Jarvis Agent"
    SetOutPath "$INSTDIR"
    File /r "${BUNDLE}/*"
    CreateDirectory "$SMPROGRAMS\Jarvis Agent"
    CreateShortcut "$SMPROGRAMS\Jarvis Agent\Jarvis Agent.lnk" "$INSTDIR\runtime\pythonw.exe" '"$INSTDIR\launcher.py"' "$INSTDIR\app-source\config\jarvis.ico"
    CreateShortcut "$DESKTOP\Jarvis Agent.lnk" "$INSTDIR\runtime\pythonw.exe" '"$INSTDIR\launcher.py"' "$INSTDIR\app-source\config\jarvis.ico"
    WriteUninstaller "$INSTDIR\Uninstall.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\JarvisAgent" "DisplayName" "Jarvis Agent"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\JarvisAgent" "UninstallString" '"$INSTDIR\Uninstall.exe"'
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\JarvisAgent" "DisplayVersion" "1.0.0"
SectionEnd
Section "Uninstall"
    Delete "$DESKTOP\Jarvis Agent.lnk"
    RMDir /r "$SMPROGRAMS\Jarvis Agent"
    RMDir /r "$INSTDIR\runtime"
    RMDir /r "$INSTDIR\app-source"
    Delete "$INSTDIR\launcher.py"
    Delete "$INSTDIR\app-manifest.json"
    Delete "$INSTDIR\dependencies.json"
    Delete "$INSTDIR\LICENSE"
    Delete "$INSTDIR\THIRD_PARTY.md"
    Delete "$INSTDIR\README.he.md"
    Delete "$INSTDIR\Jarvis Agent.cmd"
    Delete "$INSTDIR\Uninstall.exe"
    RMDir "$INSTDIR"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\JarvisAgent"
    ; Private notes and settings are in a separate per-user directory and remain.
SectionEnd
