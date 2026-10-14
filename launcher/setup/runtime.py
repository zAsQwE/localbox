"""Пути к зависимостям, установленным мастером LocalBox."""

import json
import os
from pathlib import Path

from . import platform as plat


def paths():
    try:
        value = json.loads((plat.repo_root() / "launcher" / "install-paths.json").read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def directory():
    return Path(paths().get("runtime") or plat.repo_root() / "runtime")


def binary_dirs():
    base = directory()
    saved = paths()
    discovered = [Path(saved[name]).parent for name in ("node", "npm", "git", "ffmpeg", "openssl", "mkcert", "python")
                  if saved.get(name) and Path(saved[name]).is_file()]
    return discovered + [base, base / "bin", base / "node", base / "python", base / "python" / "Scripts",
            base / "git" / "cmd", base / "git" / "ucrt64" / "bin",
            base / "git" / "mingw64" / "bin", base / "ffmpeg" / "bin"]


def activate():
    dirs = [str(path) for path in binary_dirs() if path.is_dir()]
    current = os.environ.get("PATH", "").split(os.pathsep)
    os.environ["PATH"] = os.pathsep.join(dirs + [path for path in current if path not in dirs])
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
