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
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from . import platform as plat
from . import settings, runtime


def engine_dir() -> Path:
    """Каталог нашего сервера LocalBox."""
    return plat.repo_root() / "server"


def client_dir() -> Path:
    return plat.repo_root() / "client"


def russian_client_dir() -> Path:
    """Русская оболочка (jackbox.ru/jackbox.fun). Если есть — основной клиент, а англ. client/ —
    фоллбэк для совпадающих путей. Приоритет: client-ru, затем client-fun."""
    for name in ("client-ru", "client-fun"):
        d = plat.repo_root() / name
        if d.exists():
            return d
    return plat.repo_root() / "client-ru"  # по умолчанию (может не существовать)


def find_node() -> str | None:
    """Ищет node: встроенный runtime/ рядом с проектом -> PATH -> nvm -> прочие места."""
    exe = "node.exe" if plat.is_windows() else "node"
    # встроенный node (если положен в комплект сборки: <repo>/runtime/ или <repo>/runtime/bin/)
    for p in [folder / exe for folder in runtime.binary_dirs()]:
        if p.exists():
            return str(p)
    node = shutil.which("node")
    if node:
        return node
    candidates = sorted(glob.glob(str(Path.home() / ".nvm/versions/node/*/bin/node")),
                        key=lambda p: tuple(map(int, re.findall(r"\d+", Path(p).parents[1].name))), reverse=True)
    candidates += [str(Path.home() / ".lmstudio/.internal/utils/node")]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def write_config(server_url: str, log=print) -> bool:
    """Создаёт server/config.json (serverUrl + пути к серту)."""
    config_path = engine_dir() / "config.json"
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        if not isinstance(cfg, dict):
            raise ValueError("config.json должен содержать объект")
        cfg["serverUrl"] = server_url
        cfg.setdefault("ssl", {"cert": "../certs/localbox.pem", "key": "../certs/localbox-key.pem"})
        cfg.setdefault("games", {"appTags": {}, "appIds": {}, "maxPlayers": {}, "minPlayers": {}})
        cfg.setdefault("appConfigs", {})
        tmp = config_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, indent="\t", ensure_ascii=False), encoding="utf-8")
        tmp.replace(config_path)
    except (OSError, ValueError) as e:
        log(f"Не удалось записать server/config.json: {e}")
        return False
    log(f"server/config.json записан (serverUrl={server_url})")
    return True


def deps_installed() -> bool:
    try:
        deps = json.loads((engine_dir() / "package.json").read_text(encoding="utf-8"))["dependencies"]
        return all((engine_dir() / "node_modules" / name / "package.json").is_file() for name in deps)
    except (OSError, ValueError, KeyError):
        return False


def install_deps(log=print) -> bool:
    from .npm import invocation
    node = find_node()
    npm_name = "npm.cmd" if plat.is_windows() else "npm"
    npm = shutil.which(npm_name) or (str(Path(node).parent / npm_name) if node else None)
    if not npm or not os.path.exists(npm):
        log("npm не найден. Установите Node.js.")
        return False
    log("Устанавливаю зависимости движка (npm i)… это может занять минуту")
    env = os.environ.copy()
    if node:
        env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
    try:
        command = invocation(node, npm, runtime.paths().get('npm_cli'), windows=plat.is_windows())
        p = subprocess.run([*command, "install"], env=env, cwd=str(engine_dir()), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           shell=False)
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
        if plat.has_admin():
            log("macOS: лаунчер уже запущен с правами root; порты 80/443 доступны.")
            return True
        log("macOS: порты 80/443 требуют запуска от root (sudo). Запустите лаунчер через sudo, "
            "либо смените порты движка (нежелательно — игры ждут 80/443).")
        return False
    node = find_node()
    if not node:
        log("node не найден.")
        return False
    real = os.path.realpath(node)
    getcap = shutil.which("getcap")
    if getcap:
        try:
            current = subprocess.run([getcap, real], capture_output=True, text=True, timeout=10)
            if "cap_net_bind_service" in current.stdout:
                log(f"Порты 80/443 уже разрешены для node ({real}).")
                return True
        except (OSError, subprocess.SubprocessError):
            pass
    cmd = ["setcap", "cap_net_bind_service=+ep", real]
    runner = [] if plat.has_admin() else (["pkexec"] if shutil.which("pkexec") else (["sudo"] if shutil.which("sudo") else None))
    if runner is None:
        log("Нужен pkexec или sudo. Вручную: sudo setcap cap_net_bind_service=+ep " + real)
        return False
    try:
        p = subprocess.run(runner + cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
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
        env = os.environ.copy()
        env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
        # TTS: движок и голос из настроек + python для Silero-воркера (тот же, что у лаунчера).
        _s = settings.load()
        if _s.get("auto_start_full", False):
            env["LOCALBOX_AUTO_START_FULL"] = "1"
            self.on_log("Автостарт включён: игра запустится, когда комната заполнится.")
        if not _s.get("download_missing", True):
            env.pop("LOCALBOX_FETCH_ORIGIN", None)
        env["LOCALBOX_TTS_ENGINE"] = _s.get("tts_engine", "auto")
        env["LOCALBOX_TTS_VOICE"] = _s.get("tts_voice", "eugene")
        _tts_py = (_s.get("tts_python") or "").strip()
        env["LOCALBOX_PYTHON"] = _tts_py or (sys.executable if not getattr(sys, "frozen", False) else (shutil.which("python3") or "python3"))
        # Додо Ре Ми: включаем локальный рендер выступления, если в настройках включено
        # (либо если флаг уже задан в окружении, напр. из start-server.bat).
        dodo = os.environ.get("LOCALBOX_DODO")
        if dodo == "1" or (dodo != "0" and _s.get("dodo_render")):
            env["LOCALBOX_DODO"] = "1"
            self.on_log("Додо Ре Ми: поддержка включена (локальный рендер выступления, нужен ffmpeg).")
        else:
            env.pop("LOCALBOX_DODO", None)
        # Громкость рендера Додо Ре Ми (инструмент / бэкинг).
        env["LOCALBOX_RENDER_INSTR"] = str(_s.get("render_instr", 4.0))
        env["LOCALBOX_RENDER_BACKING"] = str(_s.get("render_backing", 0.45))
        # Читы: ники (через запятую), которым доступен чит-оверлей прямо в игре.
        _admins = (_s.get("admin_nicks") or os.environ.get("LOCALBOX_ADMINS") or "").strip()
        if _admins:
            env["LOCALBOX_ADMINS"] = _admins
            _content = (_s.get("cheat_content_dir") or "").strip()
            if _content:
                env["LOCALBOX_CHEAT_CONTENT"] = _content
            # Показ «правильного ответа» / «цены картины» — по настройке (по умолчанию включены).
            for option, variable in (("cheat_answer", "LOCALBOX_CHEAT_ANSWER"),
                                     ("cheat_price", "LOCALBOX_CHEAT_PRICE"),
                                     ("cheat_highlight", "LOCALBOX_CHEAT_HIGHLIGHT")):
                env[variable] = "1" if _s.get(option, True) else "0"
            self.on_log(f"Читы включены для: {_admins} (зайди в игру под этим ником — оверлей справа / Ctrl+Shift+K).")
        # Фиксированный код комнаты (свой/русский), если задан. В ВЕРХНЕМ регистре — клиент при вводе
        # всё равно апперкейсит код, иначе набранный «игра» не совпадёт с комнатой «Игра».
        _code = (_s.get("room_code") or "").strip().upper()
        if _code:
            env["LOCALBOX_ROOM_CODE"] = _code
            self.on_log(f"Код комнаты зафиксирован: {_code}")
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
            if _s.get("download_missing", True):
                origin = "https://jackbox.fun" if rc.name == "client-fun" else "https://jackbox.ru"
                env["LOCALBOX_FETCH_ORIGIN"] = origin
                self.on_log(f"Клиент: русский ({rc.name}) + фоллбэк client/ + докачка недостающего с {origin}")
            else:
                env.pop("LOCALBOX_FETCH_ORIGIN", None)
                self.on_log(f"Клиент: русский ({rc.name}) + фоллбэк client/ — полностью локально (без докачки)")
        else:
            env["LOCALBOX_CLIENT_DIR"] = str(client_dir())
        try:
            self.proc = subprocess.Popen(
                [node, "server.js"], cwd=str(engine_dir()), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                encoding="utf-8", errors="replace",
            )
        except Exception as e:  # noqa: BLE001
            self.on_log(f"Не удалось запустить движок: {e}")
            return False
        threading.Thread(target=self._pump, args=(self.proc,), daemon=True).start()
        self.on_log("Движок запускается…")
        return True

    def _pump(self, proc):
        try:
            for line in proc.stdout:
                self.on_log(line.rstrip("\n"))
        except Exception:  # noqa: BLE001
            pass
        self.on_log("Движок остановлен.")

    def stop(self):
        if not self.is_running():
            return
        proc = self.proc
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        except ProcessLookupError:
            pass
