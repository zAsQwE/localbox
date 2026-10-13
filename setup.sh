#!/usr/bin/env bash
# Linux/macOS: графический мастер; без дисплея — те же вопросы текстом.
set -euo pipefail
LOCALBOX_SOURCE="$(cd "$(dirname "$0")" && pwd)"
mode=auto
target="${LOCALBOX_BUNDLE_SOURCE:+$HOME/.local/share/localbox}"
target="${target:-$LOCALBOX_SOURCE}"
runtime_dir=""
tts=""
voices="ru_RU-denis-medium"
game=""
cheat_content=""
cheat_configured=0
dodo=0
russian=0
run_after=0
noninteractive=0
usage() {
    printf '%s\n' 'setup.sh [--gui|--console] [--target ПАПКА] [--runtime ПАПКА] [--tts none|piper|silero|both|espeak]' \
        '         [--voices ru_RU-denis-medium,ru_RU-irina-medium] [--game ПАПКА_JACKBOX10] [--cheat-content ПАПКА_ИГР] [--dodo] [--ru] [--run]' \
        'Установка с параметрами --target или --tts не задаёт вопросов.'
}
while [ "$#" -gt 0 ]; do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --gui) mode=gui ;;
        --console) mode=console ;;
        --target|--runtime|--tts|--voices|--game|--cheat-content)
            if [ "$#" -lt 2 ]; then usage >&2; exit 2; fi
            key="$1"; shift
            case "$key" in
                --target) target="$1"; noninteractive=1 ;;
                --runtime) runtime_dir="$1" ;;
                --tts) tts="$1"; noninteractive=1 ;;
                --voices) voices="$1" ;;
                --game) game="$1"; dodo=1 ;;
                --cheat-content) cheat_content="$1"; cheat_configured=1 ;;
            esac ;;
        --dodo) dodo=1 ;;
        --ru) russian=1 ;;
        --run) run_after=1 ;;
        *) printf 'Неизвестный аргумент: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done
if { [ "$noninteractive" = 0 ] || [ "$mode" = gui ]; } && [ "$mode" != console ] && { [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; }; then
    bash "$LOCALBOX_SOURCE/installer/linux-deps.sh" --gui
    args=(--target "$target")
    [ -z "$runtime_dir" ] || args+=(--runtime "$runtime_dir")
    [ -z "$game" ] || args+=(--game "$game")
    [ "$cheat_configured" = 0 ] || args+=(--cheat-content "$cheat_content")
    [ -z "$tts" ] || args+=(--tts "$tts")
    args+=(--voices "$voices")
    [ "$russian" = 0 ] || args+=(--ru)
    [ "$dodo" = 0 ] || args+=(--dodo)
    [ "$run_after" = 0 ] || args+=(--run)
    exec python3 "$LOCALBOX_SOURCE/installer/wizard.py" "${args[@]}"
fi
if [ "$mode" = gui ]; then printf '%s\n' 'Нет графической сессии. Используйте --console.' >&2; exit 1; fi
if [ "$noninteractive" = 0 ] && [ -t 0 ]; then
    printf '\nLocalBox — установка\n'
    read -r -p "Папка приложения [$target]: " answer; target="${answer:-$target}"
    read -r -p "Папка зависимостей и TTS [$target/runtime]: " runtime_dir
    printf '\nTTS: [1] Piper  [2] Silero  [3] Оба  [4] eSpeak  [5] Без озвучки\n'
    while true; do
        read -r -p 'Ваш выбор [1]: ' answer
        case "${answer:-1}" in 1) tts=piper; break;; 2) tts=silero; break;; 3) tts=both; break;; 4) tts=espeak; break;; 5) tts=none; break;; esac
    done
    if [ "$tts" = piper ] || [ "$tts" = both ]; then
        printf '%s\n' 'Голоса Piper: [1] Денис [2] Дмитрий [3] Ирина [4] Руслан'
        while true; do
            read -r -p 'Номера через запятую [1]: ' answer
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
    read -r -p 'Включить Додо Ре Ми? [y/N]: ' answer
    case "$answer" in y|Y|д|Д) dodo=1; read -r -p 'Папка Jackbox Party Pack 10 (Enter — без импорта музыки): ' game;; esac
    read -r -p 'Папка с играми для читов (Enter — поиск в Steam): ' cheat_content
    cheat_configured=1
    read -r -p 'Скачать русский веб-клиент? [y/N]: ' answer
    case "$answer" in y|Y|д|Д) russian=1;; esac
fi
bash "$LOCALBOX_SOURCE/installer/linux-deps.sh" --python
args=(--target "$target" --tts "${tts:-piper}" --voices "$voices")
[ -z "$runtime_dir" ] || args+=(--runtime "$runtime_dir")
[ -z "$game" ] || args+=(--game "$game")
[ "$cheat_configured" = 0 ] || args+=(--cheat-content "$cheat_content")
[ "$russian" = 0 ] || args+=(--ru)
[ "$dodo" = 0 ] || args+=(--dodo)
python3 "$LOCALBOX_SOURCE/installer/install.py" "${args[@]}"
if [ "$run_after" = 1 ]; then exec bash "$target/start-server.sh"; fi
