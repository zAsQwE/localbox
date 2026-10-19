"""Bind Windows npm to the selected Node distribution, without global npm.cmd redirects."""

import os
from pathlib import Path


def invocation(node, npm, npm_cli=None, windows=None):
    windows = os.name == 'nt' if windows is None else windows
    if not windows:
        return [str(npm)]
    if not node:
        raise RuntimeError('Не найден выбранный Node.js. Повторите установку через setup.')
    candidates = [Path(node).parent / 'node_modules/npm/bin/npm-cli.js']
    if npm_cli:
        candidates.insert(0, Path(npm_cli))
    for cli in candidates:
        if cli.is_file():
            return [str(node), str(cli)]
    raise RuntimeError('Не найден npm-cli.js для выбранного Node.js. Повторите установку через setup.')
