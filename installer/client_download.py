"""Install the web client from local files or a GitHub snapshot, without git clone."""

if __package__:
    from .i18n import tr
else:
    from i18n import tr

from pathlib import Path
import argparse
import json
import re
import shutil
import tempfile
import time
import urllib.request
import zipfile

from client_ru import client_entries
from update import update_lock

URL = 'https://codeload.github.com/DdejjCAT/jackbox.tv/zip/refs/heads/main'
MAX_SIZE = 4 * 1024**3
MAX_SECONDS = 30 * 60
IGNORED = {'.git', '.hg', '.svn', '__pycache__', 'node_modules', '.DS_Store', '__MACOSX'}


def download_archive(destination, log=print, url=URL):
    destination = Path(destination)
    partial = destination.with_suffix('.zip.part')
    for attempt in range(1, 4):
        size, started, reported = 0, time.monotonic(), 0
        log(tr('Веб-клиент: загрузка ZIP с GitHub, попытка {0}/3…', attempt))
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'LocalBox-Setup', 'Accept-Encoding': 'identity'})
            with urllib.request.urlopen(request, timeout=20) as response, partial.open('wb') as output:
                total = int(response.headers.get('Content-Length', 0))
                if total > MAX_SIZE:
                    raise ValueError(tr('Архив веб-клиента слишком большой.'))
                # read1 reports received data promptly, even on slow connections.
                read = getattr(response, 'read1', response.read)
                while chunk := read(256 * 1024):
                    size += len(chunk)
                    now = time.monotonic()
                    if size > MAX_SIZE:
                        raise ValueError(tr('Архив веб-клиента слишком большой.'))
                    if now - started > MAX_SECONDS:
                        raise TimeoutError(tr('Превышено время загрузки веб-клиента.'))
                    output.write(chunk)
                    if now - reported >= 2:
                        progress = f'{size * 100 // total}% — ' if total else ''
                        log(tr('Веб-клиент: {0}{1:.1f} МБ, {2:.1f} МБ/с', progress, size / 1024 ** 2, size / 1024 ** 2 / max(now - started, 0.01)))
                        reported = now
            if not size or (total and size != total):
                raise OSError(tr('Архив веб-клиента скачан не полностью.'))
            partial.replace(destination)
            log(tr('Веб-клиент: ZIP скачан ({0:.1f} МБ).', size / 1024 ** 2))
            return destination
        except OSError as error:
            log(tr('Загрузка веб-клиента прервалась: {0}', error))
            if attempt == 3:
                raise RuntimeError(tr('Не удалось скачать веб-клиент за 3 попытки. Повторите установку или используйте готовую папку client.')) from error
        finally:
            partial.unlink(missing_ok=True)


def install_client(target, runtime_dir=None, source=None, log=print):
    target = Path(target).resolve()
    client = target / 'client'
    if (client / 'main').is_dir():
        log(tr('Использую уже установленный веб-клиент.'))
        return client
    if client.exists():
        raise ValueError(tr('Папка client неполная. Переместите её и повторите установку.'))
    local = Path(source).resolve() / 'client' if source else None
    with tempfile.TemporaryDirectory(prefix='localbox-client-', dir=target) as temp:
        stage = Path(temp) / 'client'
        if local and (local / 'main').is_dir() and (local / 'index.html').is_file():
            log(tr('Использую готовый веб-клиент: {0}', local))
            stage.mkdir()
            count = 0
            for file in local.rglob('*'):
                relative = file.relative_to(local)
                if any(part in IGNORED for part in relative.parts):
                    continue
                destination = stage / relative
                if file.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                if not file.is_file():
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, destination)
                count += 1
                if count % 500 == 0:
                    log(tr('Веб-клиент: скопировано {0} файлов…', count))
        else:
            cache = Path(runtime_dir or target / 'runtime') / 'downloads'
            cache.mkdir(parents=True, exist_ok=True)
            archive = cache / 'jackbox-client.zip'
            if not archive.is_file():
                download_archive(archive, log)
            else:
                log(tr('Использую ранее скачанный ZIP веб-клиента.'))
            try:
                entries = client_entries(archive, label='client.zip')
                stage.mkdir()
                log(tr('Распаковываю веб-клиент: {0} файлов…', len(entries)))
                with zipfile.ZipFile(archive) as package:
                    for count, (name, entry) in enumerate(entries.items(), 1):
                        destination = stage / name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with package.open(entry) as incoming, destination.open('wb') as output:
                            shutil.copyfileobj(incoming, output)
                        if count % 500 == 0:
                            log(tr('Веб-клиент: распаковано {0}/{1} файлов…', count, len(entries)))
            except (zipfile.BadZipFile, ValueError) as error:
                archive.unlink(missing_ok=True)
                raise ValueError(tr('Архив веб-клиента повреждён или имеет неверную структуру: {0}', error)) from error
        stage.replace(client)
    log(tr('Веб-клиент установлен.'))
    return client


def update_client(target, log=print):
    target = Path(target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    with update_lock(target):
        return _update_client(target, log)


def _update_client(target, log=print):
    """Replace only the English controller, after validating a complete GitHub snapshot."""
    target = Path(target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    client = target / 'client'
    if client.is_symlink():
        raise ValueError(tr('Папка client не должна быть символической ссылкой.'))
    request = urllib.request.Request('https://api.github.com/repos/DdejjCAT/jackbox.tv/commits/main',
                                     headers={'User-Agent': 'LocalBox-Setup', 'Accept': 'application/vnd.github+json'})
    log(tr('Проверяю обновлённый client на GitHub…'))
    with urllib.request.urlopen(request, timeout=25) as response:
        revision = json.loads(response.read(2 * 1024**2 + 1)).get('sha', '')
    if not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise ValueError(tr('GitHub не вернул версию веб-клиента.'))
    marker = client / '.localbox-github.json'
    log(tr('Веб-клиент: версия {0}', revision[:12]))
    with tempfile.TemporaryDirectory(prefix='localbox-client-update-', dir=target) as temp:
        work = Path(temp)
        archive = work / 'client.zip'
        download_archive(archive, log, url=f'https://codeload.github.com/DdejjCAT/jackbox.tv/zip/{revision}')
        entries = client_entries(archive, label='client.zip')
        stage = work / 'client'
        stage.mkdir()
        log(tr('Проверяю и распаковываю client: {0} файлов…', len(entries)))
        with zipfile.ZipFile(archive) as package:
            for number, (name, entry) in enumerate(entries.items(), 1):
                destination = stage / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with package.open(entry) as source, destination.open('wb') as output:
                    shutil.copyfileobj(source, output)
                if number % 500 == 0:
                    log(tr('Веб-клиент: распаковано {0}/{1} файлов…', number, len(entries)))
        (stage / marker.name).write_text(json.dumps({'repository': 'DdejjCAT/jackbox.tv', 'revision': revision}), encoding='utf-8')
        backup = work / 'previous-client'
        if client.exists():
            client.replace(backup)
        try:
            stage.replace(client)
        except BaseException:
            if backup.exists():
                backup.replace(client)
            raise
    log(tr('Клиент обновлён. Можно продолжить вход в комнату.'))
    return client


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=tr('Обновить client с GitHub, сохранив client-ru и настройки LocalBox.'))
    parser.add_argument('--target', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--update', action='store_true')
    args = parser.parse_args()
    if not args.update:
        parser.error(tr('Укажите --update для загрузки актуального client.'))
    try:
        update_client(args.target, log=lambda message: print(message, flush=True))
    except Exception as failure:
        parser.exit(1, tr('Не удалось обновить client: {0}\n', failure))
