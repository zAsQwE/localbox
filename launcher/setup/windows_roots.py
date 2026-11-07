"""Verified ROOT import/readback, for native Windows and a selected Proton prefix."""
import hashlib
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile

from .i18n import tr


def helper_binary():
    folder = Path(__file__).with_name("pki")
    binary = folder / "windows-root-x64.exe"
    manifest = json.loads((folder / "windows-root.json").read_text())
    if hashlib.sha256(binary.read_bytes()).hexdigest() != manifest["sha256"]:
        raise ValueError(tr('Повреждён помощник Windows ROOT. Переустанови LocalBox.'))
    return binary.resolve()


def command(public_ca, mode, *, wine=None, env=None):
    binary = helper_binary()
    der = ssl.PEM_cert_to_DER_cert(public_ca)
    fingerprint = hashlib.sha256(der).hexdigest().upper()
    with tempfile.TemporaryDirectory(prefix="localbox-root-public-") as folder:
        source = Path(folder) / "root.der"
        source.write_bytes(der)
        if wine:
            # Standard Proton prefixes expose the host filesystem through Z:.
            prefix = Path(env["WINEPREFIX"])
            z_drive = prefix / "dosdevices/z:"
            if not z_drive.is_symlink() or z_drive.resolve() != Path("/"):
                raise ValueError(tr('В Proton отсутствует стандартный диск Z:. Доверие не установлено.'))
            arguments = [str(wine), str(binary), mode, "Z:" + str(source).replace("/", "\\"), fingerprint]
        else:
            arguments = [str(binary), mode, str(source), fingerprint]
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        result = subprocess.run(arguments, env=env, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", stdin=subprocess.DEVNULL, timeout=90, **options)
    if mode == "verify" and result.returncode == 17:
        return False
    if result.returncode or "LOCALBOX_ROOT_OK" not in result.stdout:
        raise ValueError(tr('Windows ROOT не подтвердил сертификат (код {0}): {1}',
                            result.returncode, (result.stderr or result.stdout).strip()[-1500:]))
    return True


def install(public_ca, *, wine=None, env=None):
    command(public_ca, "install", wine=wine, env=env)
    if not command(public_ca, "verify", wine=wine, env=env):
        raise ValueError(tr('После импорта Windows ROOT не видит CA LocalBox.'))
