#!/usr/bin/env python3
#
# LocalBox — воркер синтеза речи Silero (офлайн, русский).
# Модель v4_ru скачивается один раз (~60 МБ) в этот же каталог, дальше работает без интернета.
# Общение с Node-сервером: JSON-строки в stdin/stdout.
#   вход:  {"id":N, "text":"...", "speaker":"eugene", "out":"/путь/файл.wav"}
#   выход: {"ok":true,"id":N}  или  {"ok":false,"id":N,"error":"..."}
#
import sys
import os
import json
import re
import wave


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


try:
    import torch
    import numpy as np
except Exception as e:  # noqa: BLE001
    emit({"ready": False, "error": "не установлен torch/numpy: " + str(e)})
    sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "v4_ru.pt")
URL = "https://models.silero.ai/models/tts/ru/v4_ru.pt"
SR = int(os.environ.get("LOCALBOX_TTS_SR", "48000"))
DEFAULT_SPK = os.environ.get("LOCALBOX_TTS_VOICE") or "eugene"
SPEAKERS = ["aidar", "baya", "kseniya", "xenia", "eugene", "random"]

try:
    torch.set_num_threads(max(1, os.cpu_count() or 1))
    if not os.path.isfile(MODEL):
        emit({"info": "скачиваю модель Silero (~60 МБ, один раз, нужен интернет)…"})
        torch.hub.download_url_to_file(URL, MODEL)
    model = torch.package.PackageImporter(MODEL).load_pickle("tts_models", "model")
    model.to(torch.device("cpu"))
except Exception as e:  # noqa: BLE001
    emit({"ready": False, "error": "модель Silero не загрузилась: " + str(e)})
    sys.exit(1)


def synth_to_wav(text, spk, out):
    import numpy as _np
    audio = model.apply_tts(text=text, speaker=spk, sample_rate=SR, put_accent=True, put_yo=True)
    pcm = (audio.numpy() * 32767).astype(_np.int16)
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# Одноразовый режим предпрослушивания:  python silero_worker.py --sample <speaker> <out.wav>
if "--sample" in sys.argv:
    i = sys.argv.index("--sample")
    spk = sys.argv[i + 1] if len(sys.argv) > i + 1 else DEFAULT_SPK
    out = sys.argv[i + 2] if len(sys.argv) > i + 2 else "sample.wav"
    if spk not in SPEAKERS:
        spk = DEFAULT_SPK
    synth_to_wav("Привет! Это мой голос для игр Джекбокс.", spk, out)
    emit({"ok": True})
    sys.exit(0)

emit({"ready": True, "speakers": SPEAKERS})

TAG = re.compile(r"<[^>]+>")
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = None
    try:
        req = json.loads(line)
        text = TAG.sub("", req.get("text") or " ").strip() or "…"
        if len(text) > 900:
            text = text[:900]
        spk = req.get("speaker") or DEFAULT_SPK
        if spk not in SPEAKERS:
            spk = DEFAULT_SPK
        out = req["out"]
        audio = model.apply_tts(text=text, speaker=spk, sample_rate=SR, put_accent=True, put_yo=True)
        pcm = (audio.numpy() * 32767).astype(np.int16)
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm.tobytes())
        emit({"ok": True, "id": req.get("id")})
    except Exception as e:  # noqa: BLE001
        emit({"ok": False, "id": (req.get("id") if req else None), "error": str(e)})
