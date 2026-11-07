[Русский](install.md) · [English](install.en.md) · [Home](README.en.md)

# LocalBox installer

The installers are in **Assets** on the [Releases](https://github.com/zAsQwE/localbox/releases) page.
They download the latest stable LocalBox Release and whatever is missing: Python, Node.js, ffmpeg,
the web client and the chosen voices. Suitable programs that are already installed are reused.
Internet is needed only during installation.

## Windows

1. Run `setup.exe`. It does not ask for administrator rights.
2. Choose the language, the LocalBox folder (no spaces or non-Latin letters in the path) and voices.
3. Optional: Russian web client, Jackbox 10 folder for Dodo Re Mi, games folder for cheats, TMP3 patch.
4. Keep **Make the certificate trusted for Jackbox games** ticked and click **Download**.
   At the end Windows asks about the LocalBox certificate — answer Yes.
5. Click **Open LocalBox**. Later use the LocalBox shortcut or `start-server.bat`.

The installation log is `install.log` in the LocalBox folder.

## Linux

```sh
chmod +x setup-linux.run
./setup-linux.run
```

A window with the same settings opens. Without a display the questions are asked in the terminal. For missing
system packages setup asks for your password once; don't run setup itself through `sudo`.
The default folder is `~/.local/share/localbox`; LocalBox appears in the application menu.

Unattended installation:

```sh
./setup-linux.run --console --target "$HOME/LocalBox" --tts piper --voices ru_RU-denis-medium --ru
```

## Updates

In the launcher: **Check for updates → Update to …**. The archive is verified before files are replaced;
on failure the installation is rolled back. Settings, certificates, the client, voices and music are kept.
You can also run setup again and choose the same folder.

## For the author: build and release

You need Python 3.10+ and [NSIS](https://nsis.sourceforge.io/Download) (`makensis`) for `setup.exe`:

```sh
python3 tools/build-installers.py --version v1.2.0
```

`dist/` then holds `setup.exe`, `setup-linux.run`, `localbox-update.zip` and `SHA256SUMS`.
Settings, certificates, keys, clients and `node_modules` are not included.

**Testing before publishing.** A normal setup installs the published Release, not your fresh build.
To install the code inside the installer itself, run `setup.exe /local` or
`./setup-linux.run --local` and choose an empty folder.

**Release:**

1. The number in `version.json` (or `--version`) must match the tag, e.g. `1.2` and `v1.2.0`.
2. Attach all four files from `dist/` to the Release.
3. Publish it without the draft or pre-release marks: the installer skips those.
4. Test `setup.exe` / `setup-linux.run` from the Release page without switches, and the update from the
   launcher of an older version.

The Russian client `client-ru.zip` needs to be attached to at least one stable Release: the installer takes the
newest one. To add it to the build: `--client-ru-archive /path/to/client-ru.zip`.
