#!/usr/bin/env python3
"""Fetch the latest stable release as a verified, fresh installation source."""

if __package__:
    from .i18n import tr
else:
    from i18n import tr

import argparse
from pathlib import Path
import shutil
import sys
import zipfile

from update import ASSET_NAME, MANIFEST, download_release, latest_release, validate_archive


def fetch_latest(destination, log=print):
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(tr('Папка загрузки Release должна быть пустой.'))
    log(tr('Проверяю последний стабильный Release LocalBox…'))
    release = latest_release()
    if release is None:
        raise RuntimeError(tr('Нет опубликованного стабильного Release LocalBox.'))
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / ASSET_NAME
    payload = destination / "payload"
    try:
        download_release(release, archive, log)
        manifest = validate_archive(archive, release["tag_name"])
        payload.mkdir()
        with zipfile.ZipFile(archive) as package:
            for name in (*manifest, MANIFEST):
                file = payload / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(package.read(name))
                if file.suffix == ".sh":
                    file.chmod(0o755)
        (destination / "release-tag.txt").write_text(release["tag_name"], encoding="utf-8")
        log(tr('Устанавливаю Release {0}.', release['tag_name']))
        return payload
    except Exception:
        shutil.rmtree(payload, ignore_errors=True)
        raise
    finally:
        archive.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=tr('Загрузить последний стабильный Release LocalBox'))
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    try:
        fetch_latest(args.destination)
    except Exception as error:
        print(tr('Не удалось загрузить Release: {0}', error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
