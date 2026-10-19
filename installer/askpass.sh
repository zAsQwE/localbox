#!/usr/bin/env bash
# sudo reads this stdout directly; it never enters the installation log.
set -eu
if command -v zenity >/dev/null 2>&1; then
    exec zenity --password --title='LocalBox — пароль администратора'
elif command -v kdialog >/dev/null 2>&1; then
    exec kdialog --title LocalBox --password 'Пароль администратора для установки системных пакетов:'
else
    exec python3 "$(dirname "$0")/askpass.py"
fi
