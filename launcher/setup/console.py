"""Русское меню в Windows Console, Windows Terminal и перенаправленном журнале."""

import os
import sys


def configure():
    # activate() changes only the environment of future children; repair this interpreter too.
    for name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    class FontInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.ULONG), ("nFont", wintypes.DWORD),
                    ("dwFontSize", wintypes._COORD), ("FontFamily", wintypes.UINT),
                    ("FontWeight", wintypes.UINT), ("FaceName", wintypes.WCHAR * 32)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetConsoleCP(65001)
    kernel.SetConsoleOutputCP(65001)
    # CONOUT$ also works when PowerShell redirected stdout. Raster fonts cannot
    # render UTF-8 Cyrillic reliably; change only this window's font, never registry defaults.
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    handle = kernel.CreateFileW("CONOUT$", 0xC0000000, 3, None, 3, 0, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        return
    kernel.GetCurrentConsoleFontEx.argtypes = [wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(FontInfo)]
    kernel.SetCurrentConsoleFontEx.argtypes = [wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(FontInfo)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        info = FontInfo()
        info.cbSize = ctypes.sizeof(info)
        if kernel.GetCurrentConsoleFontEx(handle, False, ctypes.byref(info)):
            if not info.FontFamily & 4:  # TMPF_TRUETYPE
                info.FaceName = "Consolas"
                info.FontFamily = 54
                info.dwFontSize.X = 0
                info.dwFontSize.Y = max(16, info.dwFontSize.Y)
                kernel.SetCurrentConsoleFontEx(handle, False, ctypes.byref(info))
    finally:
        kernel.CloseHandle(handle)
