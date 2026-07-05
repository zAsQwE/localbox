#!/usr/bin/env bash
#
# LocalBox — установка одной командой (Linux / macOS).
#
#   ./setup.sh          — зависимости движка + английский клиент (client/)
#   ./setup.sh --ru     — то же + скачать русский клиент (client-ru/) с jackbox.ru (долго, ~0.5 ГБ)
#
# Проверяет, что уже установлено, и делает только недостающее.
# (На Windows запускай из Git Bash, либо ставь части вручную по README.)
#
set -u
cd "$(cd "$(dirname "$0")" && pwd)"   # корень проекта

say()  { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
ok()   { printf '  [ok] %s\n' "$*"; }
warn() { printf '  [!] %s\n' "$*"; }

FETCH_RU=0
[ "${1:-}" = "--ru" ] && FETCH_RU=1

# 1) Node.js / npm
say "Проверка Node.js"
if ! command -v node >/dev/null 2>&1; then
    warn "Node.js не найден. Установите и повторите:"
    echo "    Debian/Ubuntu: curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt-get install -y nodejs"
    echo "    Arch/CachyOS:  sudo pacman -S nodejs npm"
    echo "    Fedora:        sudo dnf install nodejs npm"
    echo "    macOS:         brew install node"
    exit 1
fi
ok "node $(node -v), npm $(npm -v 2>/dev/null)"

# 2) Зависимости движка
say "Зависимости движка (engine/node_modules)"
if [ -d engine/node_modules/express ]; then
    ok "уже установлены"
else
    echo "  npm i ..."
    if ( cd engine && npm i ); then ok "установлены"; else warn "npm i не удался"; exit 1; fi
fi

# 3) Английский клиент (client/)
say "Английский клиент (client/)"
if [ -d client ] && [ -n "$(ls -A client 2>/dev/null)" ]; then
    ok "уже есть"
elif command -v git >/dev/null 2>&1; then
    echo "  git clone DdejjCAT/jackbox.tv ..."
    if git clone --depth 1 https://github.com/DdejjCAT/jackbox.tv client; then
        ok "скачан"
    else
        warn "не удалось склонировать (проверьте интернет/доступ к GitHub)"
    fi
else
    warn "git не найден — установите git или скачайте клиент вручную в папку client/"
fi

# 4) Русский клиент (client-ru/) — по желанию
say "Русский клиент (client-ru/)"
if [ -d client-ru ] && [ -n "$(ls -A client-ru 2>/dev/null)" ]; then
    ok "уже есть"
elif [ "$FETCH_RU" = "1" ]; then
    if [ -d client ]; then
        echo "  скачиваю с jackbox.ru (может занять время)..."
        if node tools/fetch-fun.js --host jackbox.ru --dst client-ru; then
            ok "скачан"
        else
            warn "докачка не удалась — не страшно: движок дотянет недостающее при первой загрузке"
        fi
    else
        warn "нужен client/ как индекс путей — сначала английский клиент"
    fi
else
    warn "пропущен (необязателен). Движок сам докачает нужное с jackbox.ru при первой загрузке."
    echo "      Скачать заранее: ./setup.sh --ru"
fi

say "Готово"
echo "Запуск:  cd launcher && python3 localbox_launcher.py           # GUI (локально)"
echo "         cd launcher && python3 localbox_launcher.py -ip=АЙПИ  # сервер по сети"
