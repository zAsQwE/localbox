#!/usr/bin/env python3
"""Download the jackbox.ru web client into client-ru/, using client/ as the file index.

Layout on jackbox.ru: every game lives in a base such as main/ppad/drawful3 (same files
as the English client) or the_box/ppad/drawful3 (translated files with the same names),
each with script.js and assets/. The English client (client/, jackbox.tv) uses flat
bases such as main/ppad-drawful3. This script maps one path to the other with only the
base changing, e.g.

    main/ppad-drawful3/assets/BgspNlgv.png
      -> main/ppad/drawful3/assets/BgspNlgv.png
      -> the_box/ppad/drawful3/assets/BgspNlgv.png

and saves every file under its jackbox.ru path. The LocalBox server maps flat requests
to nested files itself (server/lib/client-paths.js).

    python3 tools/fetch-jackbox-ru.py                       # everything
    python3 tools/fetch-jackbox-ru.py --only the_box/ppad   # one part
    python3 tools/fetch-jackbox-ru.py --dry-run             # only list what would be fetched
    python3 tools/fetch-jackbox-ru.py --no-main             # only the_box/ + shell; main/ = client/

Resumable: existing files are skipped (use --force to re-download). Needs internet.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path, PurePosixPath
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = Path(__file__).resolve().parents[1]
ROOT_FILES = ("index.html", "settings.json", "achievements.json", "manifest.webmanifest",
              "favicon.ico", "favicon-32.png", "apple-touch-icon.png", "ach.mp3", "robots.txt")
TEXT = {".js", ".css", ".html", ".json", ".webmanifest", ".txt", ".svg"}
SAFE = re.compile(r"^[A-Za-z0-9@_.~+-]+(?:/[A-Za-z0-9@_.~+-]+)*$")
# A game base listed by the jackbox.ru shell: main/pp7/quiplash3, the_box/ppad/drawful3, main/@connect.
BASE = re.compile(r'["\'`]((?:main|the_box)/(?:[A-Za-z0-9@_-]+)(?:/[A-Za-z0-9_-]+){0,2})["\'`]')
ASSET_EXT = r"(?:png|jpe?g|webp|gif|svg|mp3|ogg|wav|m4a|mp4|webm|json|js|css|woff2?|ttf|otf|txt|atlas|fnt)"


def clean(relative):
    """A safe repository-relative POSIX path, or None."""
    relative = urllib.parse.unquote(str(relative)).split("?", 1)[0].split("#", 1)[0].lstrip("/")
    path = PurePosixPath(relative)
    if not relative or any(part in ("", ".", "..") or part.startswith(".") for part in path.parts):
        return None
    return relative if SAFE.match(relative) else None


def flat_base(base):
    """main/ppad/drawful3 or the_box/ppad/drawful3 -> main/ppad-drawful3 (English client layout)."""
    parts = base.split("/")
    if len(parts) == 2:
        return "main/" + parts[1]
    return "main/" + "-".join(parts[1:])


# The jackbox.ru bundles load untranslated files from the English CDN (flat layout),
# and some stylesheets name jackbox.ru's mirrors, which serve the same paths.
CDN_HOSTS = ("bundles.jackbox.tv", "jackbox.tv")
MIRROR_HOSTS = ("jackbox.ru", "www.jackbox.ru", "jackbox.su", "www.jackbox.su")


def references(text, origin_host, here, flat_to_nested=None):
    """Paths referenced by a downloaded text file: same-host URLs, English CDN URLs mapped to
    their jackbox.ru base (main/ppad-drawful3/x -> main/ppad/drawful3/x), and relative files."""
    found = set()
    same = {origin_host, *MIRROR_HOSTS}
    for match in re.finditer(r"https?://(?:" + "|".join(map(re.escape, same)) + r")/([^\"'`\s)<>\\]+)", text):
        found.add(match.group(1))
    for match in re.finditer(r"https?://(?:" + "|".join(map(re.escape, CDN_HOSTS)) + r")/([^\"'`\s)<>\\]+)", text):
        path = match.group(1)
        head, _, rest = path.partition("/")
        flat = head + "/" + rest.split("/", 1)[0] if rest else head
        nested = (flat_to_nested or {}).get(flat)
        if nested and "/" in rest:
            found.add(nested + "/" + rest.split("/", 1)[1])
    directory = str(PurePosixPath(here).parent)
    for match in re.finditer(r"""["'`(]\s*(\.{0,2}/?(?:[A-Za-z0-9@_.~+-]+/)*[A-Za-z0-9@_.~+-]+\.""" + ASSET_EXT + r""")\s*["'`)]""", text):
        value = match.group(1)
        if value.startswith(".."):
            continue  # bundler source keys (../assets/shareables/...), not URLs
        if value.startswith("/"):
            found.add(value.lstrip("/"))
        elif "/" in value or value.startswith(".") or here.endswith(".css"):
            # CSS url(B8C8i_h7.woff2) is relative to the stylesheet's own folder.
            joined = os.path.normpath(os.path.join(directory, value)).replace(os.sep, "/")
            found.add(joined)
    return {path for path in (clean(item) for item in found) if path}


class Fetcher:
    def __init__(self, origin, dst, force=False, dry=False, timeout=30, log=print):
        self.origin = origin.rstrip("/")
        self.host = urllib.parse.urlsplit(self.origin).netloc
        self.dst, self.force, self.dry, self.timeout, self.log = Path(dst), force, dry, timeout, log
        self.lock = threading.Lock()
        self.stats = {"downloaded": 0, "existing": 0, "missing": 0, "failed": 0}

    def _count(self, key):
        with self.lock:
            self.stats[key] += 1

    def get(self, relative):
        """(bytes or None, from_cache). None = the site does not have this file."""
        target = self.dst / relative
        if target.is_file() and target.stat().st_size and not self.force:
            self._count("existing")
            return (target.read_bytes() if Path(relative).suffix in TEXT else b""), True
        if self.dry and Path(relative).suffix not in TEXT:
            self.log("would fetch " + relative)
            return None, False
        url = self.origin + "/" + urllib.parse.quote(relative)
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (LocalBox client mirror)"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = response.read()
                    kind = response.headers.get("Content-Type", "")
                break
            except urllib.error.HTTPError as error:
                if error.code in (403, 404, 410):
                    self._count("missing")
                    return None, False
                if attempt == 2:
                    self.log(f"error {error.code} {relative}")
                    self._count("failed")
                    return None, False
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
                if attempt == 2:
                    self.log(f"error {error} {relative}")
                    self._count("failed")
                    return None, False
            time.sleep(1 + attempt)
        # jackbox.ru answers some missing paths with its index page (HTTP 200, text/html).
        if Path(relative).suffix != ".html" and "text/html" in kind.lower():
            self._count("missing")
            return None, False
        if not data:
            self._count("missing")
            return None, False
        if self.dry:  # text files are read to discover more paths, but never written
            self.log("would fetch " + relative)
            return data, False
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".part")
        temporary.write_bytes(data)
        temporary.replace(target)
        self._count("downloaded")
        return data, False


def english_hints(src, base):
    """Files of the matching English game (client/main/ppad-drawful3), as paths inside `base`."""
    directory = Path(src) / flat_base(base)
    if not directory.is_dir():
        return set()
    hints = set()
    for file in directory.rglob("*"):
        if file.is_file() and not file.is_symlink():
            relative = file.relative_to(directory).as_posix()
            # English JS/CSS bundles carry their own hashed names; jackbox.ru uses script.js.
            if "/" not in relative and file.suffix in (".js", ".css"):
                continue
            hints.add(base + "/" + relative)
    return hints


def mirror(origin="https://jackbox.ru", src=REPO / "client", dst=REPO / "client-ru", only=None,
           include_main=True, workers=8, force=False, dry=False, log=print):
    fetcher = Fetcher(origin, dst, force=force, dry=dry, log=log)
    wanted = lambda path: not only or path.startswith(only)
    seen, lock = set(), threading.Lock()

    def take(paths):
        fresh = []
        with lock:
            for path in paths:
                if path and path not in seen and wanted(path) and (include_main or not path.startswith("main/") or
                                                                   path.startswith(("main/@", "main/internal"))):
                    seen.add(path)
                    fresh.append(path)
        return fresh

    flat_to_nested = {}

    def visit(path):
        data, _cached = fetcher.get(path)
        if data and Path(path).suffix in (".js", ".css", ".html"):
            return take(references(data.decode("utf-8", "replace"), fetcher.host, path, flat_to_nested))
        return []

    # 1) The shell, and the game bases it lists.
    shell = []
    for name in ROOT_FILES:
        shell.append(name)
    index, _ = fetcher.get("index.html")
    if index:
        shell += [path for path in (clean(m) for m in re.findall(r'(?:src|href)="([^"#:?]+)"', index.decode("utf-8", "replace"))) if path]
    bases = set()
    for name in [path for path in shell if path.endswith(".js")]:
        data, _ = fetcher.get(name)
        if data:
            bases |= set(BASE.findall(data.decode("utf-8", "replace")))
    flat_to_nested.update({flat_base(base): base for base in bases if base.startswith("main/")})
    log(f"jackbox.ru: {len(bases)} game bases ({sum(b.startswith('the_box/') for b in bases)} in the_box/)")

    queue = take(shell)
    for base in sorted(bases):
        # The shell loads each game's styles from <base>/assets/style-0.css (built, not quoted).
        queue += take([base + "/script.js", base + "/assets/style-0.css"])
        queue += take(sorted(english_hints(src, base)))

    # 2) Download breadth-first; text files add the paths they reference.
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        while queue:
            batch, queue = queue, []
            for more in pool.map(visit, batch):
                queue += more
    log("done: " + ", ".join(f"{key} {value}" for key, value in fetcher.stats.items()))
    return fetcher.stats


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--origin", default="https://jackbox.ru", help="site to mirror (default https://jackbox.ru)")
    parser.add_argument("--src", default=str(REPO / "client"), help="English client used as the file index")
    parser.add_argument("--dst", default=str(REPO / "client-ru"), help="destination folder")
    parser.add_argument("--only", help="path prefix, e.g. the_box/ppad or main/pp7/quiplash3")
    parser.add_argument("--no-main", action="store_true", help="skip main/<pack>/<game>: identical to client/")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--force", action="store_true", help="re-download existing files")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    stats = mirror(args.origin, args.src, args.dst, args.only, not args.no_main, args.concurrency, args.force, args.dry_run)
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
