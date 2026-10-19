"""Download a Russian web client from the selected LocalBox GitHub Release."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import time
import urllib.parse
import zipfile

from update import REPOSITORY, asset_url, latest_release, request, update_lock, update_workspace, version_tuple

ASSET_NAME = "client-ru.zip"
MARKER = ".localbox-release.json"
MAX_DOWNLOAD = 4 * 1024**3
MAX_UNPACKED = 12 * 1024**3
IGNORED = {".git", ".hg", ".svn", "__MACOSX", ".DS_Store"}


def release_info(tag=None):
    tag = tag or os.environ.get("LOCALBOX_RELEASE_TAG")
    if tag:
        version_tuple(tag)
        with request(f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{urllib.parse.quote(tag, safe='')}") as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("Слишком большой ответ GitHub.")
        release = json.loads(data)
        if not isinstance(release, dict) or release.get("tag_name") != tag:
            raise ValueError("GitHub вернул другой выпуск для русского клиента.")
    else:
        release = latest_release()
    if not release or release.get("draft") or release.get("prerelease"):
        raise RuntimeError("Нет стабильного Release для русского клиента.")
    assets = [asset for asset in release.get("assets", []) if asset.get("name") == ASSET_NAME]
    if len(assets) != 1:
        raise RuntimeError(f"В Release {release['tag_name']} нет {ASSET_NAME}. Прикрепите архив русского клиента к этому выпуску.")
    asset = assets[0]
    asset_url(asset)
    digest = asset.get("digest") or ""
    if re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest):
        checksum = digest.split(":", 1)[1].lower()
    else:
        sums = [item for item in release.get("assets", []) if item.get("name") == "SHA256SUMS"]
        if len(sums) != 1:
            raise ValueError("Для client-ru.zip нет SHA-256 в GitHub или SHA256SUMS.")
        with request(asset_url(sums[0])) as response:
            data = response.read(65537)
        if len(data) > 65536:
            raise ValueError("Слишком большой SHA256SUMS.")
        matches = re.findall(r"^([a-fA-F0-9]{64})\s+\*?client-ru\.zip\s*$", data.decode("utf-8"), re.MULTILINE)
        if len(matches) != 1:
            raise ValueError("В SHA256SUMS нет однозначной суммы client-ru.zip.")
        checksum = matches[0].lower()
    return {"tag": release["tag_name"], "asset": asset, "sha256": checksum}


def client_entries(archive_path, label=ASSET_NAME):
    """Validate paths and locate one web root, independent of the enclosing directory."""
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if len(entries) > 250000 or sum(entry.file_size for entry in entries) > MAX_UNPACKED:
            raise ValueError(f"Архив {label} слишком большой.")
        files, names = {}, set()
        for entry in entries:
            name = entry.filename.replace("\\", "/").rstrip("/")
            path = PurePosixPath(name)
            if not name or path.is_absolute() or str(path) != name or any(part in (".", "..") for part in path.parts):
                raise ValueError(f"Недопустимый путь в {label}: " + entry.filename)
            for part in path.parts:
                if re.search(r'[<>:"|?*\x00-\x1f]', part) or part.endswith((".", " ")) or re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part, re.I):
                    raise ValueError(f"Недопустимое имя в {label}: " + entry.filename)
            if any(part in IGNORED for part in path.parts):
                continue
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError(f"Архив {label} содержит ссылку: " + entry.filename)
            if name.casefold() in names:
                raise ValueError(f"Повторяющийся путь в {label}: " + entry.filename)
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
            raise ValueError(f"В {label} нужна одна папка с index.html и main/. Можно упаковать саму папку клиента или её содержимое.")
        root = roots[0]
        return {name[len(root):]: entry for name, entry in files.items() if name.startswith(root)}


def download(info, destination, log):
    asset = info["asset"]
    expected_size = asset.get("size") or 0
    if not isinstance(expected_size, int) or expected_size < 0 or expected_size > MAX_DOWNLOAD:
        raise ValueError("Размер client-ru.zip превышает допустимый.")
    digest = hashlib.sha256()
    size, last_percent, last_report = 0, -5, time.monotonic()
    log(f"Скачиваю {ASSET_NAME} из Release {info['tag']}…")
    with request(asset_url(asset)) as response, Path(destination).open("wb") as output:
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_DOWNLOAD:
                raise ValueError("client-ru.zip слишком большой.")
            output.write(chunk)
            digest.update(chunk)
            percent = min(100, size * 100 // expected_size) if expected_size else 0
            if (expected_size and percent >= last_percent + 5) or time.monotonic() - last_report >= 10:
                log(f"Русский клиент: {percent}% ({size // (1024 * 1024)} МБ)" if expected_size else f"Русский клиент: скачано {size // (1024 * 1024)} МБ")
                last_percent, last_report = percent, time.monotonic()
    if not size or digest.hexdigest() != info["sha256"] or (expected_size and size != expected_size):
        raise ValueError("SHA-256 или размер client-ru.zip не совпали. Прежний клиент сохранён.")


def already_installed(client, info):
    try:
        marker = json.loads((client / MARKER).read_text(encoding="utf-8"))
        return (client / "index.html").is_file() and (client / "main").is_dir() and marker == {
            "tag": info["tag"], "asset_id": info["asset"].get("id"), "sha256": info["sha256"]}
    except (OSError, ValueError):
        return False


def install_client(target, info=None, log=print):
    target = Path(target).resolve()
    client = target / "client-ru"
    if client.is_symlink():
        raise ValueError("Папка client-ru является ссылкой. Выберите обычную папку для установки.")
    if client.exists() and not client.is_dir():
        raise ValueError("Путь client-ru занят файлом. Выберите другую папку установки.")
    info = info or release_info()
    if already_installed(client, info):
        log(f"Русский клиент Release {info['tag']} уже установлен.")
        return client
    with update_workspace(target) as (work, retain_backup):
        archive = work / ASSET_NAME
        download(info, archive, log)
        try:
            entries = client_entries(archive)
        except zipfile.BadZipFile as error:
            raise ValueError("client-ru.zip повреждён. Прежний клиент сохранён.") from error
        new_client, backup = work / "new-client", work / "previous-client"
        new_client.mkdir()
        log("Распаковываю русский клиент…")
        try:
            with zipfile.ZipFile(archive) as package:
                for name, entry in entries.items():
                    file = new_client / name
                    file.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(entry) as source, file.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
        except zipfile.BadZipFile as error:
            raise ValueError("client-ru.zip повреждён при распаковке. Прежний клиент сохранён.") from error
        (new_client / MARKER).write_text(json.dumps({"tag": info["tag"], "asset_id": info["asset"].get("id"), "sha256": info["sha256"]}), encoding="utf-8")
        with update_lock(target):
            if client.is_symlink():
                raise ValueError("Папка client-ru стала ссылкой. Установка отменена.")
            if client.exists() and not client.is_dir():
                raise ValueError("Путь client-ru занят файлом. Установка отменена.")
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
                        raise RuntimeError(f"Прежний client-ru сохранён в {backup}. Не удалось восстановить папку автоматически.") from error
                raise
        log(f"Русский клиент установлен из Release {info['tag']}.")
        return client
