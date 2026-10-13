#!/usr/bin/env bash
# LocalBox: выбор GUI, Додо Ре Ми и уже установленных голосов.
set -u
cd "$(cd "$(dirname "$0")" && pwd)" || exit 1
LOCALBOX_PYTHON=""
for candidate in runtime/python/bin/python3 runtime/python/python.exe runtime/bin/python3; do
    if [ -x "$candidate" ]; then LOCALBOX_PYTHON="$PWD/$candidate"; break; fi
done
if [ -z "$LOCALBOX_PYTHON" ]; then
    if command -v python3 >/dev/null 2>&1; then LOCALBOX_PYTHON=python3
    elif command -v python >/dev/null 2>&1; then LOCALBOX_PYTHON=python
    else printf '%s\n' 'Python не найден. Запустите ./setup.sh.'; exit 1
    fi
fi
# start.py сохраняет код завершения лаунчера, аргументы позволяют запуск без меню.
"$LOCALBOX_PYTHON" launcher/start.py "$@"
exit "$?"
