#!/usr/bin/env bash
#
# LocalBox — установка одной командой (Linux / macOS).
#
#   ./setup.sh          — всё: системные зависимости + движок + английский клиент (client/)
#   ./setup.sh --ru     — то же + скачать русский клиент (client-ru/) с jackbox.ru (долго, ~0.5 ГБ)
#   ./setup.sh --run    — после установки сразу запустить (GUI, или сервер если нет дисплея)
#
# Пытается доставить недостающее САМ через пакетный менеджер (apt/pacman/dnf/zypper/brew).
# Node.js/Python/ffmpeg ставятся автоматически (с sudo, где нужно). На Windows — install.bat.
#
set -u
cd "$(cd "$(dirname "$0")" && pwd)"   # корень проекта

say()  { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
ok()   { printf '  \033[32m[ok]\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m[!]\033[0m %s\n' "$*"; }
err()  { printf '  \033[31m[x]\033[0m %s\n' "$*"; }

FETCH_RU=0; RUN_AFTER=0
for a in "$@"; do
    case "$a" in
        --ru) FETCH_RU=1 ;;
        --run) RUN_AFTER=1 ;;
    esac
done

# --- определить пакетный менеджер ---
PM=""; SUDO=""
if   command -v apt-get >/dev/null 2>&1; then PM=apt
elif command -v pacman  >/dev/null 2>&1; then PM=pacman
elif command -v dnf     >/dev/null 2>&1; then PM=dnf
elif command -v zypper  >/dev/null 2>&1; then PM=zypper
elif command -v brew    >/dev/null 2>&1; then PM=brew
fi
[ "$PM" != "brew" ] && [ "$(id -u)" != "0" ] && command -v sudo >/dev/null 2>&1 && SUDO="sudo"

# pkg_install <apt-пакеты> <pacman> <dnf> <zypper> <brew>  (x = пропустить на этом ПМ)
pkg_install() {
    case "$PM" in
        apt)    [ "$1" = x ] || { $SUDO apt-get update -y && $SUDO apt-get install -y $1; } ;;
        pacman) [ "$2" = x ] || $SUDO pacman -S --needed --noconfirm $2 ;;
        dnf)    [ "$3" = x ] || $SUDO dnf install -y $3 ;;
        zypper) [ "$4" = x ] || $SUDO zypper install -y $4 ;;
        brew)   [ "$5" = x ] || brew install $5 ;;
        *)      return 1 ;;
    esac
}

# 1) Node.js / npm
say "Node.js"
if command -v node >/dev/null 2>&1; then
    ok "node $(node -v), npm $(npm -v 2>/dev/null)"
else
    warn "Node.js не найден — устанавливаю…"
    if [ "$PM" = "apt" ]; then
        curl -fsSL https://deb.nodesource.com/setup_20.x | $SUDO -E bash - && $SUDO apt-get install -y nodejs
    else
        pkg_install nodejs "nodejs npm" "nodejs npm" "nodejs npm" node
    fi
    if command -v node >/dev/null 2>&1; then ok "node $(node -v)"; else
        err "не удалось поставить Node.js автоматически. Поставьте вручную (https://nodejs.org) и повторите."; exit 1
    fi
fi

# 2) Python 3 (нужен для лаунчера)
say "Python 3"
if command -v python3 >/dev/null 2>&1; then
    ok "$(python3 --version 2>&1)"
else
    warn "Python 3 не найден — устанавливаю…"
    pkg_install python3 python python3 python3 python
    command -v python3 >/dev/null 2>&1 && ok "$(python3 --version 2>&1)" || warn "поставьте python3 вручную (нужен для лаунчера)"
fi

# 3) ffmpeg (TTS + рендер Додо Ре Ми)
say "ffmpeg"
if command -v ffmpeg >/dev/null 2>&1; then
    ok "есть"
else
    warn "ffmpeg не найден — устанавливаю (нужен для TTS и рендера Додо Ре Ми)…"
    pkg_install ffmpeg ffmpeg ffmpeg ffmpeg ffmpeg
    command -v ffmpeg >/dev/null 2>&1 && ok "поставлен" || warn "поставьте ffmpeg вручную позже"
fi

# 4) mkcert (доверенный TLS — по желанию)
say "mkcert (по желанию)"
if command -v mkcert >/dev/null 2>&1; then
    ok "есть"
else
    warn "нет — ставлю (иначе будет самоподписанный серт)…"
    pkg_install "mkcert libnss3-tools" "mkcert nss" mkcert mkcert mkcert
    command -v mkcert >/dev/null 2>&1 && ok "поставлен" || warn "необязателен — примешь предупреждение о серте в браузере"
fi

# 5) Зависимости движка (server/node_modules)
say "Зависимости движка (server/)"
if [ -d server/node_modules/express ]; then
    ok "уже установлены"
else
    echo "  npm i в server/ …"
    if ( cd server && npm i ); then ok "установлены"; else err "npm i не удался"; exit 1; fi
fi

# 6) Английский клиент (client/) — ассеты игр для телефонов
say "Английский клиент (client/)"
if [ -d client ] && [ -e client/main ]; then
    ok "уже есть"
elif command -v git >/dev/null 2>&1; then
    echo "  git clone DdejjCAT/jackbox.tv (большой, ~1 ГБ)…"
    if git clone --depth 1 https://github.com/DdejjCAT/jackbox.tv client; then
        ok "скачан"
    else
        warn "не удалось склонировать — движок дотянет ассеты с jackbox.tv при первой загрузке"
    fi
else
    warn "git не найден — установите git или скачайте client/ вручную (см. README)"
fi

# 7) Русский клиент (client-ru/) — по желанию
say "Русский клиент (client-ru/)"
if [ -d client-ru ] && [ -n "$(ls -A client-ru 2>/dev/null)" ]; then
    ok "уже есть"
elif [ "$FETCH_RU" = "1" ]; then
    if [ -e client/main ]; then
        echo "  скачиваю с jackbox.ru (может занять время)…"
        node tools/fetch-fun.js --host jackbox.ru --dst client-ru && ok "скачан" \
            || warn "докачка не удалась — движок дотянет недостающее при первой загрузке"
    else
        warn "нужен client/ как индекс путей — сначала английский клиент"
    fi
else
    warn "пропущен (необязателен). Движок сам докачает нужное с jackbox.ru. Заранее: ./setup.sh --ru"
fi

say "Готово"
echo "Запуск:  cd launcher && python3 localbox_launcher.py           # GUI (локально)"
echo "         cd launcher && python3 localbox_launcher.py -ip=АЙПИ  # сервер по сети"
echo "Игра (Steam → Параметры запуска):  -jbg.config serverUrl=АДРЕС"

if [ "$RUN_AFTER" = "1" ]; then
    say "Запускаю лаунчер"
    ( cd launcher && python3 localbox_launcher.py )
fi
