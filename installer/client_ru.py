"""Download a Russian web client independently of the LocalBox application release."""

if __package__:
    from .i18n import tr
else:
    from i18n import tr

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import time
import urllib.error
import urllib.parse
import zipfile

if __package__:
    from .update import REPOSITORY, asset_url, request, update_lock, update_workspace
else:
    from update import REPOSITORY, asset_url, request, update_lock, update_workspace

ASSET_NAME = "client-ru.zip"
MARKER = ".localbox-release.json"
MAX_DOWNLOAD = 4 * 1024**3
MAX_UNPACKED = 12 * 1024**3
IGNORED = {".git", ".hg", ".svn", "__MACOSX", ".DS_Store"}


def _metadata(url):
    try:
        with request(url) as response:
            data = response.read(8 * 1024 * 1024 + 1)
            link = getattr(response, "headers", {}).get("Link")
        if len(data) > 8 * 1024 * 1024:
            raise ValueError(tr('Слишком большой ответ GitHub.'))
    except urllib.error.HTTPError as error:
        if error.code in (403, 429):
            error.close()
            raise RuntimeError(tr('GitHub ограничил запросы. Повторите проверку позднее.')) from error
        raise
    return json.loads(data), link


def _client_assets(release):
    return [asset for asset in release.get("assets", [])
            if isinstance(asset, dict) and asset.get("name") == ASSET_NAME
            and asset.get("state", "uploaded") == "uploaded"]


def _client_release(tag):
    if tag is not None:
        if not isinstance(tag, str) or not tag.strip():
            raise ValueError(tr('Не указан тег Release русского клиента.'))
        release, _ = _metadata(f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{urllib.parse.quote(tag, safe='')}")
        if not isinstance(release, dict) or release.get("tag_name") != tag:
            raise ValueError(tr('GitHub вернул другой выпуск для русского клиента.'))
        return release
    # LOCALBOX_RELEASE_TAG selects application code, never the client archive.
    # One request covers the normal case; older pages are read only when needed.
    page = 1
    while True:
        releases, link = _metadata(f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=100&page={page}")
        if not isinstance(releases, list):
            raise ValueError(tr('GitHub вернул неверный список Releases.'))
        for release in releases:
            if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
                continue
            if _client_assets(release):
                return release
        has_next = bool(re.search(r'rel="next"', link)) if link is not None else len(releases) == 100
        if not releases or not has_next:
            raise RuntimeError(tr('В опубликованных стабильных Releases LocalBox не найден {0}. Прикрепите архив русского клиента хотя бы к одному Release.', ASSET_NAME))
        page += 1


def release_info(tag=None):
    release = _client_release(tag)
    if not release or release.get("draft") or release.get("prerelease"):
        raise RuntimeError(tr('Нет стабильного Release для русского клиента.'))
    assets = _client_assets(release)
    if len(assets) != 1:
        raise RuntimeError(tr('В Release {0} нет {1}. Прикрепите архив русского клиента к этому выпуску.', release['tag_name'], ASSET_NAME))
    asset = assets[0]
    asset_url(asset)
    digest = asset.get("digest") or ""
    if re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest):
        checksum = digest.split(":", 1)[1].lower()
    else:
        sums = [item for item in release.get("assets", []) if item.get("name") == "SHA256SUMS"]
        if len(sums) != 1:
            raise ValueError(tr('Для client-ru.zip нет SHA-256 в GitHub или SHA256SUMS.'))
        with request(asset_url(sums[0])) as response:
            data = response.read(65537)
        if len(data) > 65536:
            raise ValueError(tr('Слишком большой SHA256SUMS.'))
        matches = re.findall(r"^([a-fA-F0-9]{64})\s+\*?client-ru\.zip\s*$", data.decode("utf-8"), re.MULTILINE)
        if len(matches) != 1:
            raise ValueError(tr('В SHA256SUMS нет однозначной суммы client-ru.zip.'))
        checksum = matches[0].lower()
    return {"tag": release["tag_name"], "asset": asset, "sha256": checksum}


def client_entries(archive_path, label=ASSET_NAME):
    """Validate paths and locate one web root, independent of the enclosing directory."""
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if len(entries) > 250000 or sum(entry.file_size for entry in entries) > MAX_UNPACKED:
            raise ValueError(tr('Архив {0} слишком большой.', label))
        files, names = {}, set()
        for entry in entries:
            name = entry.filename.replace("\\", "/").rstrip("/")
            path = PurePosixPath(name)
            if not name or path.is_absolute() or str(path) != name or any(part in (".", "..") for part in path.parts):
                raise ValueError(tr('Недопустимый путь в {0}: ', label) + entry.filename)
            for part in path.parts:
                if re.search(r'[<>:"|?*\x00-\x1f]', part) or part.endswith((".", " ")) or re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part, re.I):
                    raise ValueError(tr('Недопустимое имя в {0}: ', label) + entry.filename)
            if any(part in IGNORED for part in path.parts):
                continue
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError(tr('Архив {0} содержит ссылку: ', label) + entry.filename)
            if name.casefold() in names:
                raise ValueError(tr('Повторяющийся путь в {0}: ', label) + entry.filename)
            names.add(name.casefold())
            if not entry.is_dir() and not entry.filename.endswith(("/", "\\")):
                files[name] = entry
        roots = []
        for name in files:
            if PurePosixPath(name).name == "index.html":
                prefix = name[:-len("index.html")]
                if any(file.startswith(prefix + "main/") for file in files):
                    roots.append(prefix)
        if len(roots) != 1:
            raise ValueError(tr('В {0} нужна одна папка с index.html и main/. Можно упаковать саму папку клиента или её содержимое.', label))
        root = roots[0]
        return {name[len(root):]: entry for name, entry in files.items() if name.startswith(root)}


def download(info, destination, log):
    asset = info["asset"]
    expected_size = asset.get("size") or 0
    if not isinstance(expected_size, int) or expected_size < 0 or expected_size > MAX_DOWNLOAD:
        raise ValueError(tr('Размер client-ru.zip превышает допустимый.'))
    digest = hashlib.sha256()
    size, last_percent, last_report = 0, -5, time.monotonic()
    log(tr('Скачиваю {0} из Release {1}…', ASSET_NAME, info['tag']))
    with request(asset_url(asset)) as response, Path(destination).open("wb") as output:
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_DOWNLOAD:
                raise ValueError(tr('client-ru.zip слишком большой.'))
            output.write(chunk)
            digest.update(chunk)
            percent = min(100, size * 100 // expected_size) if expected_size else 0
            if (expected_size and percent >= last_percent + 5) or time.monotonic() - last_report >= 10:
                log(tr('Русский клиент: {0}% ({1} МБ)', percent, size // (1024 * 1024)) if expected_size else tr('Русский клиент: скачано {0} МБ', size // (1024 * 1024)))
                last_percent, last_report = percent, time.monotonic()
    if not size or digest.hexdigest() != info["sha256"] or (expected_size and size != expected_size):
        raise ValueError(tr('SHA-256 или размер client-ru.zip не совпали. Прежний клиент сохранён.'))


def already_installed(client, info):
    try:
        marker = json.loads((client / MARKER).read_text(encoding="utf-8"))
        return ((client / "index.html").is_file() and (client / "main").is_dir()
                and isinstance(marker, dict) and marker.get("sha256") == info["sha256"])
    except (OSError, ValueError):
        return False


def install_client(target, info=None, log=print):
    target = Path(target).resolve()
    client = target / "client-ru"
    if client.is_symlink():
        raise ValueError(tr('Папка client-ru является ссылкой. Выберите обычную папку для установки.'))
    if client.exists() and not client.is_dir():
        raise ValueError(tr('Путь client-ru занят файлом. Выберите другую папку установки.'))
    info = info or release_info()
    if already_installed(client, info):
        log(tr('Русский клиент Release {0} уже установлен.', info['tag']))
        return client
    with update_workspace(target) as (work, retain_backup):
        archive = work / ASSET_NAME
        download(info, archive, log)
        try:
            entries = client_entries(archive)
        except zipfile.BadZipFile as error:
            raise ValueError(tr('client-ru.zip повреждён. Прежний клиент сохранён.')) from error
        new_client, backup = work / "new-client", work / "previous-client"
        new_client.mkdir()
        log(tr('Распаковываю русский клиент…'))
        try:
            with zipfile.ZipFile(archive) as package:
                for name, entry in entries.items():
                    file = new_client / name
                    file.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(entry) as source, file.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
        except zipfile.BadZipFile as error:
            raise ValueError(tr('client-ru.zip повреждён при распаковке. Прежний клиент сохранён.')) from error
        (new_client / MARKER).write_text(json.dumps({"tag": info["tag"], "asset_id": info["asset"].get("id"), "sha256": info["sha256"]}), encoding="utf-8")
        with update_lock(target):
            if client.is_symlink():
                raise ValueError(tr('Папка client-ru стала ссылкой. Установка отменена.'))
            if client.exists() and not client.is_dir():
                raise ValueError(tr('Путь client-ru занят файлом. Установка отменена.'))
            existed = client.exists()
            if existed:
                client.replace(backup)
            try:
                new_client.replace(client)
            except OSError:
                if existed:
                    try:
                        backup.replace(client)
                    except OSError as error:
                        retain_backup[0] = True
                        raise RuntimeError(tr('Прежний client-ru сохранён в {0}. Не удалось восстановить папку автоматически.', backup)) from error
                raise
        log(tr('Русский клиент установлен из Release {0}.', info['tag']))
        return client
