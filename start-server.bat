@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
chcp 65001 >nul
title LocalBox - сервер

REM ---- Python ----
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY ( where py >nul 2>nul && set "PY=py" )
if not defined PY (
  echo [x] Python не найден. Сначала запусти install.bat.
  echo.
  echo Нажми Enter, чтобы закрыть...
  pause >nul & exit /b 1
)

REM ---- Движок установлен? ----
if not exist "server\node_modules\express\" (
  echo [!] Зависимости движка не найдены — запусти сначала install.bat.
  echo.
  echo Нажми Enter, чтобы закрыть...
  pause >nul & exit /b 1
)

:MENU
echo ==============================================
echo   LocalBox — выбери режим запуска
echo ==============================================
echo   [1] Обычный LocalBox (без Додо Ре Ми)
echo   [2] С поддержкой Додо Ре Ми (рендер выступления)
echo.
set "MODE="
set /p MODE="Введи 1 или 2 и нажми Enter: "
if "%MODE%"=="1" goto PLAIN
if "%MODE%"=="2" goto DODO
echo   Не понял ввод — попробуй ещё раз.
echo.
goto MENU

:DODO
echo.
echo == Проверка файлов для Додо Ре Ми ==
set "LOCALBOX_DODO=1"

REM ffmpeg (обязателен для рендера)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo   [!] ffmpeg НЕ найден — рендер выступления НЕ соберётся.
  echo       Поставь ffmpeg: запусти install.bat или скачай с https://ffmpeg.org ^(добавь в PATH^).
) else (
  echo   [ok] ffmpeg найден.
)

REM бэкинги песен (нужны для музыки; без них — только ноты)
set "HAVEBACK="
if exist "server\render\nopus-opus\songs\" (
  for /d %%d in ("server\render\nopus-opus\songs\*") do (
    if exist "%%d\backing*.ogg" set "HAVEBACK=1"
  )
)
if defined HAVEBACK (
  echo   [ok] Бэкинги песен найдены — выступление будет с музыкой.
) else (
  echo   [!] Бэкинги песен НЕ найдены — выступление соберётся БЕЗ музыки ^(только ноты игрока^).
  echo       Куда класть ^(backing.ogg каждой песни^):
  echo           server\render\nopus-opus\songs\^<slug^>\backing.ogg
  echo       Взять из установленной игры:
  echo           ...\games\NopusOpus\songs\^<slug^>\
  echo       Сэмплы инструментов докачаются сами при первом рендере.
)
echo.
echo   ^(<slug^> — папка песни, напр. trivia-murder-party-2^)
echo.
echo Нажми Enter, чтобы запустить с Додо Ре Ми ^(или закрой окно, чтобы отменить^)...
pause >nul
goto RUN

:PLAIN
set "LOCALBOX_DODO="
echo.
echo == Обычный режим (без Додо Ре Ми) ==

:RUN
echo.
echo == Запуск лаунчера ==
echo   В окне: 1) укажи адрес  2) нажми "Сертификат"  3) "Запустить".
echo.
cd launcher
!PY! localbox_launcher.py %*
cd ..

echo.
echo == Сервер остановлен ==
echo Нажми Enter, чтобы закрыть...
pause >nul
