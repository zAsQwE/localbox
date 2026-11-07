#!/usr/bin/env bash
# Linux/macOS: графический мастер; без дисплея — те же вопросы текстом.
set -euo pipefail
LOCALBOX_SOURCE="$(cd "$(dirname "$0")" && pwd)"
source "$LOCALBOX_SOURCE/installer/i18n.sh"
language_explicit=0
language_next=0
language_interactive=1
for argument in "$@"; do
    case "$argument" in --target|--tts|--help|-h) language_interactive=0;; esac
    if [ "$language_next" = 1 ]; then
        case "$argument" in ru|en) export LOCALBOX_LANGUAGE="$argument";; *) printf '%s\n' 'Language must be ru or en' >&2; exit 2;; esac
        language_next=0
        language_explicit=1
    elif [ "$argument" = --language ]; then language_next=1; fi
done
if [ "$language_next" = 1 ]; then printf '%s\n' 'Missing --language ru|en' >&2; exit 2; fi
# Headless installations choose before release/dependency downloads as well.
if [ "$language_explicit" = 0 ] && [ "$language_interactive" = 1 ] && [ -t 0 ] && { { [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; } || [[ " $* " == *" --console "* ]]; }; then
    while true; do
        read -r -p 'Language / Язык: [1] Русский  [2] English (Enter = system): ' language_answer
        case "$language_answer" in 1|ru) LOCALBOX_LANGUAGE=ru; break;; 2|en) LOCALBOX_LANGUAGE=en; break;; '') break;; esac
    done
    language_explicit=1
fi
use_release=0
show_help=0
[ -z "${LOCALBOX_BUNDLE_SOURCE:-}" ] || use_release=1
for argument in "$@"; do
    case "$argument" in
        --latest) use_release=1 ;;
        --local) use_release=0 ;;
        --help|-h) show_help=1 ;;
    esac
done
[ "$show_help" = 0 ] || use_release=0
if [ "$use_release" = 1 ] && [ "${LOCALBOX_RELEASE_READY:-0}" != 1 ]; then
    bash "$LOCALBOX_SOURCE/installer/linux-deps.sh" --python
    localbox_release_work=$(mktemp -d "${TMPDIR:-/tmp}/localbox-release-setup.XXXXXX")
    trap 'rm -rf "$localbox_release_work"' EXIT HUP INT TERM
    python3 "$LOCALBOX_SOURCE/installer/release.py" --destination "$localbox_release_work"
    export LOCALBOX_BUNDLE_SOURCE="$localbox_release_work/payload"
    export LOCALBOX_RELEASE_TAG="$(cat "$localbox_release_work/release-tag.txt")"
    export LOCALBOX_RELEASE_READY=1
    bash "$LOCALBOX_BUNDLE_SOURCE/setup.sh" "$@"
    exit $?
fi
source "$LOCALBOX_SOURCE/installer/find-node.sh"
localbox_use_node || true
mode=auto
target="${LOCALBOX_BUNDLE_SOURCE:+$HOME/.local/share/localbox}"
target="${target:-$LOCALBOX_SOURCE}"
runtime_dir=""
tts=""
voices="ru_RU-denis-medium"
game=""
cheat_content=""
tmp3_game=""
cheat_configured=0
dodo=0
trust=1
russian=0
run_after=0
noninteractive=0
usage() {
    printf '%s\n' 'setup.sh [--latest|--local] [--language ru|en] [--gui|--console] [--target DIR] [--runtime DIR] [--tts none|piper|silero|both|espeak]' \
        '         [--voices ru_RU-denis-medium,ru_RU-irina-medium] [--game JACKBOX10_DIR] [--cheat-content GAMES_DIR] [--tmp3-game TMP3_DIR] [--dodo] [--no-trust] [--ru] [--run]' \
        "$(localbox_text 'Установка с параметрами --target или --tts не задаёт вопросов.' 'Options: --language ru|en. --target or --tts runs without questions.')"
}
while [ "$#" -gt 0 ]; do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --gui) mode=gui ;;
        --console) mode=console ;;
        --latest|--local) ;; # Already handled before starting the selected release.
        --target|--runtime|--tts|--voices|--game|--cheat-content|--tmp3-game|--language)
            if [ "$#" -lt 2 ]; then usage >&2; exit 2; fi
            key="$1"; shift
            case "$key" in
                --language) ;; # Validated before downloading the selected release.
                --target) target="$1"; noninteractive=1 ;;
                --runtime) runtime_dir="$1" ;;
                --tts) tts="$1"; noninteractive=1 ;;
                --voices) voices="$1" ;;
                --tmp3-game) tmp3_game="$1" ;;
                --game) game="$1"; dodo=1 ;;
                --cheat-content) cheat_content="$1"; cheat_configured=1 ;;
            esac ;;
        --dodo) dodo=1 ;;
        --no-trust) trust=0 ;;
        --ru) russian=1 ;;
        --run) run_after=1 ;;
        *) localbox_text 'Неизвестный аргумент: %s\n' 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done
if { [ "$noninteractive" = 0 ] || [ "$mode" = gui ]; } && [ "$mode" != console ] && { [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; }; then
    bash "$LOCALBOX_SOURCE/installer/linux-deps.sh" --gui
    args=(--target "$target")
    [ -z "$runtime_dir" ] || args+=(--runtime "$runtime_dir")
    [ -z "$tmp3_game" ] || args+=(--tmp3-game "$tmp3_game")
    [ -z "$game" ] || args+=(--game "$game")
    [ "$cheat_configured" = 0 ] || args+=(--cheat-content "$cheat_content")
    [ -z "$tts" ] || args+=(--tts "$tts")
    args+=(--voices "$voices")
    [ "$language_explicit" = 0 ] || args+=(--language "$LOCALBOX_LANGUAGE")
    [ "$russian" = 0 ] || args+=(--ru)
    [ "$dodo" = 0 ] || args+=(--dodo)
    [ "$trust" = 1 ] || args+=(--no-trust)
    [ "$run_after" = 0 ] || args+=(--run)
    exec python3 "$LOCALBOX_SOURCE/installer/wizard.py" "${args[@]}"
fi
if [ "$mode" = gui ]; then printf '%s\n' "$(localbox_text 'Нет графической сессии. Используйте --console.' 'No desktop session. Use --console.')" >&2; exit 1; fi
if [ "$noninteractive" = 0 ] && [ -t 0 ]; then
    localbox_text '\nLocalBox — установка\n' '\nLocalBox — installation\n'
    read -r -p "$(localbox_text 'Папка приложения [%s]: ' 'Application folder [%s]: ' "$target")" answer; target="${answer:-$target}"
    read -r -p "$(localbox_text 'Папка зависимостей и TTS [%s/runtime]: ' 'Dependencies and TTS folder [%s/runtime]: ' "$target")" runtime_dir
    localbox_text '\nTTS: [1] Piper  [2] Silero  [3] Оба  [4] eSpeak  [5] Без озвучки\n' '\nTTS: [1] Piper  [2] Silero  [3] Both  [4] eSpeak  [5] No speech\n'
    while true; do
        read -r -p "$(localbox_text 'Ваш выбор [1]: ' 'Your choice [1]: ')" answer
        case "${answer:-1}" in 1) tts=piper; break;; 2) tts=silero; break;; 3) tts=both; break;; 4) tts=espeak; break;; 5) tts=none; break;; esac
    done
    if [ "$tts" = piper ] || [ "$tts" = both ]; then
        printf '%s\n' "$(localbox_text 'Голоса Piper: [1] Денис [2] Дмитрий [3] Ирина [4] Руслан' 'Piper voices (Russian): [1] Denis [2] Dmitri [3] Irina [4] Ruslan')"
        while true; do
            read -r -p "$(localbox_text 'Номера через запятую [1]: ' 'Comma-separated numbers [1]: ')" answer
            IFS=, read -ra numbers <<< "${answer:-1}"
            selected=(); invalid=0
            for number in "${numbers[@]}"; do
                case "$number" in
                    1) selected+=(ru_RU-denis-medium);; 2) selected+=(ru_RU-dmitri-medium);;
                    3) selected+=(ru_RU-irina-medium);; 4) selected+=(ru_RU-ruslan-medium);; *) invalid=1;;
                esac
            done
            if [ "$invalid" = 0 ]; then voices="$(IFS=,; echo "${selected[*]}")"; break; fi
        done
    fi
    read -r -p "$(localbox_text 'Включить Додо Ре Ми? [y/N]: ' 'Enable Dodo Re Mi? [y/N]: ')" answer
    case "$answer" in y|Y|д|Д) dodo=1; read -r -p "$(localbox_text 'Папка Jackbox Party Pack 10 (Enter — без импорта музыки): ' 'Jackbox Party Pack 10 folder (Enter — no music import): ')" game;; esac
    read -r -p "$(localbox_text 'Папка Trivia Murder Party 3 (Enter — без патча): ' 'Trivia Murder Party 3 folder (Enter — no patch): ')" tmp3_game
    read -r -p "$(localbox_text 'Папка с играми для читов (Enter — поиск в Steam): ' 'Game content for cheats (Enter — search Steam): ')" cheat_content
    cheat_configured=1
    if [ "$LOCALBOX_LANGUAGE" = ru ]; then
        read -r -p 'Скачать русский веб-клиент? [y/N]: ' answer
        case "$answer" in y|Y|д|Д) russian=1;; esac
    fi
fi
bash "$LOCALBOX_SOURCE/installer/linux-deps.sh" --python
args=(--target "$target" --tts "${tts:-piper}" --voices "$voices")
args+=(--language "$LOCALBOX_LANGUAGE")
[ -z "$runtime_dir" ] || args+=(--runtime "$runtime_dir")
[ -z "$tmp3_game" ] || args+=(--tmp3-game "$tmp3_game")
[ -z "$game" ] || args+=(--game "$game")
[ "$cheat_configured" = 0 ] || args+=(--cheat-content "$cheat_content")
[ "$russian" = 0 ] || args+=(--ru)
[ "$dodo" = 0 ] || args+=(--dodo)
python3 "$LOCALBOX_SOURCE/installer/install.py" "${args[@]}"
if [ "$run_after" = 1 ]; then exec bash "$target/start-server.sh"; fi
