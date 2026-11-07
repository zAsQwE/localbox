# Elevate package-manager commands, keeping downloads and the wizard as the user.
source "$(dirname "${BASH_SOURCE[0]}")/i18n.sh"
localbox_run_admin() {
    if [ "$(id -u)" = 0 ] || [ "$1" = brew ]; then "$@"; return $?; fi
    local program status
    program=$(command -v "$1") || return 1
    shift
    printf '%s\n' "$(localbox_text 'Для установки системных пакетов введите пароль администратора (root или пользователя с sudo).' 'Enter the administrator password to install system packages (root or a sudo user).')"
    if { [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; } && command -v pkexec >/dev/null 2>&1; then
        if pkexec "$program" "$@"; then return 0; else status=$?; fi
        # 126 means the user cancelled; 127 means no working authentication agent.
        [ "$status" = 127 ] || return "$status"
        printf '%s\n' "$(localbox_text 'Системное окно авторизации недоступно. Пробую запрос пароля через sudo.' 'System authentication dialog unavailable. Trying a sudo password prompt.')" >&2
    fi
    if command -v sudo >/dev/null 2>&1; then
        if [ -t 0 ]; then
            sudo -p "$(localbox_text 'Пароль администратора для установки LocalBox: ' 'Administrator password to install LocalBox: ')" "$program" "$@"
        elif [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
            SUDO_ASKPASS="$(dirname "${BASH_SOURCE[0]}")/askpass.sh" sudo -A \
                -p "$(localbox_text 'Пароль администратора для установки LocalBox:' 'Administrator password to install LocalBox:')" "$program" "$@"
        else
            printf '%s\n' "$(localbox_text 'Для ввода пароля запустите setup из терминала.' 'Run setup in a terminal to enter the password.')" >&2
            return 1
        fi
    elif [ -t 0 ] && command -v su >/dev/null 2>&1; then
        local command_text
        printf -v command_text '%q ' "$program" "$@"
        su -s /bin/bash root -c "$command_text"
    else
        printf '%s\n' "$(localbox_text 'Для установки системных пакетов нужен sudo, pkexec или su в терминале.' 'Installing system packages requires sudo, pkexec or su in a terminal.')" >&2
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
    localbox_text 'Системные пакеты (%s): %s\n' 'System packages (%s): %s\n' "$pm" "$*"
    case "$pm" in
        apt-get) localbox_run_admin apt-get update && localbox_run_admin apt-get install -y "$@" ;;
        pacman) localbox_run_admin pacman -S --needed --noconfirm "$@" ;;
        dnf) localbox_run_admin dnf install -y "$@" ;;
        zypper) localbox_run_admin zypper --non-interactive install "$@" ;;
        brew) localbox_run_admin brew install "$@" ;;
        *) printf '%s\n' "$(localbox_text 'Поддерживаемый пакетный менеджер не найден.' 'No supported package manager found.')" >&2; return 1 ;;
    esac
}
