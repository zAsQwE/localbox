#!/usr/bin/env bash
#
# LocalBox — запуск сервера (Linux / macOS). Аналог start-server.bat.
#   ./start-server.sh                 — меню: обычный или с Додо Ре Ми, затем лаунчер (GUI/сервер)
#   ./start-server.sh -ip=1.2.3.4     — аргументы пробрасываются в лаунчер (серверный режим)
#
set -u
cd "$(cd "$(dirname "$0")" && pwd)"   # корень проекта

say()  { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
ok()   { printf '  \033[32m[ok]\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m[!]\033[0m %s\n' "$*"; }

# --- Python ---
PY=""
command -v python3 >/dev/null 2>&1 && PY=python3
[ -z "$PY" ] && command -v python >/dev/null 2>&1 && PY=python
if [ -z "$PY" ]; then
    warn "Python 3 не найден. Установи python3 (или запусти ./setup.sh)."
    exit 1
fi

# --- движок установлен? ---
if [ ! -d server/node_modules/express ]; then
    warn "Зависимости движка не найдены — сначала ./setup.sh"
    exit 1
fi

# --- меню (только если есть терминал) ---
MODE=1
if [ -t 0 ]; then
    echo "=============================================="
    echo "  LocalBox — выбери режим запуска"
    echo "=============================================="
    echo "  [1] Обычный LocalBox (без Додо Ре Ми)"
    echo "  [2] С поддержкой Додо Ре Ми (рендер выступления)"
    echo
    while true; do
        printf "Введи 1 или 2 и нажми Enter: "
        read -r MODE
        [ "$MODE" = "1" ] || [ "$MODE" = "2" ] && break
        echo "  Не понял ввод — попробуй ещё раз."
    done
fi

if [ "$MODE" = "2" ]; then
    say "Проверка файлов для Додо Ре Ми"
    export LOCALBOX_DODO=1
    # ffmpeg — обязателен для рендера
    if command -v ffmpeg >/dev/null 2>&1; then
        ok "ffmpeg найден."
    else
        warn "ffmpeg НЕ найден — рендер выступления НЕ соберётся. Поставь: ./setup.sh (или пакетным менеджером)."
    fi
    # бэкинги песен — для музыки
    if ls server/render/nopus-opus/songs/*/backing*.ogg >/dev/null 2>&1; then
        ok "Бэкинги песен найдены — выступление будет с музыкой."
    else
        warn "Бэкинги песен НЕ найдены — выступление соберётся БЕЗ музыки (только ноты игрока)."
        echo "      Куда класть (backing.ogg каждой песни):"
        echo "          server/render/nopus-opus/songs/<slug>/backing.ogg"
        echo "      Взять из установленной игры: .../games/NopusOpus/songs/<slug>/"
        echo "      Сэмплы инструментов докачаются сами при первом рендере."
    fi
    [ -t 0 ] && { printf "\nНажми Enter, чтобы запустить с Додо Ре Ми (или Ctrl+C — отмена)…"; read -r _; }
else
    unset LOCALBOX_DODO
fi

say "Запуск лаунчера"
echo "  GUI: укажи адрес → «Сертификат» → «Запустить». (Сервер по сети: ./start-server.sh -ip=АЙПИ)"
cd launcher
"$PY" localbox_launcher.py "$@"

echo
echo "== Сервер остановлен =="
[ -t 0 ] && { printf "Нажми Enter, чтобы закрыть…"; read -r _; }
