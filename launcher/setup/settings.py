#
#   LocalBox — пользовательские настройки лаунчера (сохраняются в файл).
#
"""Простое хранилище настроек в launcher/localbox-settings.json.

download_missing: качать ли недостающие фирменные текстуры с jackbox.ru при первой загрузке.
    False = полностью локальный режим (движок не ходит на jackbox.ru, только локальные файлы).
"""

from __future__ import annotations

import json
from pathlib import Path

from . import platform as plat

DEFAULTS = {
    "download_missing": True,
    "tts_engine": "auto",   # auto | silero | piper | espeak | silent
    "tts_voice": "eugene",  # голос Silero: eugene | baya | kseniya | xenia | aidar | random
    "tts_python": "",       # путь к python с TTS-библиотеками (напр. venv на 3.11); пусто = python лаунчера
}

TTS_ENGINES = ["auto", "silero", "piper", "espeak", "silent"]
# голоса Silero:
TTS_VOICES = ["eugene", "baya", "kseniya", "xenia", "aidar", "random"]
# голоса Piper (piper1-gpl), русские:
PIPER_VOICES = ["ru_RU-denis-medium", "ru_RU-dmitri-medium", "ru_RU-irina-medium", "ru_RU-ruslan-medium"]


def voices_for(engine: str):
    """Список голосов для выбранного движка (для выпадающего списка в настройках)."""
    return PIPER_VOICES if engine == "piper" else TTS_VOICES


def _path() -> Path:
    return plat.repo_root() / "launcher" / "localbox-settings.json"


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        p = _path()
        if p.exists():
            data.update(json.loads(p.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        pass
    return data


def save(data: dict) -> bool:
    try:
        _path().write_text(json.dumps(data, indent="\t", ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001
        return False
