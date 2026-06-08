#!/usr/bin/env python3
"""afork.py — entry point for the ``afork`` agent fork launcher.

Thin, like fork_terminal.py: it puts its own directory on the import path and
hands off to ``aforklib``. Run it explicitly with python3 — the working
directory is the user's project, not the skill directory::

    python3 <skill-dir>/afork.py <runtime> [agent] \
            [--permission P] [--model M] [--effort E] \
            [--title T] [--cwd DIR] [--placement P] [--allow-unenforced]

afork builds a launch command for any coding agent (plain or definition-backed),
maps the declared permission posture to a runtime-enforced flag, and prints a
single ``ready_to_fork`` handoff (or a failure handoff) as JSON. It does not
fork — the calling agent passes the command to the tfork skill.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aforklib.cli import main  # noqa: E402  (import follows the path setup)

if __name__ == "__main__":
    sys.exit(main())
