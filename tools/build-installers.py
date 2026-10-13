#!/usr/bin/env python3
"""Сборка Windows setup.exe (NSIS) и самораспаковывающегося Linux setup-linux.run."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "installer"))
from install import payload_files


def linux_bundle(stage, output):
    header = '''#!/bin/sh
# LocalBox: самораспаковывающийся установщик Linux.
set -eu
archive_line=$(awk '/^__LOCALBOX_PAYLOAD__$/ {print NR+1; exit}' "$0")
if [ "${1:-}" = "--extract-to" ]; then
    [ "$#" -eq 2 ] || { echo 'Использование: setup-linux.run --extract-to ПАПКА' >&2; exit 2; }
    mkdir -p "$2"
    tail -n +"$archive_line" "$0" | tar -xz -C "$2"
    exit 0
fi
localbox_extract=$(mktemp -d "${TMPDIR:-/tmp}/localbox-setup.XXXXXX")
trap 'rm -rf "$localbox_extract"' EXIT HUP INT TERM
tail -n +"$archive_line" "$0" | tar -xz -C "$localbox_extract"
export LOCALBOX_BUNDLE_SOURCE="$localbox_extract"
bash "$localbox_extract/setup.sh" "$@"
exit $?
__LOCALBOX_PAYLOAD__
'''
    with output.open("wb") as file:
        file.write(header.encode("utf-8"))
        with tarfile.open(fileobj=file, mode="w:gz") as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    info = archive.gettarinfo(str(path), arcname=str(path.relative_to(stage)))
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with path.open("rb") as source:
                        archive.addfile(info, source)
    output.chmod(0o755)


def build(output_dir=None, windows=True, linux=True, makensis=None):
    output_dir = Path(output_dir or ROOT / "dist").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    compiler = makensis or os.environ.get("MAKENSIS") or shutil.which("makensis")
    if windows and not compiler:
        raise RuntimeError("Для setup.exe нужен NSIS (makensis). Установите NSIS или передайте --makensis /путь/makensis.")
    with tempfile.TemporaryDirectory(prefix="localbox-build-") as temp:
        stage = Path(temp) / "payload"
        stage.mkdir()
        for relative in payload_files(ROOT):
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        manifest = {str(path.relative_to(stage)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(stage.rglob("*")) if path.is_file()}
        (stage / "installer" / "payload-sha256.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if windows:
            subprocess.run([str(compiler), "-V2", "-INPUTCHARSET", "UTF8", f"-DPAYLOAD_DIR={stage}",
                            f"-DOUTPUT_FILE={output_dir / 'setup.exe'}", str(ROOT / "installer" / "localbox.nsi")], check=True)
        if linux:
            linux_bundle(stage, output_dir / "setup-linux.run")
    artifacts = [output_dir / name for enabled, name in ((windows, "setup.exe"), (linux, "setup-linux.run")) if enabled]
    (output_dir / "SHA256SUMS").write_text("".join(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n" for path in artifacts), encoding="utf-8")
    for path in artifacts:
        print(f"Готово: {path} ({path.stat().st_size:,} байт)")
    return artifacts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir")
    parser.add_argument("--makensis")
    parser.add_argument("--linux-only", action="store_true")
    parser.add_argument("--windows-only", action="store_true")
    args = parser.parse_args()
    if args.linux_only and args.windows_only:
        parser.error("Выберите один фильтр платформы.")
    try:
        build(args.output_dir, not args.linux_only, not args.windows_only, args.makensis)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
