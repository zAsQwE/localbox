#!/usr/bin/env bash
#
# Регистрирует LocalBox в меню приложений (clickable-ярлык) на Linux.
# Запуск:  bash launcher/install-desktop.sh
#
set -e
LAUNCHER="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"   # папка launcher/
APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"

chmod +x "$LAUNCHER/localbox"

cat > "$APPS/localbox.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=LocalBox
GenericName=Jackbox local server
Comment=Локальный сервер Jackbox (все игры)
Exec=$LAUNCHER/localbox
Path=$LAUNCHER
Terminal=false
Categories=Game;Network;
StartupNotify=true
EOF

update-desktop-database "$APPS" 2>/dev/null || true
echo "Ярлык установлен: $APPS/localbox.desktop"
echo "LocalBox появится в меню приложений (может потребоваться перелогин)."
echo "Запуск из терминала: $LAUNCHER/localbox"
