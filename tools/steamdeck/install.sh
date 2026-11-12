#!/bin/bash
# Установка LocalBox для Steam Deck (SteamOS) из этой папки. Повторный запуск безопасен.
#   - скачивает переносимый Node.js в runtime/node (с проверкой SHA-256);
#   - ставит зависимости сервера и segno (QR-оверлей) в runtime/steamdeck-py;
#   - создаёт server/config.json и пользовательскую службу localbox;
#   - в конце печатает единственную команду с sudo (права на порты 80/443 для node).
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
RUNTIME="$ROOT/runtime"
UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/localbox.service"
say() { printf '\n== %s\n' "$*"; }

say "Node.js"
# Свой переносимый Node: права на порты 80/443 выдаются только ему (на SteamOS /usr только для чтения).
NODE="$RUNTIME/node/bin/node"
if [ ! -x "$NODE" ]; then
    base="https://nodejs.org/dist/latest-v24.x"
    file=$(curl -fsSL "$base/SHASUMS256.txt" | grep -oE 'node-v[0-9.]+-linux-x64\.tar\.xz' | head -1)
    work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
    curl -fsSL "$base/$file" -o "$work/$file"
    (cd "$work" && curl -fsSL "$base/SHASUMS256.txt" | grep " $file\$" | sha256sum -c -)
    mkdir -p "$RUNTIME/node" && tar -xJf "$work/$file" -C "$RUNTIME/node" --strip-components=1
fi
NODE="$(readlink -f "$NODE")"
echo "$NODE ($("$NODE" --version))"

say "Зависимости сервера"
(cd "$ROOT/server" && PATH="$(dirname "$NODE"):$PATH" npm ci --omit=dev --no-audit --no-fund)
[ -f "$ROOT/server/config.json" ] || cp "$ROOT/server/config.example.json" "$ROOT/server/config.json"

say "segno для QR-оверлея"
pylib="$RUNTIME/steamdeck-py"
if ! PYTHONPATH="$pylib" python3 -c "import segno" 2>/dev/null; then
    venv=$(mktemp -d)
    python3 -m venv "$venv" && "$venv/bin/pip" -q install --target "$pylib" segno
    rm -rf "$venv"
fi

say "Служба localbox"
client=""
for dir in client-ru client; do
    if [ -d "$ROOT/$dir" ]; then client="Environment=LOCALBOX_CLIENT_DIR=../$dir"; break; fi
done
mkdir -p "$(dirname "$UNIT")" "${XDG_STATE_HOME:-$HOME/.local/state}/localbox"
cat > "$UNIT" <<EOF
[Unit]
Description=LocalBox — локальный сервер Jackbox

[Service]
WorkingDirectory=$ROOT/server
$client
# Без Piper/Silero сервер на каждую фразу пытается скачать голос Piper; на Deck хватает espeak.
Environment=LOCALBOX_TTS_ENGINE=espeak
# Телефоны — на высокий порт: обновления SteamOS закрывают 80/443 брандмауэром.
Environment=LOCALBOX_PLAYER_PORT=38204
ExecStart=$NODE server.js
StandardOutput=append:${XDG_STATE_HOME:-$HOME/.local/state}/localbox/server.log
StandardError=inherit
Restart=on-failure
RestartSec=3
EOF
systemctl --user daemon-reload
[ -n "$client" ] || echo "Веб-клиент не найден (client-ru/ или client/) — см. docs/manual.md."
chmod +x "$ROOT/tools/steamdeck/jackbox.sh" "$ROOT/tools/steamdeck/qr-overlay.py"

say "Готово"
if getcap "$NODE" 2>/dev/null | grep -q cap_net_bind_service; then
    echo "Права на порты 80/443 уже выданы."
else
    echo "Игра подключается к комнате только через порт 443. Один раз выполните (нужен пароль):"
    echo "    sudo setcap cap_net_bind_service=+ep $NODE"
fi
echo
echo "Параметры запуска в Steam для каждого пака Jackbox:"
echo "    $ROOT/tools/steamdeck/jackbox.sh -local %command%"
