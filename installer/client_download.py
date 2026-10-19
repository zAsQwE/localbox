"""Install the web client from local files or a GitHub snapshot, without git clone."""

from pathlib import Path
import shutil
import tempfile
import time
import urllib.request
import zipfile

from client_ru import client_entries

URL = 'https://codeload.github.com/DdejjCAT/jackbox.tv/zip/refs/heads/main'
MAX_SIZE = 4 * 1024**3
MAX_SECONDS = 30 * 60
IGNORED = {'.git', '.hg', '.svn', '__pycache__', 'node_modules', '.DS_Store', '__MACOSX'}


def download_archive(destination, log=print):
    destination = Path(destination)
    partial = destination.with_suffix('.zip.part')
    for attempt in range(1, 4):
        size, started, reported = 0, time.monotonic(), 0
        log(f'Веб-клиент: загрузка ZIP с GitHub, попытка {attempt}/3…')
        try:
            request = urllib.request.Request(URL, headers={'User-Agent': 'LocalBox-Setup', 'Accept-Encoding': 'identity'})
            with urllib.request.urlopen(request, timeout=20) as response, partial.open('wb') as output:
                total = int(response.headers.get('Content-Length', 0))
                if total > MAX_SIZE:
                    raise ValueError('Архив веб-клиента слишком большой.')
                # read1 reports received data promptly, even on slow connections.
                read = getattr(response, 'read1', response.read)
                while chunk := read(256 * 1024):
                    size += len(chunk)
                    now = time.monotonic()
                    if size > MAX_SIZE:
                        raise ValueError('Архив веб-клиента слишком большой.')
                    if now - started > MAX_SECONDS:
                        raise TimeoutError('Превышено время загрузки веб-клиента.')
                    output.write(chunk)
                    if now - reported >= 2:
                        progress = f'{size * 100 // total}% — ' if total else ''
                        log(f'Веб-клиент: {progress}{size / 1024**2:.1f} МБ, {size / 1024**2 / max(now - started, .01):.1f} МБ/с')
                        reported = now
            if not size or (total and size != total):
                raise OSError('Архив веб-клиента скачан не полностью.')
            partial.replace(destination)
            log(f'Веб-клиент: ZIP скачан ({size / 1024**2:.1f} МБ).')
            return destination
        except OSError as error:
            log(f'Загрузка веб-клиента прервалась: {error}')
            if attempt == 3:
                raise RuntimeError('Не удалось скачать веб-клиент за 3 попытки. Повторите установку или используйте готовую папку client.') from error
        finally:
            partial.unlink(missing_ok=True)


def install_client(target, runtime_dir=None, source=None, log=print):
    target = Path(target).resolve()
    client = target / 'client'
    if (client / 'main').is_dir():
        log('Использую уже установленный веб-клиент.')
        return client
    if client.exists():
        raise ValueError('Папка client неполная. Переместите её и повторите установку.')
    local = Path(source).resolve() / 'client' if source else None
    with tempfile.TemporaryDirectory(prefix='localbox-client-', dir=target) as temp:
        stage = Path(temp) / 'client'
        if local and (local / 'main').is_dir() and (local / 'index.html').is_file():
            log(f'Использую готовый веб-клиент: {local}')
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
                    log(f'Веб-клиент: скопировано {count} файлов…')
        else:
            cache = Path(runtime_dir or target / 'runtime') / 'downloads'
            cache.mkdir(parents=True, exist_ok=True)
            archive = cache / 'jackbox-client.zip'
            if not archive.is_file():
                download_archive(archive, log)
            else:
                log('Использую ранее скачанный ZIP веб-клиента.')
            try:
                entries = client_entries(archive, label='client.zip')
                stage.mkdir()
                log(f'Распаковываю веб-клиент: {len(entries)} файлов…')
                with zipfile.ZipFile(archive) as package:
                    for count, (name, entry) in enumerate(entries.items(), 1):
                        destination = stage / name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with package.open(entry) as incoming, destination.open('wb') as output:
                            shutil.copyfileobj(incoming, output)
                        if count % 500 == 0:
                            log(f'Веб-клиент: распаковано {count}/{len(entries)} файлов…')
            except (zipfile.BadZipFile, ValueError) as error:
                archive.unlink(missing_ok=True)
                raise ValueError(f'Архив веб-клиента повреждён или имеет неверную структуру: {error}') from error
        stage.replace(client)
    log('Веб-клиент установлен.')
    return client
