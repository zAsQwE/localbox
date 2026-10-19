"""Resolve the nvm download referenced by Node.js's official installation guide."""

import html
import re
import sys
import urllib.request

GUIDE = 'https://nodejs.org/en/download'
FALLBACK = 'https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.8/install.sh'
PATTERN = r'https://raw\.githubusercontent\.com/nvm-sh/nvm/v(\d+\.\d+\.\d+)/install\.sh'


def installer_url(log=print):
    try:
        request = urllib.request.Request(GUIDE, headers={'User-Agent': 'LocalBox-Setup'})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('страница слишком большая')
        versions = re.findall(PATTERN, html.unescape(data.decode('utf-8')))
        if not versions:
            raise ValueError('в инструкции не найдена ссылка на nvm')
        version = max(versions, key=lambda v: tuple(map(int, v.split('.'))))
        return f'https://raw.githubusercontent.com/nvm-sh/nvm/v{version}/install.sh'
    except (OSError, ValueError) as error:
        log(f'Не удалось прочитать {GUIDE}: {error}. Использую сохранённую инструкцию nvm.')
        return FALLBACK


if __name__ == '__main__':
    print(installer_url(log=lambda message: print(message, file=sys.stderr)))
