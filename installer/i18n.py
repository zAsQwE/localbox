"""Allow installer entry points and private updater packages to share translations."""

import sys
from pathlib import Path

_launcher = str(Path(__file__).resolve().parents[1] / "launcher")
if _launcher not in sys.path:
    sys.path.insert(0, _launcher)

from setup.i18n import detect, language, normalize, set_language, tr
