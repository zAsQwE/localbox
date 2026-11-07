"""Shared desktop/installer translations. Language never changes game data."""

import json
import locale
import os
from pathlib import Path

LANGUAGES = {"ru": "Русский", "en": "English"}
_language = None
_catalog = None


def normalize(value):
    code = str(value or "").lower().replace("-", "_").split("_")[0]
    return code if code in LANGUAGES else None


def detect(saved=None):
    """Saved user choice, environment default, then desktop locale."""
    value = normalize(saved) or normalize(os.environ.get("LOCALBOX_LANGUAGE"))
    if value:
        return value
    try:
        system = locale.getlocale()[0]
    except (ValueError, TypeError):
        system = None
    system = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or system or os.environ.get("LANG")
    return "ru" if normalize(system) == "ru" else "en"


def set_language(value):
    global _language
    code = normalize(value)
    if code is None:
        raise ValueError("Language must be ru or en")
    _language = code
    os.environ["LOCALBOX_LANGUAGE"] = code
    return code


def language():
    global _language
    if _language is None:
        try:
            saved = json.loads((Path(__file__).resolve().parents[1] / "localbox-settings.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            saved = {}
        if not isinstance(saved, dict):
            saved = {}
        _language = detect(saved.get("language"))
    return _language


def tr(message, *values):
    global _catalog
    if language() == "en":
        if _catalog is None:
            _catalog = json.loads((Path(__file__).parent / "translations" / "en.json").read_text(encoding="utf-8"))
        message = _catalog.get(message, message)
    return message.format(*values) if values else message


def choose_language(root, initial=None):
    """Small bilingual first screen; cancellation starts no installation."""
    import tkinter as tk
    from tkinter import ttk

    result = [None]
    window = tk.Toplevel(root)
    window.title("LocalBox — Language / Язык")
    window.resizable(False, False)
    frame = ttk.Frame(window, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Language / Язык", font=("TkDefaultFont", 14, "bold")).pack(anchor="w", pady=(0, 12))
    selected = tk.StringVar(value=normalize(initial) or detect())
    for code, label in LANGUAGES.items():
        ttk.Radiobutton(frame, text=label, value=code, variable=selected).pack(anchor="w", pady=4)
    def confirm():
        result[0] = set_language(selected.get())
        window.destroy()
    ttk.Button(frame, text="Continue / Продолжить", command=confirm).pack(pady=(16, 0))
    window.bind("<Return>", lambda _: confirm())
    window.update_idletasks()
    window.geometry("+%d+%d" % (max(0, (window.winfo_screenwidth() - window.winfo_reqwidth()) // 2),
                                max(0, (window.winfo_screenheight() - window.winfo_reqheight()) // 2)))
    window.grab_set()
    root.wait_window(window)
    return result[0]
