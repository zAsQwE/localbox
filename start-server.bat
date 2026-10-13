@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
chcp 65001 >nul
title LocalBox
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\start-windows.ps1" %*
exit /b %ERRORLEVEL%
