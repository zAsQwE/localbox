Unicode true
!include "LogicLib.nsh"
!include "x64.nsh"

!ifndef PAYLOAD_DIR
!error "Передайте -DPAYLOAD_DIR=папка_файлов через tools/build-installers.py"
!endif
!ifndef OUTPUT_FILE
!define OUTPUT_FILE "setup.exe"
!endif
Name "LocalBox"
Caption "LocalBox"
OutFile "${OUTPUT_FILE}"
RequestExecutionLevel user
SilentInstall silent
WindowIcon off
SetCompressor /SOLID lzma

; NSIS only unpacks the bundle. The single-window UI works before Python is installed.
Section "LocalBox"
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "Для LocalBox нужна 64-битная Windows 10 или 11."
    SetErrorLevel 1
    Quit
  ${EndIf}
  InitPluginsDir
  SetOutPath "$PLUGINSDIR\payload"
  File /r "${PAYLOAD_DIR}/*"
  ExecWait '"$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File "$PLUGINSDIR\payload\installer\windows-ui.ps1" -Source "$PLUGINSDIR\payload"' $0
  SetErrorLevel $0
SectionEnd
