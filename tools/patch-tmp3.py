#!/usr/bin/env python3
"""Connect a purchased Trivia Murder Party 3 installation to LocalBox."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
from setup import runtime
from setup.tmp3 import main

if __name__ == "__main__":
    runtime.activate()
    main()
