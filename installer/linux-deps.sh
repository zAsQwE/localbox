#!/usr/bin/env bash
# Системные зависимости; приложение и venv размещает Python-мастер.
set -euo pipefail
mode="${1:---full}"
tts="${2:-piper}"
source "$(dirname "$0")/find-node.sh"
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
    if ! command -v node >/dev/null 2>&1 || ! node -e 'process.exit(+process.versions.node.split(".")[0] < 18)' >/dev/null 2>&1; then
        add 'nodejs npm' 'nodejs npm' 'nodejs npm' 'nodejs npm' node
    fi
    command -v npm >/dev/null 2>&1 || add npm npm npm npm node
    if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
        printf 'Использую установленные Node.js и npm: %s\n' "$(command -v node)"
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
    elevate=()
    if [ "$pm" != brew ] && [ "$(id -u)" != 0 ]; then
        if command -v sudo >/dev/null 2>&1; then elevate=(sudo)
        elif command -v pkexec >/dev/null 2>&1; then elevate=(pkexec)
        else printf '%s\n' 'Для системных пакетов нужен sudo или pkexec.' >&2; exit 1
        fi
    fi
    printf 'Системные пакеты (%s): %s\n' "$pm" "${packages[*]}"
    case "$pm" in
        apt-get) "${elevate[@]}" apt-get update; "${elevate[@]}" apt-get install -y "${packages[@]}" ;;
        pacman) "${elevate[@]}" pacman -S --needed --noconfirm "${packages[@]}" ;;
        dnf) "${elevate[@]}" dnf install -y "${packages[@]}" ;;
        zypper) "${elevate[@]}" zypper --non-interactive install "${packages[@]}" ;;
        brew) brew install "${packages[@]}" ;;
        *) printf '%s\n' 'Поддерживаются apt, pacman, dnf, zypper и brew. Установите Python 3, Tk, Node.js, npm, git, ffmpeg, OpenSSL вручную.' >&2; exit 1 ;;
    esac
fi
python3 -c 'import sys; assert sys.version_info >= (3,10), "Нужен Python 3.10+"'
if [ "$mode" = "--gui" ]; then python3 -c 'import tkinter'; fi
if [ "$mode" = "--full" ]; then
    node -e 'if (+process.versions.node.split(".")[0] < 18) throw Error("Нужен Node.js 18+")'
    for tool in npm git ffmpeg openssl; do command -v "$tool" >/dev/null; done
fi
