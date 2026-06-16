#!/usr/bin/env python3
"""flux-mcp — stdio MCP gateway over the p2p / afork / tfork skill binaries.

Thin entry: parse --scope, put the skill dir on the import path, and hand off
to fluxmcplib.server. Vendored JSON-RPC (no `mcp` SDK). See SKILL.md for host
wiring (Claude mcpServers / codex config.toml).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fluxmcplib.server import main  # noqa: E402


def _parse():
    p = argparse.ArgumentParser(prog="flux-mcp")
    p.add_argument("--scope", choices=["comms", "orchestrator"],
                   default="comms",
                   help="comms → p2p only (default); orchestrator → p2p+afork+tfork")
    return p.parse_args()


if __name__ == "__main__":
    sys.exit(main(_parse().scope))
