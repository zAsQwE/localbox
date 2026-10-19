#!/usr/bin/env bash
# Системные зависимости; приложение и venv размещает Python-мастер.
set -euo pipefail
mode="${1:---full}"
tts="${2:-piper}"
source "$(dirname "$0")/find-node.sh"
source "$(dirname "$0")/linux-node.sh"
source "$(dirname "$0")/linux-admin.sh"
export LOCALBOX_SOURCE="${LOCALBOX_SOURCE:-$(cd "$(dirname "$0")/.." && pwd)}"
localbox_use_node || true
packages=()
pm=""
for candidate in apt-get pacman dnf zypper brew; do
    if command -v "$candidate" >/dev/null 2>&1; then pm="$candidate"; break; fi
done
add() {
    case "$pm" in
        apt-get) packages+=( $1 ) ;; pacman) packages+=( $2 ) ;;
        dnf) packages+=( $3 ) ;; zypper) packages+=( $4 ) ;; brew) packages+=( $5 ) ;;
    esac
}
python3 -c 'import sys; assert sys.version_info >= (3,10)' >/dev/null 2>&1 || add python3 python python3 python3 python
if [ "$mode" = "--gui" ] || [ "$mode" = "--full" ]; then
    python3 -c 'import tkinter' >/dev/null 2>&1 || add python3-tk tk python3-tkinter python3-tk python-tk
fi
if [ "$mode" = "--full" ]; then
    if ! localbox_use_node && ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
        add curl curl curl curl curl
    fi
    command -v git >/dev/null 2>&1 || add git git git git git
    command -v ffmpeg >/dev/null 2>&1 || add ffmpeg ffmpeg ffmpeg ffmpeg ffmpeg
    command -v openssl >/dev/null 2>&1 || add openssl openssl openssl openssl openssl
    command -v setcap >/dev/null 2>&1 || add libcap2-bin libcap libcap libcap ' '
    if [ "$tts" != "none" ] && [ "$tts" != "espeak" ]; then
        python3 -c 'import venv, ensurepip' >/dev/null 2>&1 || add 'python3-venv python3-pip' python python3-pip python3-pip python
    fi
    if [ "$tts" = "espeak" ]; then
        command -v espeak-ng >/dev/null 2>&1 || add espeak-ng espeak-ng espeak-ng espeak-ng espeak
    fi
fi
if [ "${#packages[@]}" -gt 0 ]; then
    if ! localbox_install_packages "${packages[@]}"; then
        printf '%s\n' 'Пакетный менеджер не завершил установку. Проверяю, какие зависимости доступны.' >&2
    fi
fi
if [ "$mode" = "--full" ] && ! localbox_use_node; then
    node_packages=()
    case "$pm" in
        apt-get|pacman|dnf|zypper) node_packages=(nodejs npm) ;;
        brew) node_packages=(node) ;;
    esac
    if [ "${#node_packages[@]}" -gt 0 ]; then
        if ! localbox_install_packages "${node_packages[@]}"; then
            printf '%s\n' 'Не удалось установить Node.js через пакетный менеджер. Повторный поиск, затем официальный способ установки.' >&2
        fi
    fi
    # Also handles packages that installed an obsolete Node or a broken npm.
    localbox_ensure_node
fi
python3 -c 'import sys; assert sys.version_info >= (3,10), "Нужен Python 3.10+"'
if [ "$mode" = "--gui" ]; then python3 -c 'import tkinter'; fi
if [ "$mode" = "--full" ]; then
    localbox_ensure_node
    node -e 'if (+process.versions.node.split(".")[0] < 18) throw Error("Нужен Node.js 18+")'
    python3 -c 'import tkinter' || { printf "%s\n" "Не найден Tk для лаунчера. Установите пакет Python Tk своей системы." >&2; exit 1; }
    npm --version
    for tool in npm git ffmpeg openssl; do
        command -v "$tool" >/dev/null || { printf "Не найдена зависимость: %s. Установка системных пакетов не завершилась.\n" "$tool" >&2; exit 1; }
    done
    # Propagate paths to the Python wizard, whose PATH cannot be changed by this child.
    python3 - "$LOCALBOX_SOURCE/launcher/install-paths.json" "$(command -v node)" "$(command -v npm)" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
# fnm's /run/user/.../fnm_multishells symlink disappears after logout.
# Resolve its bin directory, retaining npm's launcher rather than resolving npm
# into lib/node_modules/npm/bin (which does not contain the Node executable).
def stable_tool(filename):
    file = pathlib.Path(filename)
    return str(file.parent.resolve() / file.name)
data.update(node=stable_tool(sys.argv[2]), npm=stable_tool(sys.argv[3]))
path.parent.mkdir(parents=True, exist_ok=True)
temporary = path.with_suffix('.json.tmp')
temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
temporary.replace(path)
PY
fi
