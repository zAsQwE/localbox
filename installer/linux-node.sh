# Sourced by linux-deps.sh; follows https://nodejs.org/en/download (nvm).
localbox_install_nvm_node() (
    set +u
    export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
    if [ ! -s "$NVM_DIR/nvm.sh" ]; then
        localbox_nvm_script=$(mktemp) || return 1
        trap 'rm -f "$localbox_nvm_script"' EXIT
        printf '%s\n' 'Читаю инструкцию установки Node.js: https://nodejs.org/en/download'
        localbox_nvm_url=$(python3 "$(dirname "${BASH_SOURCE[0]}")/node_recipe.py") || return 1
        if command -v curl >/dev/null 2>&1; then
            curl -fSL --retry 2 --connect-timeout 10 --max-time 120 "$localbox_nvm_url" -o "$localbox_nvm_script" || return 1
        elif command -v wget >/dev/null 2>&1; then
            wget --timeout=30 --tries=3 -O "$localbox_nvm_script" "$localbox_nvm_url" || return 1
        else
            python3 - "$localbox_nvm_url" "$localbox_nvm_script" <<'PY' || return 1
import sys, urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=30) as response:
    data = response.read()
if not data:
    raise RuntimeError('Пустой установщик nvm')
with open(sys.argv[2], 'wb') as file:
    file.write(data)
PY
        fi
        # LocalBox saves the selected Node path; shell profiles need no changes.
        PROFILE=/dev/null METHOD=script bash "$localbox_nvm_script" || return 1
    fi
    source "$NVM_DIR/nvm.sh" --no-use || return 1
    nvm install --lts || return 1
)

localbox_ensure_node() {
    if localbox_use_node; then
        printf 'Использую установленные Node.js и npm: %s\n' "$(command -v node)"
        return 0
    fi
    printf '%s\n' 'Node.js 18+ с рабочим npm не найден. Устанавливаю LTS через nvm по инструкции https://nodejs.org/en/download'
    if localbox_install_nvm_node && localbox_use_node; then
        printf 'Node.js и npm готовы: %s\n' "$(command -v node)"
        return 0
    fi
    printf '%s\n' 'Установка Node.js не завершилась. Повторно проверяю систему...'
    if localbox_use_node; then return 0; fi
    printf '%s\n' 'Не удалось установить Node.js и npm. Инструкция: https://nodejs.org/en/download' >&2
    return 1
}
