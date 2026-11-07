"""Launcher interface to the standalone release updater."""

import importlib
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


def russian_client():
    """Import installed setup helpers without changing the launcher's search path."""
    name = "_localbox_installer"
    if name not in sys.modules:
        directory = plat.repo_root() / "installer"
        spec = importlib.util.spec_from_file_location(name, directory / "__init__.py",
                                                     submodule_search_locations=[str(directory)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name, None)
            raise
    return importlib.import_module(name + ".client_ru")


def launch(archive, version, work):
    # Run a copy so the worker can replace its own installed source files on Windows.
    work = Path(work)
    for name in ("update.py", "window.py", "theme.py"):
        shutil.copy2(plat.repo_root() / "installer" / name, work / name)
    # The detached worker must retain translations while replacing the installation.
    shutil.copy2(plat.repo_root() / "launcher/setup/i18n.py", work / "i18n.py")
    shutil.copytree(plat.repo_root() / "launcher/setup/translations", work / "translations", dirs_exist_ok=True)
    from . import i18n
    env = {**os.environ, "LOCALBOX_LANGUAGE": i18n.language()}
    return subprocess.Popen([sys.executable, str(work / "update.py"), "--archive", str(archive),
                             "--target", str(plat.repo_root()), "--version", version, "--parent", str(os.getpid())],
                            cwd=work, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def temporary_directory():
    return Path(tempfile.mkdtemp(prefix="localbox-release-"))
