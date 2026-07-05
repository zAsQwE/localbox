#
#   LocalBox - local private server for Jackbox games
#   Copyright (C) 2026 LocalBox contributors
#   Licensed under the GNU Affero General Public License v3 or later.
#
"""Запуск игрового сервера LocalBox (server/server.js) и генерация его config.json.

Сервер слушает порты 80/443/38202/38203, поэтому node должен иметь право на привилегированные
порты (setcap) либо запуск от root.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from . import platform as plat
from . import settings


def engine_dir() -> Path:
    """Каталог нашего сервера LocalBox."""
    return plat.repo_root() / "server"


def client_dir() -> Path:
    return plat.repo_root() / "client"


def russian_client_dir() -> Path:
    """Русская оболочка (jackbox.ru/jackbox.fun). Если есть — основной клиент, а англ. client/ —
    фоллбэк ассетов (хеши совпадают). Приоритет: client-ru, затем client-fun."""
    for name in ("client-ru", "client-fun"):
        d = plat.repo_root() / name
        if d.exists():
            return d
    return plat.repo_root() / "client-ru"  # по умолчанию (может не существовать)


def find_node() -> str | None:
    """Ищет node: встроенный runtime/ рядом с проектом -> PATH -> nvm -> прочие места."""
    exe = "node.exe" if plat.is_windows() else "node"
    # встроенный node (если положен в комплект сборки: <repo>/runtime/ или <repo>/runtime/bin/)
    for p in (plat.repo_root() / "runtime" / exe, plat.repo_root() / "runtime" / "bin" / exe):
        if p.exists():
            return str(p)
    node = shutil.which("node")
    if node:
        return node
    candidates = sorted(glob.glob(str(Path.home() / ".nvm/versions/node/*/bin/node")), reverse=True)
    candidates += [str(Path.home() / ".lmstudio/.internal/utils/node")]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def write_config(server_url: str, log=print) -> bool:
    """Создаёт server/config.json (serverUrl + пути к серту)."""
    cfg = {
        "serverUrl": server_url,
        "ssl": {"cert": "../certs/localbox.pem", "key": "../certs/localbox-key.pem"},
        "games": {"appTags": {}, "appIds": {}, "maxPlayers": {}, "minPlayers": {}},
        "appConfigs": {},
    }
    (engine_dir() / "config.json").write_text(json.dumps(cfg, indent="\t", ensure_ascii=False), encoding="utf-8")
    log(f"server/config.json записан (serverUrl={server_url})")
    return True


def deps_installed() -> bool:
    return (engine_dir() / "node_modules" / "express").exists()


def install_deps(log=print) -> bool:
    npm = shutil.which("npm") or (str(Path(find_node()).parent / "npm") if find_node() else None)
    if not npm or not os.path.exists(npm):
        log("npm не найден. Установите Node.js.")
        return False
    log("Устанавливаю зависимости движка (npm i)… это может занять минуту")
    try:
        p = subprocess.run([npm, "install"], cwd=str(engine_dir()), capture_output=True, text=True,
                           shell=plat.is_windows())
        if p.returncode != 0:
            log(p.stdout[-500:]); log(p.stderr[-500:])
            return False
        log("Зависимости движка установлены.")
        return True
    except Exception as e:  # noqa: BLE001
        log(f"Ошибка npm install: {e}")
        return False


def allow_privileged_ports(log=print) -> bool:
    """Даёт node право слушать порты <1024 (setcap), чтобы движок работал без sudo. Нужен pkexec/root."""
    if plat.is_windows():
        log("Windows: отдельно разрешать порты не нужно — низкие порты (80/443) доступны. "
            "Просто нажмите «Запустить». Если порт занят — закройте IIS/Skype или запустите от администратора.")
        return True
    if plat.is_macos():
        log("macOS: порты 80/443 требуют запуска от root (sudo). Запустите лаунчер через sudo, "
            "либо смените порты движка (нежелательно — игры ждут 80/443).")
        return False
    node = find_node()
    if not node:
        log("node не найден.")
        return False
    real = os.path.realpath(node)
    cmd = ["setcap", "cap_net_bind_service=+ep", real]
    runner = ["pkexec"] if shutil.which("pkexec") else (["sudo"] if shutil.which("sudo") else None)
    if not runner:
        log("Нужен pkexec или sudo. Вручную: sudo setcap cap_net_bind_service=+ep " + real)
        return False
    try:
        p = subprocess.run(runner + cmd, capture_output=True, text=True)
        if p.returncode == 0:
            log(f"Порты 80/443 разрешены для node ({real}).")
            return True
        log(p.stderr.strip() or "Не удалось выдать права.")
        return False
    except Exception as e:  # noqa: BLE001
        log(f"Ошибка setcap: {e}")
        return False


class EngineProcess:
    """Запуск server/server.js с выводом лога в колбэк."""

    def __init__(self, server_url: str, on_log=print, no_web: bool = False):
        self.on_log = on_log
        self.server_url = server_url
        self.no_web = no_web
        self.proc = None

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> bool:
        if self.is_running():
            self.on_log("Движок уже запущен.")
            return True
        node = find_node()
        if not node:
            self.on_log("node не найден. Установите Node.js (https://nodejs.org).")
            return False
        # Прибиваем зависший прошлый сервер и освобождаем его порты (переживают краши). best-effort.
        for cmd in (
            ["pkill", "-9", "-f", "server/server.js"],
            ["fuser", "-k", "-9", "38202/tcp"],
            ["fuser", "-k", "-9", "38203/tcp"],
        ):
            try:
                subprocess.run(cmd, capture_output=True, timeout=5)
            except Exception:  # noqa: BLE001
                pass
        env = os.environ.copy()
        env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
        # TTS: движок и голос из настроек + python для Silero-воркера (тот же, что у лаунчера).
        _s = settings.load()
        env["LOCALBOX_TTS_ENGINE"] = _s.get("tts_engine", "auto")
        env["LOCALBOX_TTS_VOICE"] = _s.get("tts_voice", "eugene")
        _tts_py = (_s.get("tts_python") or "").strip()
        env["LOCALBOX_PYTHON"] = _tts_py or (sys.executable if not getattr(sys, "frozen", False) else (shutil.which("python3") or "python3"))
        if self.no_web:
            env["LOCALBOX_NO_CLIENT"] = "1"
            self.on_log("Режим -no-web: веб-клиент не раздаётся (только игровой сервер).")
        # Если есть русская оболочка — она основная, английский клиент с ассетами — фоллбэк.
        if russian_client_dir().exists():
            rc = russian_client_dir()
            env["LOCALBOX_CLIENT_DIR"] = str(rc)
            env["LOCALBOX_CLIENT_FALLBACK"] = str(client_dir())
            # Докачка фирменных ассетов (задники/логотипы/«ячейки») с исходного сайта — по настройке.
            # Выключено = полностью локально (движок не ходит на jackbox.ru).
            if settings.load().get("download_missing", True):
                origin = "https://jackbox.fun" if rc.name == "client-fun" else "https://jackbox.ru"
                env["LOCALBOX_FETCH_ORIGIN"] = origin
                self.on_log(f"Клиент: русский ({rc.name}) + фоллбэк client/ + докачка недостающего с {origin}")
            else:
                self.on_log(f"Клиент: русский ({rc.name}) + фоллбэк client/ — полностью локально (без докачки)")
        else:
            env["LOCALBOX_CLIENT_DIR"] = str(client_dir())
        try:
            self.proc = subprocess.Popen(
                [node, "server.js"], cwd=str(engine_dir()), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
        except Exception as e:  # noqa: BLE001
            self.on_log(f"Не удалось запустить движок: {e}")
            return False
        threading.Thread(target=self._pump, daemon=True).start()
        self.on_log("Движок запускается…")
        return True

    def _pump(self):
        try:
            for line in self.proc.stdout:
                self.on_log(line.rstrip("\n"))
        except Exception:  # noqa: BLE001
            pass
        self.on_log("Движок остановлен.")

    def stop(self):
        if not self.is_running():
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
