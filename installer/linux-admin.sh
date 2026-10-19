# Elevate package-manager commands, keeping downloads and the wizard as the user.
localbox_run_admin() {
    if [ "$(id -u)" = 0 ] || [ "$1" = brew ]; then "$@"; return $?; fi
    local program status
    program=$(command -v "$1") || return 1
    shift
    printf '%s\n' 'Для установки системных пакетов введите пароль администратора (root или пользователя с sudo).'
    if { [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; } && command -v pkexec >/dev/null 2>&1; then
        if pkexec "$program" "$@"; then return 0; else status=$?; fi
        # 126 means the user cancelled; 127 means no working authentication agent.
        [ "$status" = 127 ] || return "$status"
        printf '%s\n' 'Системное окно авторизации недоступно. Пробую запрос пароля через sudo.' >&2
    fi
    if command -v sudo >/dev/null 2>&1; then
        if [ -t 0 ]; then
            sudo -p 'Пароль администратора для установки LocalBox: ' "$program" "$@"
        elif [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
            SUDO_ASKPASS="$(dirname "${BASH_SOURCE[0]}")/askpass.sh" sudo -A \
                -p 'Пароль администратора для установки LocalBox:' "$program" "$@"
        else
            printf '%s\n' 'Для ввода пароля запустите setup из терминала.' >&2
            return 1
        fi
    elif [ -t 0 ] && command -v su >/dev/null 2>&1; then
        local command_text
        printf -v command_text '%q ' "$program" "$@"
        su -s /bin/bash root -c "$command_text"
    else
        printf '%s\n' 'Для установки системных пакетов нужен sudo, pkexec или su в терминале.' >&2
        return 1
    fi
}

localbox_install_packages() {
    # Check again immediately before changing system Node packages. Other callers
    # may have queued them before finding a working user installation (e.g. fnm).
    local package
    local filtered=()
    local reuse_node=0
    if declare -F localbox_use_node >/dev/null && localbox_use_node; then reuse_node=1; fi
    for package in "$@"; do
        case "$package" in
            node|nodejs|npm)
                if [ "$reuse_node" = 1 ]; then continue; fi ;;
        esac
        filtered+=("$package")
    done
    set -- "${filtered[@]}"
    [ "$#" -gt 0 ] || return 0
    printf 'Системные пакеты (%s): %s\n' "$pm" "$*"
    case "$pm" in
        apt-get) localbox_run_admin apt-get update && localbox_run_admin apt-get install -y "$@" ;;
        pacman) localbox_run_admin pacman -S --needed --noconfirm "$@" ;;
        dnf) localbox_run_admin dnf install -y "$@" ;;
        zypper) localbox_run_admin zypper --non-interactive install "$@" ;;
        brew) localbox_run_admin brew install "$@" ;;
        *) printf '%s\n' 'Поддерживаемый пакетный менеджер не найден.' >&2; return 1 ;;
    esac
}
