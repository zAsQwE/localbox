#!/usr/bin/env bash
# sudo reads this stdout directly; it never enters the installation log.
source "$(dirname "${BASH_SOURCE[0]}")/i18n.sh"
set -eu
if command -v zenity >/dev/null 2>&1; then
    exec zenity --password --title="$(localbox_text 'LocalBox — пароль администратора' 'LocalBox — administrator password')"
elif command -v kdialog >/dev/null 2>&1; then
    exec kdialog --title LocalBox --password "$(localbox_text 'Пароль администратора для установки системных пакетов:' 'Administrator password to install system packages:')"
else
    exec python3 "$(dirname "$0")/askpass.py"
fi
