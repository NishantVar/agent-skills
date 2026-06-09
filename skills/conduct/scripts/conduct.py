#!/usr/bin/env python3
"""conduct — cmux control plane. Thin CLI entry; real code lives in flat
sibling modules in this same directory (cli, core, cmux, ownership, adapters,
errors). Running this file directly puts its own directory on the import path
automatically, so no path shim is needed."""

import sys

from cli import main


if __name__ == "__main__":
    sys.exit(main())
