#!/bin/bash
# Запуск игр Jackbox на Steam Deck с выбором сервера.
#
# Steam → игра → Свойства → Параметры запуска:
#     /путь/к/LocalBox/tools/steamdeck/jackbox.sh -local %command%       — LocalBox на этом Deck, без интернета
#     /путь/к/LocalBox/tools/steamdeck/jackbox.sh -online-ru %command%   — российские серверы (jb-ecast.klucva.ru)
#     /путь/к/LocalBox/tools/steamdeck/jackbox.sh -online %command%      — официальные серверы игры
#     /путь/к/LocalBox/tools/steamdeck/jackbox.sh %command%              — режим по умолчанию
#
# Команды:
#     jackbox.sh mode local|online-ru|online — режим по умолчанию
#     jackbox.sh status                      — режим, IP, сервер, адрес для игроков
#
# QR поверх игры: в -local — с кодом комнаты, пока идёт лобби; в онлайн-режимах — на сайт клиента,
# в меню и LOCALBOX_QR_SECONDS (30) секунд после создания комнаты. Отключить: LOCALBOX_QR=0.
set -u

ROOT="${LOCALBOX_ROOT:-$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)}"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/localbox"
MODE_FILE="$STATE/mode"
LOG="$STATE/launch.log"
CONFIG="$ROOT/server/config.json"
CERT="$ROOT/certs/localbox.pem"
KEY="$ROOT/certs/localbox-key.pem"
RU_SERVER="jb-ecast.klucva.ru"
mkdir -p "$STATE"

log() { printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }

# Steam передаёт свои LD_LIBRARY_PATH/LD_PRELOAD, с ними системные программы ломаются
# (curl: "CURL_OPENSSL_4 not found"). Служебные команды запускаем без них.
sys() { env -u LD_LIBRARY_PATH -u LD_PRELOAD PATH=/usr/bin:/bin "$@"; }

norm_mode() {
    case "${1#-}" in
        local|online-ru|online) echo "${1#-}" ;;
        *) return 1 ;;
    esac
}

current_mode() {
    norm_mode "${LOCALBOX_MODE:-}" 2>/dev/null || norm_mode "$(cat "$MODE_FILE" 2>/dev/null)" 2>/dev/null || echo local
}

local_ip() {
    sys ip -4 route get 1.1.1.1 2>/dev/null | grep -oE 'src [0-9.]+' | cut -d' ' -f2
}

# Адрес для телефонов: в -local — тот, что отдаёт сервер (с фактическим веб-портом).
player_site() {
    case "$1" in
        local)
            local url
            url=$(sys curl -s -m 2 http://127.0.0.1:38202/localbox/status http://127.0.0.1/localbox/status 2>/dev/null |
                  grep -oE '"playerUrl":"[^"]+"' | head -1 | cut -d'"' -f4)
            echo "${url:-http://$(local_ip):38202}  (QR с кодом — поверх лобби)" ;;
        online-ru) echo "https://jackbox.ru" ;;
        online) echo "https://jackbox.fun" ;;
    esac
}

# Сертификат и serverUrl должны совпадать с текущим IP: после смены сети старый сертификат
# игра отклонит. Сервер перезапускается один раз, если что-то поменялось.
ensure_ip() {
    local ip="$1" changed=0
    if ! sys openssl x509 -in "$CERT" -noout -ext subjectAltName 2>/dev/null | grep -q "IP Address:$ip\b"; then
        log "новый IP $ip — перевыпускаю сертификат"
        mkdir -p "$(dirname "$CERT")"
        sys openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 3650 \
            -keyout "$KEY" -out "$CERT" -subj "/CN=LocalBox $ip" \
            -addext "subjectAltName=IP:$ip,DNS:localhost" 2>/dev/null || return 1
        changed=1
    fi
    if ! grep -q "\"serverUrl\": \"$ip\"" "$CONFIG"; then
        sed -i "s/\"serverUrl\": \"[^\"]*\"/\"serverUrl\": \"$ip\"/" "$CONFIG"
        changed=1
    fi
    [ "$changed" = 0 ] || sys systemctl --user restart localbox
}

port_open() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

# Игра подключается к комнате только по wss на 443 — ждём именно его.
ensure_server() {
    sys systemctl --user is-active --quiet localbox || sys systemctl --user start localbox
    for _ in $(seq 60); do
        port_open 443 && return 0
        sleep 0.5
    done
    log "ВНИМАНИЕ: сервер LocalBox не ответил за 30 с (journalctl --user -u localbox)"
    return 1
}

# gamescope показывает внешние оверлеи только с X-дисплея самого Steam, не игры.
steam_display() {
    local d
    for d in :0 :1 :2; do
        sys env DISPLAY=$d xprop -root GAMESCOPE_XWAYLAND_SERVER_ID 2>/dev/null | grep -q '= 0$' && { echo "$d"; return; }
    done
    echo "${DISPLAY:-:0}"
}

# Без аргумента — QR с кодом комнаты LocalBox; с адресом — QR на сайт клиента.
start_qr() {
    [ "${LOCALBOX_QR:-1}" = 0 ] && return
    sys systemctl --user stop localbox-qr 2>/dev/null
    sys systemctl --user reset-failed localbox-qr 2>/dev/null
    sys systemd-run --user --unit=localbox-qr --collect -E DISPLAY="$(steam_display)" \
        -E LOCALBOX_QR_SITE="${1:-}" -E LOCALBOX_QR_SECONDS="${LOCALBOX_QR_SECONDS:-30}" \
        -E LOCALBOX_PYLIB="$ROOT/runtime/steamdeck-py" \
        /usr/bin/python3 "$ROOT/tools/steamdeck/qr-overlay.py" >/dev/null 2>&1 || log "не удалось запустить QR-оверлей"
}

case "${1:-}" in
    mode)
        m="$(norm_mode "${2:-}")" || { echo "Использование: $0 mode local|online-ru|online" >&2; exit 2; }
        echo "$m" > "$MODE_FILE"; echo "Режим по умолчанию: $m"; exit 0 ;;
    status)
        m="$(current_mode)"
        echo "Режим по умолчанию: $m"
        echo "IP: $(local_ip)"
        echo "Сервер LocalBox: $(sys systemctl --user is-active localbox)"
        echo "Игрокам: $(player_site "$m")"
        exit 0 ;;
    "")
        echo "Использование: $0 [-local|-online-ru|-online] %command% | mode РЕЖИМ | status" >&2; exit 2 ;;
esac

# Флаг режима может стоять где угодно в строке — убираем его из аргументов игры.
args=()
for a in "$@"; do
    case "$a" in
        -local|-online-ru|-online) LOCALBOX_MODE="${a#-}" ;;
        *) args+=("$a") ;;
    esac
done
[ ${#args[@]} -gt 0 ] || { echo "Нет команды игры (%command%)." >&2; exit 2; }

mode="$(current_mode)"
case "$mode" in
    local)
        ip="$(local_ip)"
        if [ -z "$ip" ]; then
            # Сети нет — игра на этом же Deck всё равно дойдёт до сервера по localhost.
            ip=127.0.0.1; log "ВНИМАНИЕ: нет IP в сети, использую 127.0.0.1 (телефоны не подключатся)"
        fi
        ensure_ip "$ip" || log "ВНИМАНИЕ: не удалось обновить сертификат для $ip"
        ensure_server
        start_qr
        # Даже если проверка не прошла, остаёмся на локальном сервере, а не уходим в интернет.
        extra=(-jbg.config "serverUrl=$ip" -cafile "$CERT") ;;
    online-ru)
        start_qr "https://jackbox.ru"
        extra=(-jbg.config "serverUrl=$RU_SERVER") ;;
    online)
        start_qr "https://jackbox.fun"
        extra=() ;;
esac
log "режим $mode: ${args[*]} ${extra[*]}"
exec "${args[@]}" "${extra[@]}"
