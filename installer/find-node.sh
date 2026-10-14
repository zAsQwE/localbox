# Source this file so an existing Node.js outside PATH is also available to the wizard.
localbox_use_node() {
    if command -v node >/dev/null 2>&1 && node -e 'process.exit(+process.versions.node.split(".")[0] < 18)' >/dev/null 2>&1 && npm --version >/dev/null 2>&1; then
        return 0
    fi
    local candidate saved=""
    if command -v python3 >/dev/null 2>&1 && [ -f "${LOCALBOX_SOURCE:-.}/launcher/install-paths.json" ]; then
        saved=$(python3 - "${LOCALBOX_SOURCE:-.}/launcher/install-paths.json" <<'PY'
import json, sys
try:
    print(json.load(open(sys.argv[1])).get('node', ''))
except (OSError, ValueError):
    pass
PY
)
    fi
    local candidates=("$saved" "${NVM_SYMLINK:-}/node" "$HOME/.volta/bin/node" /usr/local/bin/node /opt/homebrew/bin/node)
    while IFS= read -r candidate; do candidates+=("$candidate"); done < <(compgen -G "$HOME/.nvm/versions/node/*/bin/node" | sort -Vr)
    while IFS= read -r candidate; do candidates+=("$candidate"); done < <(compgen -G "$HOME/.local/share/mise/installs/node/*/bin/node" | sort -Vr)
    for candidate in "${candidates[@]}"; do
        if [ -x "$candidate" ] && "$candidate" -e 'process.exit(+process.versions.node.split(".")[0] < 18)' >/dev/null 2>&1 && [ -x "$(dirname "$candidate")/npm" ]; then
            if PATH="$(dirname "$candidate"):$PATH" "$(dirname "$candidate")/npm" --version >/dev/null 2>&1; then
                export PATH="$(dirname "$candidate"):$PATH"
                return 0
            fi
        fi
    done
    return 1
}
