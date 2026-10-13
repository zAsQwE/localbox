"""Каталог готовых локальных голосов; проверка ничего не скачивает."""

import json
import shutil
import subprocess
import sys

from . import platform as plat, settings, runtime

PIPER_LABELS = {"ru_RU-denis-medium": "Денис", "ru_RU-dmitri-medium": "Дмитрий",
                "ru_RU-irina-medium": "Ирина", "ru_RU-ruslan-medium": "Руслан"}


def python_modules(python):
    try:
        result = subprocess.run(
            [python, "-c", "import importlib.util,json; print(json.dumps({n: importlib.util.find_spec(n) is not None for n in ('torch','numpy','piper')}))"],
            capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
        return json.loads(result.stdout) if result.returncode == 0 else {}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


def installed_voices(cfg=None):
    runtime.activate()
    cfg = cfg or settings.load()
    available = python_modules((cfg.get("tts_python") or "").strip() or sys.executable)
    folder = plat.repo_root() / "server" / "tts"
    voices = []
    model = folder / "v4_ru.pt"
    if available.get("torch") and available.get("numpy") and model.is_file() and model.stat().st_size > 0:
        voices.extend({"engine": "silero", "voice": voice, "label": "Silero · " + voice}
                      for voice in settings.TTS_VOICES)
    if available.get("piper"):
        for voice in settings.PIPER_VOICES:
            model = folder / "piper" / (voice + ".onnx")
            config = folder / "piper" / (voice + ".onnx.json")
            try:
                metadata = json.loads(config.read_text())
                ready = (isinstance(metadata, dict) and isinstance(metadata.get("audio"), dict)
                         and isinstance(metadata["audio"].get("sample_rate"), (int, float))
                         and metadata["audio"]["sample_rate"] > 0
                         and isinstance(metadata.get("phoneme_id_map"), dict) and metadata["phoneme_id_map"])
                if model.is_file() and model.stat().st_size > 0 and ready:
                    voices.append({"engine": "piper", "voice": voice, "label": "Piper · " + PIPER_LABELS[voice]})
            except (OSError, ValueError):
                continue
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    if espeak:
        try:
            result = subprocess.run([espeak, "--voices=ru"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and any(" ru " in " " + line + " " for line in result.stdout.splitlines()[1:]):
                voices.append({"engine": "espeak", "voice": "ru", "label": "eSpeak · русский"})
        except (OSError, subprocess.TimeoutExpired):
            pass
    return voices
