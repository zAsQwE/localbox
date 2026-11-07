"""Validated connection options copied by the launcher."""

import re

from .i18n import tr

def server_address(value):
    value = str(value).strip()
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::[0-9]{1,5})?", value):
        raise ValueError(tr('Укажи IP или имя сервера без https:// и пробелов.'))
    host, separator, port = value.partition(":")
    if len(host) > 253 or (separator and not 1 <= int(port) <= 65535):
        raise ValueError(tr('Неверный адрес или порт сервера.'))
    return value


RESERVED_PORTS = {443, 38202, 38203}


def porthole_port(value):
    """Web port to share in Porthole: 80 (the normal one) or an extra HTTP port 1024–65535."""
    try:
        port = int(str(value).strip())
    except ValueError:
        return None
    if port == 80 or (1024 <= port <= 65535 and port not in RESERVED_PORTS):
        return port
    return None


def launch_options(host):
    """The bare server option: all a Windows build needs once Windows trusts the LocalBox CA."""
    return "-jbg.config serverUrl=" + server_address(host)


def steam_launch_options(host):
    """The one Steam line the launcher shows.

    Windows: only serverUrl. Linux: one line for every build (see linux_launch_options), or the
    bare option until the server has written the game CA file once.
    """
    cafile = game_cafile()
    return linux_launch_options(host, cafile) if cafile else launch_options(host)


def _quoted(value):
    return '"' + value + '"' if " " in value else value


def linux_launch_options(host, cafile):
    """One Steam line for native Linux builds and Windows builds under Proton alike.

    Native builds (Launcher.sh, packs 2–8) run in the Steam Linux Runtime container with its own
    CA bundle: -cafile gives their HTTPS and WebSocket clients the game-only CA file.
    Windows builds under Proton (pack 1, Jackbox 12, Naughty Pack, Russian repacks) have no
    -cafile (they log "Unknown option" and go on) and check TLS against Windows ROOT:
    protocol=http keeps their REST calls off TLS, and SSL_CERT_FILE (Z: is the Linux root as
    Proton sees it) points their WebSocket library at the same file; native builds work with
    both as well (checked on pack 2 in the Steam container and pack 1 under Proton).
    Launcher.sh passes "$@" unquoted, so a folder with spaces breaks -cafile for native builds.
    Nothing in Steam's folders or the system store changes.
    """
    path = str(cafile)
    if any(c in path for c in '"\\\n\r$`'):
        raise ValueError(tr('Недопустимый путь к файлу сертификатов игры.'))
    return ("SSL_CERT_FILE=" + _quoted("Z:" + path) + " %command% -jbg.config serverUrl="
            + server_address(host) + " protocol=http -cafile " + _quoted(path))


def game_cafile():
    """The public CA bundle for the Linux Steam line, or None (other systems, not created yet)."""
    from . import certs, platform as plat
    if not plat.is_linux():
        return None
    path = certs.game_bundle_path()
    return path if path.is_file() else None
