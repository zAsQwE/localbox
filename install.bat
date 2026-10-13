@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
chcp 65001 >nul
if exist "%~dp0dist\setup.exe" goto DIST_SETUP
if exist "%~dp0setup.exe" goto ROOT_SETUP
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\windows-bootstrap.ps1" -Prompt
exit /b %ERRORLEVEL%
:DIST_SETUP
start "" /wait "%~dp0dist\setup.exe"
exit /b %ERRORLEVEL%
:ROOT_SETUP
start "" /wait "%~dp0setup.exe"
exit /b %ERRORLEVEL%
