#!/usr/bin/env bash
#
# Сборка АВТОНОМНОГО исполняемого LocalBox (пользователю НЕ нужно ставить Python).
#
# Важно: PyInstaller НЕ кросс-компилит — собирай на той ОС, под которую нужно:
#   • Windows (в Git Bash / обычной консоли): получится localbox.exe с GUI
#   • Linux: получится бинарь localbox
#
# Требуется на машине СБОРКИ: python3 + pip (+ tkinter: Arch `sudo pacman -S tk`).
# Node.js пользователю всё равно нужен (это рантайм сервера) — либо он ставит node,
# либо в комплект кладётся портативный node в папку <проект>/runtime/  (см. README).
#
set -e
cd "$(dirname "$(readlink -f "$0")")"   # launcher/

echo "Ставлю PyInstaller (если нет)…"
python3 -m pip install --user --upgrade --break-system-packages pyinstaller >/dev/null

echo "Собираю…"
python3 -m PyInstaller --onefile --windowed --name localbox \
    --collect-submodules setup \
    localbox_launcher.py

BIN="dist/localbox"; [ -f "dist/localbox.exe" ] && BIN="dist/localbox.exe"
echo
echo "Готово: launcher/$BIN"
echo "Положи этот файл в папку launcher/ (рядом с setup/) и распространяй вместе с проектом."
echo "Запуск: Windows → двойной клик localbox.exe ; Linux → ./localbox"
