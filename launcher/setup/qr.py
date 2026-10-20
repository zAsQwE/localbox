"""Local QR requests and positioning within one physical monitor."""

import base64
from dataclasses import dataclass
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request


class QRClient:
    def __init__(self, base_url="http://127.0.0.1:38202"):
        self.base_url = base_url.rstrip("/")
        # The local server must remain reachable when the desktop uses an HTTP proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.key = None
        self.image = None

    def status(self):
        with self.opener.open(self.base_url + "/localbox/status", timeout=1.5) as response:
            return json.loads(response.read().decode("utf-8")).get("room")

    def fetch(self):
        room = self.status()
        if not room or room.get("qrVisible") is False:
            self.key = self.image = None
            return None, None
        key = (room["code"], room["joinUrl"])
        if key != self.key:
            url = self.base_url + "/localbox/qr.png?code=" + urllib.parse.quote(room["code"], safe="")
            with self.opener.open(url, timeout=2) as response:
                png = response.read()
            if not png.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Сервер вернул некорректное изображение QR-кода.")
            self.image = base64.b64encode(png).decode("ascii")
            self.key = key
        return room, self.image


@dataclass(frozen=True)
class Monitor:
    x: int
    y: int
    width: int
    height: int
    primary: bool = False


def parse_xrandr(output):
    monitors = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 3 or not fields[0].rstrip(":").isdigit():
            continue
        match = re.fullmatch(r"(\d+)(?:/\d+)?x(\d+)(?:/\d+)?([+-]\d+)([+-]\d+)", fields[2])
        if match:
            width, height, x, y = map(int, match.groups())
            if width > 0 and height > 0:
                monitors.append(Monitor(x, y, width, height, "*" in fields[1]))
    return monitors


def _windows_monitors():
    import ctypes
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                    ("work", wintypes.RECT), ("flags", wintypes.DWORD)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), callback_type, wintypes.LPARAM]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    monitors = []
    def append(handle, _dc, _rect, _data):
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            rect = info.work
            monitors.append(Monitor(rect.left, rect.top, rect.right - rect.left,
                                    rect.bottom - rect.top, bool(info.flags & 1)))
        return True
    user32.EnumDisplayMonitors(None, None, callback_type(append), 0)
    return monitors


_layout_cache = (0, [])


def monitor_layout():
    global _layout_cache
    now = time.monotonic()
    if now - _layout_cache[0] < 5:
        return _layout_cache[1]
    monitors = []
    try:
        if sys.platform == "win32":
            monitors = _windows_monitors()
        elif sys.platform.startswith("linux"):
            result = subprocess.run(["xrandr", "--listmonitors"], capture_output=True,
                                    text=True, timeout=1, check=False)
            if result.returncode == 0:
                monitors = parse_xrandr(result.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    _layout_cache = (now, monitors)
    return monitors


def overlay_position(width, height, monitors, anchor, fallback):
    """Use the launcher's monitor, not the corner of the virtual desktop's bounding box."""
    ax, ay = anchor
    monitor = next((m for m in monitors if m.x <= ax < m.x + m.width and m.y <= ay < m.y + m.height), None)
    if monitor is None:
        monitor = next((m for m in monitors if m.primary), monitors[0] if monitors else fallback)
    return (max(monitor.x, monitor.x + monitor.width - width - 24),
            max(monitor.y, monitor.y + monitor.height - height - 48))
