#!/usr/bin/env python3
"""fork_terminal.py — entry point for the ``tfork`` deterministic terminal fork.

This file is intentionally thin: it puts its own directory on the import path
and hands off to ``tforklib``, the package that holds all the logic. Run it
explicitly with python3 — the working directory is the user's project, not the
skill directory::

    python3 <skill-dir>/fork_terminal.py \
            --placement {right,left,top,bottom,new-workspace} \
            [--anchor <surface-ref-or-tab-title>] \
            [--type {agent,command}] [--delay N] -- <command...>

The invocation contract and JSON output format are documented in
``tforklib/cli.py``; the package is split there by concern.
"""

import sys
from pathlib import Path

# Running this file as a script already puts its directory on sys.path; the
# explicit insert also covers the case where it is imported instead.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tforklib.cli import main  # noqa: E402  (import follows the path setup)

if __name__ == "__main__":
    sys.exit(main())
