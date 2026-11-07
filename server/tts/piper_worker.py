#!/usr/bin/env python3
"""Persistent Piper: one loaded voice, sequential UTF-8 JSON jobs, no model downloads."""
import json
import os
import sys
import wave


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


try:
    import onnxruntime
    from piper import PiperVoice
    from piper.config import PiperConfig

    model_path = os.environ["LOCALBOX_PIPER_MODEL"]
    with open(model_path + ".json", encoding="utf-8") as stream:
        config = PiperConfig.from_dict(json.load(stream))
    options = onnxruntime.SessionOptions()
    cores = os.cpu_count() or 1
    default_threads = min(2, max(1, cores - 1))
    options.intra_op_num_threads = max(1, min(4, cores, int(os.environ.get("LOCALBOX_TTS_THREADS", str(default_threads)))))
    options.inter_op_num_threads = 1
    options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    voice = PiperVoice(config=config, session=onnxruntime.InferenceSession(
        model_path, sess_options=options, providers=["CPUExecutionProvider"]))
except Exception as error:
    emit({"ready": False, "error": str(error)})
    sys.exit(1)

emit({"ready": True})
for line in sys.stdin:
    request = None
    try:
        request = json.loads(line)
        with wave.open(request["out"], "wb") as output:
            voice.synthesize_wav(request.get("text") or " ", output)
        emit({"id": request["id"], "ok": True})
    except Exception as error:
        emit({"id": request.get("id") if request else None, "ok": False, "error": str(error)})
