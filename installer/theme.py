"""Read the desktop's colour preference without changing its settings."""

import configparser
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def _read_command(command):
    if not shutil.which(command[0]):
        return ""
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=1,
                                check=False)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _portal_preference(value):
    match = re.search(r"\buint32\s+([0-9]+)\b", value)
    if match and match[1] in ("1", "2"):
        return match[1] == "1"
    return None


def detect_dark():
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
        except OSError:
            return False
    if sys.platform == "darwin":
        return _read_command(["defaults", "read", "-g", "AppleInterfaceStyle"]).lower() == "dark"

    portal = ["gdbus", "call", "--session", "--dest", "org.freedesktop.portal.Desktop",
              "--object-path", "/org/freedesktop/portal/desktop", "--method"]
    for method in ("ReadOne", "Read"):
        preferred = _portal_preference(_read_command(
            portal + ["org.freedesktop.portal.Settings." + method,
                      "org.freedesktop.appearance", "color-scheme"]))
        if preferred is not None:
            return preferred

    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    if "kde" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower():
        config = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            config.read(config_home / "kdeglobals", encoding="utf-8")
            rgb = config.get("Colors:Window", "BackgroundNormal", fallback="").split(",")
            if len(rgb) == 3:
                r, g, b = (int(part) for part in rgb)
                return 0.2126 * r + 0.7152 * g + 0.0722 * b < 128
            name = config.get("General", "ColorScheme", fallback="")
            if name:
                return "dark" in name.lower()
        except (OSError, ValueError, configparser.Error):
            pass

    preference = _read_command(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"])
    if "prefer-dark" in preference:
        return True
    if "prefer-light" in preference:
        return False
    if os.environ.get("GTK_THEME"):
        return "dark" in os.environ["GTK_THEME"].lower()
    for version in ("gtk-3.0", "gtk-4.0"):
        config = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            config.read(config_home / version / "settings.ini", encoding="utf-8")
            if config.getboolean("Settings", "gtk-application-prefer-dark-theme", fallback=False):
                return True
            if "dark" in config.get("Settings", "gtk-theme-name", fallback="").lower():
                return True
        except (OSError, ValueError, configparser.Error):
            pass
    gtk_theme = _read_command(["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"])
    return "dark" in gtk_theme.lower()
