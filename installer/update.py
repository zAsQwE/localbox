#!/usr/bin/env python3
"""Verified release downloads and a standalone, rollback-capable LocalBox updater."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import queue
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile

REPOSITORY = "zAsQwE/localbox"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
ASSET_NAME = "localbox-update.zip"
MAX_SIZE = 100 * 1024 * 1024
MANIFEST = "installer/payload-sha256.json"
ROOT_FILES = {"LICENSE", "README.md", "start-server.sh", "start-server.bat", "setup.sh", "install.bat", "version.json"}
EXCLUDED = {".git", "node_modules", "runtime", "client", "client-ru", "certs", "storage", "cache", "render",
            "test", "tests", "__pycache__", "build", "dist", "piper"}
PRIVATE_FILES = {"config.json", "localbox-settings.json", "install-paths.json", "update-state.json", "setup-options.ini", "testing.md"}


@contextmanager
def update_lock(target):
    path = Path(target) / ".localbox-update.lock"
    if path.is_symlink():
        raise ValueError("Файл блокировки обновления является символьной ссылкой.")
    with path.open("a+b") as file:
        if not path.stat().st_size:
            file.write(b"0"); file.flush()
        file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError("Эта копия LocalBox уже обновляется в другом окне.") from error
        try:
            yield
        finally:
            file.seek(0)
            if os.name == "nt":
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)


@contextmanager
def update_workspace(target):
    work = Path(tempfile.mkdtemp(prefix=".localbox-update-", dir=target))
    retain = [False]
    try:
        yield work, retain
    finally:
        if not retain[0]:
            shutil.rmtree(work, ignore_errors=True)


def version_tuple(value):
    match = re.fullmatch(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(value).strip())
    if not match:
        raise ValueError("Номер версии должен выглядеть как v1.2.0 или 1.2.0.")
    return tuple(int(part or 0) for part in match.groups())


def current_version(root):
    try:
        value = json.loads((Path(root) / "version.json").read_text(encoding="utf-8"))["version"]
        version_tuple(value)
        return value
    except (OSError, ValueError, KeyError, TypeError):
        return "0.0.0"


def request(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "LocalBox-Updater",
                                  "Accept": "application/vnd.github+json"}), timeout=30)


def latest_release(root=None):
    try:
        with request(f"https://api.github.com/repos/{REPOSITORY}/releases/latest") as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("Слишком большой ответ GitHub.")
        release = json.loads(data)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        if error.code in (403, 429):
            raise RuntimeError("GitHub ограничил запросы. Повторите проверку позднее.") from error
        raise
    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        return None
    version_tuple(release.get("tag_name", ""))
    if root is not None and version_tuple(release["tag_name"]) <= version_tuple(current_version(root)):
        return None
    return release


def asset_url(asset):
    url = asset.get("browser_download_url", "")
    if not isinstance(url, str) or not url.startswith(RELEASES_URL + "/download/"):
        raise ValueError("Адрес файла обновления не принадлежит Releases LocalBox.")
    return url


def download_release(release, destination, log=print):
    assets = {asset["name"]: asset for asset in release.get("assets", [])}
    asset = assets.get(ASSET_NAME)
    if not asset:
        raise RuntimeError(f"В выпуске {release['tag_name']} нет {ASSET_NAME}. Автору нужно прикрепить архив к Release.")
    digest = asset.get("digest") or ""
    if not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest):
        checksum_asset = assets.get("SHA256SUMS")
        if not checksum_asset:
            raise ValueError("В Release нет SHA-256 для проверки обновления.")
        with request(asset_url(checksum_asset)) as response:
            data = response.read(65537)
        if len(data) > 65536:
            raise ValueError("Слишком большой список SHA256SUMS.")
        matches = re.findall(r"^([a-fA-F0-9]{64})\s+\*?localbox-update\.zip\s*$", data.decode("utf-8"), re.MULTILINE)
        if len(matches) != 1:
            raise ValueError("В SHA256SUMS отсутствует однозначная сумма архива обновления.")
        digest = "sha256:" + matches[0]
    expected = digest.split(":", 1)[1].lower()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(".part")
    log(f"Скачиваю LocalBox {release['tag_name']}…")
    try:
        actual = hashlib.sha256()
        size = 0
        with request(asset_url(asset)) as response, partial.open("wb") as output:
            while chunk := response.read(128 * 1024):
                size += len(chunk)
                if size > MAX_SIZE:
                    raise ValueError("Архив обновления слишком большой.")
                actual.update(chunk)
                output.write(chunk)
        if not size or actual.hexdigest() != expected:
            raise ValueError("SHA-256 обновления не совпала. Файлы приложения не изменены.")
        validate_archive(partial, release["tag_name"])
        partial.replace(destination)
        return destination
    finally:
        partial.unlink(missing_ok=True)


def allowed_path(name):
    path = PurePosixPath(name)
    if "\\" in name or ":" in name or path.is_absolute() or str(path) != name:
        return False
    if not path.parts or any(part in EXCLUDED or part.startswith(".") or part.startswith("test_") for part in path.parts):
        return False
    if path.name in PRIVATE_FILES:
        return False
    return name in ROOT_FILES or (path.parts[0] in ("launcher", "server", "installer", "tools", "docs")
                                  and path.suffix in (".py", ".js", ".json", ".md", ".txt", ".ps1", ".sh", ".nsi"))


def validate_archive(archive_path, expected_version=None):
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(entries) > 5000 or sum(entry.file_size for entry in entries) > MAX_SIZE:
            raise ValueError("Слишком большой пакет обновления.")
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError("В архиве повторяются пути файлов.")
        for entry in entries:
            if not allowed_path(entry.filename) or stat.S_ISLNK(entry.external_attr >> 16) or entry.is_dir():
                raise ValueError("Недопустимый файл обновления: " + entry.filename)
        manifest = json.loads(archive.read(MANIFEST))
        if not isinstance(manifest, dict) or set(names) != set(manifest) | {MANIFEST} or MANIFEST in manifest:
            raise ValueError("Файлы архива не совпадают с манифестом.")
        for required in ("server/server.js", "server/package.json", "launcher/localbox_launcher.py", "version.json"):
            if required not in manifest:
                raise ValueError("Неполный архив обновления: " + required)
        for name, expected in manifest.items():
            if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
                raise ValueError("Неверная контрольная сумма: " + name)
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError("Повреждён файл обновления: " + name)
        version = json.loads(archive.read("version.json"))["version"]
        if expected_version and version_tuple(version) != version_tuple(expected_version):
            raise ValueError("Версия архива не совпадает с тегом Release.")
        version_tuple(version)
        return manifest


def wait_for_parent(pid, timeout=60):
    if not pid:
        return
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if handle:
            try:
                if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
                    raise RuntimeError("Лаунчер не завершился. Обновление отменено.")
            finally:
                kernel.CloseHandle(handle)
    else:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        raise RuntimeError("Лаунчер не завершился. Обновление отменено.")


def prepare_dependencies(source, target, log):
    server, old_server = source / "server", target / "server"
    same = all((server / name).is_file() == (old_server / name).is_file()
               and (not (server / name).is_file() or (server / name).read_bytes() == (old_server / name).read_bytes())
               for name in ("package.json", "package-lock.json"))
    dependencies = json.loads((server / "package.json").read_text()).get("dependencies", {})
    installed = all((old_server / "node_modules" / name / "package.json").is_file() for name in dependencies)
    if same and installed:
        log("Зависимости сервера уже установлены.")
        return False
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise RuntimeError("Не найден npm. Запустите setup для проверки зависимостей.")
    log("Подготавливаю зависимости новой версии…")
    command = [npm, "ci" if (server / "package-lock.json").is_file() else "install", "--omit=dev"]
    with subprocess.Popen(command, cwd=server, shell=os.name == "nt", stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace") as process:
        for line in process.stdout:
            log(line.rstrip())
        if process.wait():
            raise RuntimeError("Не удалось подготовить npm-зависимости. Прежняя версия сохранена.")
    (server / "node_modules").mkdir(exist_ok=True)
    return True


def apply_update(archive_path, target, log=print, expected_version=None):
    target = Path(target).resolve()
    if not (target / "server/server.js").is_file():
        raise ValueError("Не найдена установленная копия LocalBox.")
    manifest = validate_archive(archive_path, expected_version)
    for name in manifest:
        destination = target / name
        chain = [destination, *destination.parents]
        chain = chain[:chain.index(target) + 1]
        if any(part.is_symlink() for part in chain):
            raise ValueError("Путь обновления содержит символьную ссылку: " + name)
    if (target / "server/node_modules").is_symlink():
        raise ValueError("node_modules является ссылкой. Используйте setup для обновления этой установки.")
    if (target / ".git").exists():
        git = shutil.which("git")
        if not git:
            raise RuntimeError("Не найден git для проверки локальных изменений.")
        status = subprocess.run([git, "status", "--porcelain", "--untracked-files=no"], cwd=target, capture_output=True, text=True, check=True)
        if status.stdout.strip():
            raise RuntimeError("В исходниках есть незакоммиченные изменения. Сохраните их перед обновлением.")
    with update_lock(target), update_workspace(target) as (work, retain_backup):
        source, backup = work / "new", work / "backup"
        source.mkdir(); backup.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            for name in manifest:
                file = source / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(archive.read(name))
                if file.suffix == ".sh":
                    file.chmod(0o755)
        replace_modules = prepare_dependencies(source, target, log)
        changed = []
        modules_replaced = False
        old_modules = False
        try:
            if replace_modules:
                modules = target / "server/node_modules"
                if modules.exists():
                    modules.replace(backup / "node_modules")
                    old_modules = True
                modules_replaced = True
                (source / "server/node_modules").replace(modules)
            for name in manifest:
                destination = target / name
                old = backup / name
                existed = destination.exists()
                if existed:
                    old.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, old)
                destination.parent.mkdir(parents=True, exist_ok=True)
                (source / name).replace(destination)
                changed.append((name, existed))
            log(f"LocalBox {current_version(target)} установлен. Настройки и загруженные данные сохранены.")
        except Exception:
            try:
                for name, existed in reversed(changed):
                    destination = target / name
                    if existed:
                        (backup / name).replace(destination)
                    else:
                        destination.unlink(missing_ok=True)
                if modules_replaced:
                    modules = target / "server/node_modules"
                    if modules.exists():
                        shutil.rmtree(modules)
                    if old_modules:
                        (backup / "node_modules").replace(modules)
            except OSError as error:
                retain_backup[0] = True
                raise RuntimeError(f"Не удалось завершить откат. Резервные файлы сохранены: {backup}") from error
            log("Ошибка обновления. Прежняя версия восстановлена.")
            raise


def restart(target):
    env = os.environ.copy()
    # Keep the saved GUI settings rather than replaying a previous start menu selection.
    env.pop("LOCALBOX_DODO", None)
    subprocess.Popen([sys.executable, str(Path(target) / "launcher/localbox_launcher.py"), "--gui"], cwd=target,
                     env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def main():
    parser = argparse.ArgumentParser(description="Обновление LocalBox из проверенного архива Release")
    parser.add_argument("--archive", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--parent", type=int, default=0)
    parser.add_argument("--no-restart", action="store_true")
    parser.add_argument("--console", action="store_true")
    args = parser.parse_args()
    def execute(log):
        wait_for_parent(args.parent)
        apply_update(args.archive, args.target, log, args.version)
    try:
        import tkinter as tk
        from tkinter import ttk
        from window import fit_window
        if args.console:
            raise ImportError
        root = tk.Tk()
    except Exception as error:
        # No display/Tk: use the same verified update flow without a window.
        if not args.console:
            print(f"Окно обновления недоступно: {error}")
        execute(print)
        if not args.no_restart:
            restart(args.target)
        return
    root.title("LocalBox — обновление")
    fit_window(root)
    from theme import detect_dark
    dark = detect_dark()
    bg, fg = ("#202124", "#f1f2f3") if dark else ("#f5f5f5", "#202124")
    root.configure(bg=bg)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=bg, foreground=fg)
    body = ttk.Frame(root, padding=20); body.pack(fill="both", expand=True)
    status = tk.StringVar(value="Обновляю LocalBox…")
    ttk.Label(body, textvariable=status, wraplength=360).pack(anchor="w")
    button = ttk.Button(body, text="Открыть LocalBox", state="disabled")
    button.pack(side="bottom", fill="x", pady=(12, 0))
    text = tk.Text(body, wrap="word", bg=bg, fg=fg, state="disabled", relief="flat")
    text.pack(fill="both", expand=True, pady=(12, 0))
    events = queue.Queue()
    running = [True]
    def open_launcher():
        if not running[0]:
            if not args.no_restart:
                restart(args.target)
            root.destroy()
    button.configure(command=open_launcher)
    root.protocol("WM_DELETE_WINDOW", open_launcher)
    def worker():
        try:
            execute(lambda message: events.put(("log", str(message))))
            events.put(("done", "Обновление установлено."))
        except Exception as error:
            events.put(("error", str(error)))
    def drain():
        while not events.empty():
            kind, message = events.get_nowait()
            if kind == "log":
                text.configure(state="normal"); text.insert("end", message + "\n"); text.see("end"); text.configure(state="disabled")
            else:
                running[0] = False
                status.set(message)
                button.configure(state="normal")
                if kind == "done":
                    root.after(700, open_launcher)
        root.after(100, drain)
    threading.Thread(target=worker, daemon=True).start()
    drain(); root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Обновление не установлено: {error}", file=sys.stderr)
        sys.exit(1)
    finally:
        work = Path(__file__).resolve().parent
        if work.name.startswith("localbox-release-"):
            shutil.rmtree(work, ignore_errors=True)
