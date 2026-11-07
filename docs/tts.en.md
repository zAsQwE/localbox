[Русский](tts.md) · [English](tts.en.md) · [Home](README.en.md)

# Speech (TTS)

Games such as Mad Verse City request speech from the server. LocalBox synthesizes it locally using installed
models. If speech fails, it returns silence of the required length so the game can continue.
Changing the interface language does not change the language of these voices: setup currently offers Russian models.

## Engines and installation

| Engine | Requirements | One-time download |
| --- | --- | --- |
| `silero` | `torch`, `numpy` | Russian model, about 60 MB |
| `piper` | `piper-tts` | Selected model, about 20–60 MB per voice |
| `espeak` | System `espeak-ng` | No neural model |
| `silent` | None | None |
| `auto` | Tries Silero, Piper, eSpeak, then silence | Depends on installed engines |

Piper is lighter and faster on modest CPUs. Setup installs Python libraries in `<runtime>/tts`, downloads the selected
models, tests synthesis and saves that Python path. On Linux eSpeak is also available directly in setup.
Use **Settings → Speech → Preview** to test a voice before starting a game.

For manual installation, use the same Python executable selected in **TTS Python**:

```sh
python -m pip install torch numpy
python -m pip install piper-tts
python -m piper.download_voices ru_RU-denis-medium --data-dir server/tts/piper
```

Silero's `v4_ru` model downloads once when needed; after that synthesis works offline.
On Linux, install eSpeak using your package manager, e.g. `sudo apt install espeak-ng`,
`sudo pacman -S espeak-ng` or `sudo dnf install espeak-ng`.
Windows eSpeak can be installed separately from its official project; ensure `espeak-ng --version` works.

For Windows Piper DLL errors, install the official
[Visual C++ Redistributable x64](https://aka.ms/vs/17/release/vc_redist.x64.exe).
Use 64-bit Python; `python -c "import struct; print(struct.calcsize('P')*8)"` should print `64`.
If a model package is incompatible with your current Python, use a separate supported Python environment
and set its executable in **TTS Python**. Leaving that setting empty uses the launcher's interpreter.

## Voices and settings

Silero voices: `eugene`, `baya`, `kseniya`, `xenia`, `aidar`, `random`.
Piper voices: `ru_RU-denis-medium`, `ru_RU-dmitri-medium`, `ru_RU-irina-medium`, `ru_RU-ruslan-medium`.
The startup menu only lists complete local models with working Python libraries and does not download them.
Save changes and restart the server. The settings are in `launcher/localbox-settings.json`.

## Performance and cleanup

Piper/Silero workers retain their model between phrases. Identical text with the same settings reuses generated audio,
and concurrent requests for the same phrase share one synthesis job. Engine failures returning silence do not enter the persistent cache.
MP3 files, or WAV without ffmpeg, are stored in `server/storage/tts`.

In Mad Verse City, the server prepares the supplied first line when the player receives it and queues the second line
as soon as it is submitted. A playback request receives the completed file or waits for the job already running.
Only current room text is synthesized; unseen prompts or all possible rhymes are not guessed or generated.
Playback has priority over prefetch. Obsolete queued work is cancelled when a player's task changes.
A running synthesis finishes normally; CPU speed still matters if the player submits just before playback.

By default neural synthesis uses up to two threads (one on a two-core CPU).
Set `LOCALBOX_TTS_THREADS=1` to leave more resources for the game, or `LOCALBOX_TTS_PREFETCH=0` to disable prefetch.
Restart the server after changing these. Prefetch never downloads missing models.

Each Mad Verse City game has its own cache. `gameFinished`, `game/ended` or room closure removes that game's
MP3/WAV/temporary files and cancels queued jobs. A synthesis already running has its output deleted when it finishes.
The next game gets a new cache even if the room code is reused. Downloaded voice models remain installed.
Other games share a cache limited to 512 files, about 256 MiB and seven days, pruned after generation.
With the server stopped, the generated-audio cache can be deleted manually. Changing engine, voice or model changes the cache key.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Windows `DLL load failed … onnxruntime_pybind11_state` | Install the x64 Visual C++ runtime; verify 64-bit Python and package compatibility. |
| `No module named torch/piper/onnxruntime` | Install packages into the interpreter selected in TTS Python. |
| Piper `wave.Error: # channels not specified` | No audio chunks were produced; check model files, UTF-8 input and the worker's error log. |
| eSpeak not found | Install the system package and check PATH. |
| Silence | Use Preview and check server logs; the silence fallback deliberately keeps the game moving. |
| First phrase is slow | The model is loading, or CPU synthesis cannot keep up. Piper or eSpeak may be faster. |

LocalBox's Windows launch scripts and Python workers use UTF-8 for Cyrillic input/output.
ffmpeg in PATH or the runtime folder enables MP3 encoding and audio processing.
