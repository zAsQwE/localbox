"""Launcher interface to the standalone release updater."""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from . import platform as plat


def updater():
    path = plat.repo_root() / "installer/update.py"
    spec = importlib.util.spec_from_file_location("localbox_release_updater", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def launch(archive, version, work):
    # Run a copy so the worker can replace its own installed source files on Windows.
    work = Path(work)
    for name in ("update.py", "window.py", "theme.py"):
        shutil.copy2(plat.repo_root() / "installer" / name, work / name)
    return subprocess.Popen([sys.executable, str(work / "update.py"), "--archive", str(archive),
                             "--target", str(plat.repo_root()), "--version", version, "--parent", str(os.getpid())],
                            cwd=work, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def temporary_directory():
    return Path(tempfile.mkdtemp(prefix="localbox-release-"))
