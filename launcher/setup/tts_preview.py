#
#   LocalBox — предпрослушивание голосов TTS в настройках.
#
"""Генерирует короткий образец выбранным движком/голосом и проигрывает его.

Silero — через server/tts/silero_worker.py (--sample); espeak — напрямую; громкость поднимается
через ffmpeg (как в игре). Работает офлайн (Silero после разовой загрузки модели)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

from . import platform as plat
from . import settings

SAMPLE_TEXT = "Привет! Это мой голос для игр Джекбокс."


def _py():
    """Python для TTS: заданный в настройках (venv) или тот, которым запущен лаунчер."""
    p = (settings.load().get("tts_python") or "").strip()
    return p or sys.executable or "python3"


def _espeak_voice(voice: str) -> str:
    v = (voice or "").lower()
    if any(x in v for x in ("baya", "kseniya", "xenia", "fem", "жен")):
        return "ru+f3"
    if any(x in v for x in ("aidar", "eugene", "max", "male", "муж")):
        return "ru+m3"
    return "ru"


def _player():
    for p in ("paplay", "ffplay", "aplay", "mpv", "cvlc", "play"):
        if shutil.which(p):
            return p
    return None


def _make_sample(engine: str, voice: str, log) -> str | None:
    out = os.path.join(tempfile.gettempdir(), "localbox_voice_sample.wav")
    if os.path.exists(out):
        try:
            os.remove(out)
        except OSError:
            pass
    engine = (engine or "auto").lower()
    voice = voice or "eugene"
    py = _py()
    worker = plat.repo_root() / "server" / "tts" / "silero_worker.py"
    piper_dir = plat.repo_root() / "server" / "tts" / "piper"
    order = ["silero", "piper", "espeak"] if engine == "auto" else [engine]

    def sized():
        return os.path.exists(out) and os.path.getsize(out) > 100

    for eng in order:
        if eng == "silero" and worker.exists():
            try:
                log("Генерирую образец (Silero — первый раз качается модель ~60МБ, подождите)…")
                env = dict(os.environ)
                env["LOCALBOX_TTS_VOICE"] = voice
                r = subprocess.run([py, str(worker), "--sample", voice, out],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=600)
                if sized():
                    return _boost(out, log)
                if engine == "silero":
                    log("Silero недоступен: " + ((r.stderr or r.stdout or "").strip()[:200] or "нужен pip install torch numpy"))
            except Exception as e:  # noqa: BLE001
                log(f"Silero: {e}")
        elif eng == "piper":
            try:
                v = voice if voice in settings.PIPER_VOICES else settings.PIPER_VOICES[0]
                piper_dir.mkdir(parents=True, exist_ok=True)
                if not (piper_dir / (v + ".onnx")).exists():
                    log(f"Скачиваю голос Piper {v} (один раз, нужен интернет)…")
                    subprocess.run([py, "-m", "piper.download_voices", v, "--data-dir", str(piper_dir)],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
                log(f"Генерирую образец (Piper, {v})…")
                r = subprocess.run([py, "-m", "piper", "-m", v, "--data-dir", str(piper_dir), "-f", out],
                                   input=SAMPLE_TEXT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
                if sized():
                    return _boost(out, log)
                if engine == "piper":
                    err = (r.stderr or "").strip()
                    log("Piper: " + (err.splitlines()[-1][:200] if err else "нужен pip install piper-tts"))
            except Exception as e:  # noqa: BLE001
                log(f"Piper: {e}")
        elif eng == "espeak":
            esp = shutil.which("espeak-ng") or shutil.which("espeak")
            if esp:
                log("Генерирую образец (espeak)…")
                subprocess.run([esp, "-v", _espeak_voice(voice), "-w", out, SAMPLE_TEXT], capture_output=True)
                if sized():
                    return _boost(out, log)
    return None


def _boost(wav: str, log) -> str:
    ff = shutil.which("ffmpeg")
    if not ff:
        return wav
    loud = os.path.join(tempfile.gettempdir(), "localbox_voice_sample_loud.wav")
    subprocess.run([ff, "-y", "-i", wav, "-af", "loudnorm=I=-11:TP=-1.5:LRA=11,volume=1.5", loud], capture_output=True)
    return loud if (os.path.exists(loud) and os.path.getsize(loud) > 100) else wav


def preview(engine: str, voice: str, log=print) -> None:
    """Создаёт и проигрывает образец. Блокирующе — вызывать в отдельном потоке."""
    path = _make_sample(engine, voice, log)
    if not path:
        log("Не удалось создать образец. Для Silero: pip install torch numpy. Для espeak: поставьте espeak-ng.")
        return
    pl = _player()
    if not pl:
        log("Нет аудиоплеера. Поставьте pulseaudio-utils / alsa-utils / ffmpeg / mpv.")
        return
    log(f"▶ Играет образец голоса «{voice}»…")
    args = {
        "ffplay": [pl, "-nodisp", "-autoexit", "-loglevel", "quiet", path],
        "mpv": [pl, "--no-video", "--really-quiet", path],
        "cvlc": [pl, "--play-and-exit", "--intf", "dummy", path],
    }.get(pl, [pl, path])
    try:
        subprocess.run(args, timeout=30)
    except Exception as e:  # noqa: BLE001
        log(f"Плеер: {e}")
