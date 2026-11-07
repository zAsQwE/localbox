[Русский](dodo-re-mi.md) · [English](dodo-re-mi.en.md) · [Home](README.en.md)

# Dodo Re Mi performance rendering

Dodo Re Mi in The Jackbox Party Pack 10 normally sends recorded note data to Jackbox for an MP3 performance.
LocalBox mixes it locally through ffmpeg: notes, instrument samples, backing music and missed notes (flubs).
This lets the host move past “Waiting while performance processes” without the original rendering service.
Rendering is implemented in [server/lib/render.js](../server/lib/render.js).
Synthesized instrument timbres are approximate; rendering remains experimental.

## Requirements and assets

Enable Dodo Re Mi in setup, the startup menu or launcher Settings. Install ffmpeg into PATH or the runtime folder:
`runtime/ffmpeg.exe` on Windows, `runtime/ffmpeg` on Linux/macOS. Setup can install it automatically.
For manual Linux installation use `sudo apt install ffmpeg` or `sudo pacman -S ffmpeg`.
On Windows use an [ffmpeg build](https://github.com/GyanD/codexffmpeg/releases/latest) (`ffmpeg-…-essentials_build.zip`) and, if needed, the
[Visual C++ x64 runtime](https://aka.ms/vs/17/release/vc_redist.x64.exe).

Choose your installed Jackbox 10 folder during setup, or use **Settings → Dodo Re Mi → Import music**.
Music and available OGG samples are copied into LocalBox without changing game files.
You can enable rendering first and import music later.

```text
server/render/
  nopus-opus/
    instruments/<slug>/<name>.ogg
    songs/<slug>/backing.ogg
    songs/<slug>/backing_<locale>.ogg
  out/
```

Missing instrument samples download from `cdn.jackboxgames.com` and are cached for subsequent renders.
Backing tracks must come from your installed game: `games/NopusOpus/songs/<slug>/backing*.ogg`.
Without a backing track, rendering still produces instruments and flubs, without the song's backing music.
Instrument downloads need Internet on first use; previously cached assets can be used offline.

## Volume

| Setting / environment variable | Default | Effect |
| --- | --- | --- |
| Instrument volume / `LOCALBOX_RENDER_INSTR` | `4` | Raises instrument notes relative to backing music. |
| Backing music volume / `LOCALBOX_RENDER_BACKING` | `0.45` | Lower values reduce backing music. |

Save these in launcher Settings or set environment variables before starting:

```sh
LOCALBOX_RENDER_INSTR=5 LOCALBOX_RENDER_BACKING=0.4 ./start-server.sh --server -ip=192.168.1.20
```

The final mix uses an audio limiter. Volume changes apply to the next render.

## Protocol and diagnostics

The host creates `external-request/create` with a key such as `render:N`, service `song-render`,
and a payload containing the instrument, notes, flubs, duration and song slug.
LocalBox produces `server/render/out/<id>.mp3`, serves `/render/<id>.mp3`, and updates the entity:

```json
{"service":"song-render","status":"success","progress":1,
 "response":{"gameRenderUrl":"https://192.168.1.20/render/example.mp3"}}
```

The game reads `response.gameRenderUrl` after `status: success`; a `pending` update is sent first.
Actual render time depends on the CPU, samples and number of simultaneous jobs. The game has a rendering timeout.
For detailed logs:

```sh
LOCALBOX_DEBUG=1 ./start-server.sh --server -ip=192.168.1.20 2>&1 | tee localbox-full.log
```

Look for `[render]` requests, the selected instrument, ffmpeg errors and the resulting MP3 URL.
A subsequent `GET /render/…mp3` means the host downloaded the result.

| Symptom | Action |
| --- | --- |
| ffmpeg not found | Install it in PATH or runtime/. |
| Processing screen never finishes | Check rendering errors and ffmpeg's output. |
| MP3 ready but no GET request | Check the host's TLS trust and game-scoped CA options. |
| Instruments too quiet | Raise instrument volume or reduce backing music. |
| Only flubs are audible | Inspect instrument/sample resolution in the render log. |
