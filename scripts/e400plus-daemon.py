#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "hidapi>=0.14",
#   "psutil>=5.9",
#   "PyYAML>=6",
# ]
# ///
"""Run the E400 daemon with uv-managed dependencies.

The local source tree is loaded relative to this wrapper, while uv installs
the external dependencies declared above.
"""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from e400plus.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["daemon", *sys.argv[1:]]))
