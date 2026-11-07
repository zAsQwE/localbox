"""Certificate trust for Jackbox, without touching Linux or Steam stores.

  * Linux: LocalBox writes a public bundle (system roots + the LocalBox CA) and shows
    it in the Steam launch line (-cafile + SSL_CERT_FILE); the player adds it there. Neither the
    system store nor Steam's files change.
  * Windows: the Windows ROOT store (one Windows confirmation), the only place
    Windows builds look, after consent in setup or the certificate button.
  * Trivia Murder Party 3: its own certificate file, via the TMP3 patch.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

from . import platform as plat
from .i18n import tr

# Left by an earlier development build that configured Steam's container instead.
LEGACY_ENV_NAME = "PRESSURE_VESSEL_IMPORT_CA_CERTS"


def legacy_env_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "environment.d" / "90-localbox-steam.conf"


def remove_legacy_env(log=print) -> bool:
    """Drop the Steam container variable written by an earlier build. No elevation."""
    try:
        legacy_env_file().unlink()
    except FileNotFoundError:
        return False
    # The D-Bus activation environment re-syncs into systemd, so clear it there too.
    for command in (["dbus-update-activation-environment", "--systemd", LEGACY_ENV_NAME + "="],
                    ["systemctl", "--user", "unset-environment", LEGACY_ENV_NAME]):
        if shutil.which(command[0]):
            try:
                subprocess.run(command, capture_output=True, timeout=10, stdin=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                pass
    log(tr('Старая настройка Steam Linux Runtime от LocalBox удалена: теперь сертификат передаётся в строке запуска.'))
    return True


def system_needs_update(public_ca) -> bool:
    """Windows only: does the Windows ROOT store lack the CA?"""
    if plat.is_windows():
        from . import windows_roots
        return not windows_roots.command(public_ca, "verify")
    return False  # Linux keeps its system store untouched; macOS: confirmed button only


def heal(*, log=print) -> bool:
    """Re-apply the trust the user agreed to (Windows store only). Never raises."""
    from . import cert_trust, certs
    if plat.is_linux():
        remove_legacy_env(log)
        return True
    if not plat.is_windows():
        return True
    try:
        public_ca = certs.localbox_ca_files(plat.certs_dir())[0].read_text(encoding="ascii")
        if system_needs_update(public_ca):
            cert_trust.install_local_ca(confirmed=True, log=log, public_ca=public_ca)
        return True
    except Exception as error:  # noqa: BLE001
        log(tr('Доверие на этом компьютере не обновлено: {0}', error))
        return False
