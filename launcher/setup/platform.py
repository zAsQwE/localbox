#
#   LocalBox - local private server for Jackbox games
#   Copyright (C) 2026 LocalBox contributors
#   Licensed under the GNU Affero General Public License v3 or later.
#
"""Определение ОС и путей: hosts-файл, каталоги Steam, корни репозитория."""

import os
import sys
from pathlib import Path

# Хосты Jackbox, которые перенаправляются на локальный сервер в режиме «без домена».
# ecast/api — API (отвечает наш сервер); jackbox.tv/bundles/cdn — веб-клиент (проксируется).
JACKBOX_HOSTS = [
    "ecast.jackboxgames.com",
    # Backend socket.io старых игр (Blobcast). Игра идёт сюда после GET /room.
    "ecast-prod-use2.jackboxgames.com",
    "api.jackbox.tv",
    "jackbox.tv",
    "www.jackbox.tv",
    "bundles.jackbox.tv",
    "cdn.jackboxgames.com",
    # Русский клиент (для режима «Играть» на русском)
    "jackbox.fun",
    "www.jackbox.fun",
    # Backend-серверы jackbox.fun (его клиент спрашивает комнату у них по пути /api/v2/rooms/,
    # поэтому заворачиваем на наш сервер — наш ecast ответит про нашу комнату).
    # ВНИМАНИЕ: это приватная инфраструктура jackbox.fun, имена могут со временем меняться —
    # сверяйтесь с вкладкой Network в DevTools, если перестанет работать.
    "jb-ecast.klucva.ru",
    "server.rujackbox.loamfy.com",
]


def is_windows():
    return os.name == "nt" or sys.platform.startswith("win")


def is_macos():
    return sys.platform == "darwin"


def is_linux():
    return sys.platform.startswith("linux")


def os_name():
    if is_windows():
        return "Windows"
    if is_macos():
        return "macOS"
    if is_linux():
        return "Linux"
    return sys.platform


def hosts_path() -> Path:
    """Путь к системному hosts-файлу для текущей ОС."""
    if is_windows():
        root = os.environ.get("SystemRoot", r"C:\Windows")
        return Path(root) / "System32" / "drivers" / "etc" / "hosts"
    return Path("/etc/hosts")


def _looks_like_repo(p: Path) -> bool:
    """Каталог похож на корень LocalBox, если в нём есть папка engine/."""
    return (p / "engine").is_dir()


def repo_root() -> Path:
    """Корень проекта LocalBox (где лежит папка engine/).

    Ищем НАДЁЖНО: поднимаемся вверх от исполняемого файла/скрипта, пока не найдём каталог
    с папкой engine/. Работает и из исходников, и из собранного exe, где бы он ни лежал
    (launcher/, launcher/dist/, корень проекта и т.п.).
    """
    starts = []
    if getattr(sys, "frozen", False):
        starts.append(Path(sys.executable).resolve().parent)
    starts.append(Path(__file__).resolve().parent)
    for start in starts:
        for cand in (start, *start.parents):
            if _looks_like_repo(cand):
                return cand
    # запасной вариант — прежняя логика по фиксированной глубине
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parents[2]


def server_dir() -> Path:
    return repo_root() / "server"


def certs_dir() -> Path:
    return repo_root() / "certs"


def config_path() -> Path:
    """config.json в корне репо (его читает сервер)."""
    return repo_root() / "config.json"


def steam_library_candidates():
    """Вероятные каталоги Steam (steamapps/common) для текущей ОС."""
    paths = []
    if is_windows():
        for base in [
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("ProgramFiles", r"C:\Program Files"),
        ]:
            paths.append(Path(base) / "Steam" / "steamapps" / "common")
    elif is_macos():
        home = Path.home()
        paths.append(home / "Library" / "Application Support" / "Steam" / "steamapps" / "common")
    else:  # Linux
        home = Path.home()
        paths += [
            home / ".steam" / "steam" / "steamapps" / "common",
            home / ".local" / "share" / "Steam" / "steamapps" / "common",
            home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam" / "steamapps" / "common",
        ]
    return [p for p in paths if p.exists()]


def local_ip() -> str:
    """Определяет основной локальный IP машины (для подключения телефонов в той же сети).

    Не отправляет реальных пакетов — лишь выбирает исходящий сетевой интерфейс.
    """
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        return "127.0.0.1"
    finally:
        s.close()


def has_admin() -> bool:
    """Есть ли права на правку системных файлов (нужно для hosts и доверия серту)."""
    if is_windows():
        try:
            import ctypes

            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False
