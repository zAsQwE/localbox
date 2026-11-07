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


def python_ca_env(python, env):
    """Add certifi's roots for a TTS Python on Windows (SSL_CERT_FILE; other systems unchanged).

    Windows Python reads the ROOT store directly and, unlike Windows itself, never fetches a
    missing root on demand, so on a fresh system HTTPS to Hugging Face (Piper voices) or the
    Silero model host fails with "unable to get local issuer certificate". Python loads the
    file on top of ROOT, so locally trusted roots keep working.
    """
    if os.name != "nt" or env.get("SSL_CERT_FILE"):
        return env
    bundle = Path(python).parent.parent / "Lib" / "site-packages" / "certifi" / "cacert.pem"
    return {**env, "SSL_CERT_FILE": str(bundle)} if bundle.is_file() else env


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
