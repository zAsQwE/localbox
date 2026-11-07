#!/usr/bin/env python3
"""Make the LocalBox CA trusted for every Jackbox build (run by the installer after consent)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
from setup import runtime

if __name__ == "__main__":
    runtime.activate()
    from setup import certs, game_trust, platform as plat, settings
    if not certs.ensure_cert(plat.local_ip(), extra_names=["localhost"]):
        sys.exit(1)
    game_trust.heal()  # problems are logged; the launcher retries on every server start
    options = settings.load()
    options["game_trust"] = True   # the user agreed: the launcher keeps trust in sync
    settings.save(options)
