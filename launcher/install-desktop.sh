#!/usr/bin/env bash
#
# Регистрирует LocalBox в меню приложений (clickable-ярлык) на Linux.
# Запуск:  bash launcher/install-desktop.sh
#
set -e
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"

chmod +x "$ROOT/localbox"

cat > "$APPS/localbox.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=LocalBox
GenericName=Jackbox local server
Comment=Локальный сервер Jackbox (все игры)
Exec=$ROOT/localbox
Path=$ROOT
Terminal=false
Categories=Game;Network;
StartupNotify=true
EOF

update-desktop-database "$APPS" 2>/dev/null || true
echo "Ярлык установлен: $APPS/localbox.desktop"
echo "LocalBox появится в меню приложений (может потребоваться перелогин)."
echo "Запуск из терминала: $ROOT/localbox"
