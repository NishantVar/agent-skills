#!/usr/bin/env python3
"""p2p messaging — thin CLI entry. Real code lives in `p2plib/`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from p2plib.cli import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
