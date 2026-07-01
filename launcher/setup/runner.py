#
#   LocalBox - local private server for Jackbox games
#   Copyright (C) 2026 LocalBox contributors
#   Licensed under the GNU Affero General Public License v3 or later.
#
"""Запуск/останов Node-сервера и стриминг его логов в колбэк (для GUI)."""

import shutil
import subprocess
import threading
from pathlib import Path

from . import platform as plat


def node_available() -> bool:
    return shutil.which("node") is not None


def npm_available() -> bool:
    return shutil.which("npm") is not None


def ensure_dependencies(log=print) -> bool:
    """Ставит зависимости сервера (ws), если node_modules отсутствует."""
    server = plat.server_dir()
    if (server / "node_modules" / "ws").exists():
        return True
    if not npm_available():
        log("npm не найден. Установите Node.js (https://nodejs.org) и повторите.")
        return False
    log("Устанавливаю зависимости сервера (npm install)…")
    try:
        proc = subprocess.run(
            ["npm", "install"], cwd=str(server),
            capture_output=True, text=True,
            shell=plat.is_windows(),  # npm на Windows — это npm.cmd
        )
        if proc.returncode != 0:
            log(proc.stdout)
            log(proc.stderr)
            log("npm install завершился с ошибкой.")
            return False
        log("Зависимости установлены.")
        return True
    except Exception as e:  # noqa: BLE001
        log(f"Ошибка npm install: {e}")
        return False


class ServerProcess:
    """Обёртка над `node src/index.js` с потоковой передачей вывода в on_log."""

    def __init__(self, env_overrides=None, on_log=print):
        self.on_log = on_log
        self.env_overrides = env_overrides or {}
        self.proc = None
        self._thread = None

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> bool:
        if self.is_running():
            self.on_log("Сервер уже запущен.")
            return True
        if not node_available():
            self.on_log("node не найден. Установите Node.js (https://nodejs.org).")
            return False

        import os

        env = os.environ.copy()
        env.update({k: str(v) for k, v in self.env_overrides.items()})
        server = plat.server_dir()
        try:
            self.proc = subprocess.Popen(
                ["node", "src/index.js"], cwd=str(server), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, shell=plat.is_windows(),
            )
        except Exception as e:  # noqa: BLE001
            self.on_log(f"Не удалось запустить сервер: {e}")
            return False

        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()
        self.on_log("Сервер запущен.")
        return True

    def _pump(self):
        try:
            for line in self.proc.stdout:
                self.on_log(line.rstrip("\n"))
        except Exception:
            pass
        self.on_log("Сервер остановлен.")

    def stop(self):
        if not self.is_running():
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
