#
#   LocalBox — пользовательские настройки лаунчера (сохраняются в файл).
#
"""Простое хранилище настроек в launcher/localbox-settings.json.

download_missing: качать ли недостающие фирменные текстуры с jackbox.ru при первой загрузке.
download_game_images: качать ли изображения игр и emoji с CDN Jackbox в локальный кэш.
    Для полностью локального режима обе настройки должны быть выключены.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import platform as plat

DEFAULTS = {
    "language": "",          # ru | en; empty = system language
    "server_url": plat.local_ip(),  # адрес, который игра получает через -jbg.config serverUrl=...
    "game_profile": "classic", # classic | tmp3 (Unreal)
    "tmp3_path": "",        # установленная Trivia Murder Party 3; резервная копия хранится в игре
    "qr_overlay": True,
    "qr_position": "bottom-right",  # угол экрана для QR: bottom-right/bottom-left/top-right/top-left       # QR активной комнаты поверх игры в правом нижнем углу
    "porthole_enabled": True, # строка Porthole на главном экране и дополнительный веб-порт
    "porthole_port": 80,      # веб-порт для Porthole; не 80 = дополнительный HTTP-порт (напр. 9999)
    "auto_start_full": False, # нажать VIP-действие start, когда комната заполнена
    "game_trust": False,    # пользователь согласился: лаунчер поддерживает доверие CA для всех игр Jackbox
    "download_missing": True,
    "download_game_images": True,
    "tts_engine": "auto",   # auto | silero | piper | espeak | silent
    "tts_voice": "eugene",  # голос Silero: eugene | baya | kseniya | xenia | aidar | random
    "tts_python": "",       # путь к python с TTS-библиотеками (напр. venv на 3.11); пусто = python лаунчера
    "jackbox10_path": "",   # папка установленного Jackbox 10 или songs для импорта музыки
    "dodo_render": False,   # поддержка Додо Ре Ми (nopus-opus): локальный рендер выступления (нужен ffmpeg)
    "render_instr": 4.0,    # громкость инструмента в рендере Додо Ре Ми (LOCALBOX_RENDER_INSTR)
    "render_backing": 0.45, # громкость бэкинга (0..1) в рендере (LOCALBOX_RENDER_BACKING)
    "admin_nicks": "",      # ники (через запятую), которым доступны читы (оверлей в игре)
    "admin_key": "",        # ключ доступа к читам; пусто = сгенерировать при первом запуске
    "cheat_content_dir": "", # папка игры/Jackbox или steamapps/common; пусто = поиск в библиотеках Steam
    "cheat_answer": True,   # показывать «правильный ответ» списком в панели читов
    "cheat_highlight": True,  # подсвечивать найденные правильные варианты на кнопках
    "cheat_price": True,    # показывать цену картины (Дуракцион) пульсирующим ценником у картины
    "room_code": "",        # фиксированный код комнаты (пусто = случайный); можно свой/русский
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
