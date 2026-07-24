@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
chcp 65001 >nul
title LocalBox - установка (Windows)

echo ==============================================
echo   LocalBox - установка (Windows)
echo ==============================================
echo.

REM winget доступен? (авто-установка node/python/ffmpeg/git/mkcert)
set "HAVEWG="
where winget >nul 2>nul && set "HAVEWG=1"

REM ---------- 1) Node.js ----------
echo == Node.js ==
where node >nul 2>nul
if errorlevel 1 (
  if defined HAVEWG (
    echo   [!] не найден — ставлю через winget...
    winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
    echo   [i] Node установлен. ЗАКРОЙ это окно и запусти install.bat СНОВА (нужен новый PATH^).
    pause & exit /b 0
  ) else (
    echo   [x] Node.js не найден. Скачай LTS с https://nodejs.org, установи и запусти install.bat снова.
    pause & exit /b 1
  )
)
for /f "delims=" %%v in ('node -v') do echo   [ok] node %%v

REM ---------- 2) Python 3 ----------
echo == Python 3 ==
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY ( where py >nul 2>nul && set "PY=py" )
if not defined PY (
  if defined HAVEWG (
    echo   [!] не найден — ставлю через winget...
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    echo   [i] Python установлен. ЗАКРОЙ это окно и запусти install.bat СНОВА.
    pause & exit /b 0
  ) else (
    echo   [x] Python 3 не найден. Скачай с https://python.org ^(отметь "Add python.exe to PATH"^) и запусти снова.
    pause & exit /b 1
  )
)
echo   [ok] python найден ^(!PY!^)

REM ---------- 3) ffmpeg (TTS + рендер Додо Ре Ми) ----------
echo == ffmpeg ==
where ffmpeg >nul 2>nul
if errorlevel 1 (
  if defined HAVEWG (
    echo   [!] не найден — ставлю через winget ^(для TTS и рендера Додо Ре Ми^)...
    winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
  ) else (
    echo   [!] ffmpeg не найден. Нужен для TTS и рендера Додо Ре Ми: https://ffmpeg.org ^(добавь в PATH^).
  )
) else (
  echo   [ok] есть
)

REM ---------- 4) mkcert (доверенный TLS — проще всего через winget) ----------
echo == mkcert (доверенный сертификат) ==
where mkcert >nul 2>nul
if errorlevel 1 (
  if defined HAVEWG (
    echo   [!] не найден — ставлю через winget...
    winget install -e --id FiloSottile.mkcert --accept-source-agreements --accept-package-agreements
    echo   [i] mkcert установлен. Доверие в систему добавит кнопка "Сертификат" в лаунчере
    echo       ^(один раз выскочит запрос прав администратора — согласись^).
  ) else (
    echo   [i] winget недоступен ^(старая Windows^) — mkcert НЕ нужно ставить вручную:
    echo       лаунчер САМ скачает mkcert при нажатии кнопки "Сертификат" ^(нужен интернет один раз^).
  )
) else (
  echo   [ok] есть
)

REM ---------- 5) git (для скачивания клиента) ----------
echo == git ==
where git >nul 2>nul
if errorlevel 1 (
  if defined HAVEWG (
    echo   [!] не найден — ставлю через winget...
    winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements
    echo   [i] git установлен. Если клиент не скачался ниже — закрой окно и запусти install.bat снова.
  ) else (
    echo   [!] git не найден. Установи Git ^(https://git-scm.com^) или скачай client\ вручную ^(см. README^).
  )
) else (
  echo   [ok] есть
)

REM ---------- 6) Зависимости движка ----------
echo == Зависимости движка ^(server\^) ==
if exist "server\node_modules\express\" (
  echo   [ok] уже установлены
) else (
  echo   npm i в server\ ...
  pushd server
  call npm i
  if errorlevel 1 (
    echo   [x] npm i не удался.
    popd & pause & exit /b 1
  )
  popd
  echo   [ok] установлены
)

REM ---------- 7) Английский клиент ----------
echo == Английский клиент ^(client\^) ==
if exist "client\main\" (
  echo   [ok] уже есть
) else (
  where git >nul 2>nul
  if errorlevel 1 (
    echo   [!] git недоступен — скачай client\ вручную ^(см. README^) или переоткрой окно после установки git.
  ) else (
    echo   git clone DdejjCAT/jackbox.tv ^(большой, ~1 ГБ^)...
    git clone --depth 1 https://github.com/DdejjCAT/jackbox.tv client
    if errorlevel 1 echo   [!] не удалось — движок дотянет ассеты с jackbox.tv при первой загрузке.
  )
)

echo.
echo ==============================================
echo   Готово. Запуск:  start-server.bat
echo ==============================================
echo   В игре ^(Steam - Параметры запуска^):  -jbg.config serverUrl=АДРЕС
echo.
echo Нажми Enter, чтобы закрыть...
pause >nul
