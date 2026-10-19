@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
chcp 65001 >nul
title LocalBox
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONLEGACYWINDOWSSTDIO="
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\start-windows.ps1" %*
exit /b %ERRORLEVEL%
