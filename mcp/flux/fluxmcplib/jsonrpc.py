"""Line-delimited JSON-RPC over text streams — the MCP stdio transport.

One JSON object per line. No `mcp` SDK dependency (spec §11). stderr is the
only safe debug channel; never write logs to the JSON-RPC stdout stream.
"""

from __future__ import annotations

import json
import sys


def iter_requests(stream):
    """Yield parsed JSON request objects (dicts), one per non-blank line.

    Blank lines, non-JSON lines, and non-object JSON (arrays, scalars) are
    skipped — a malformed line must never crash the dispatch loop.
    """
    for line in stream:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            log(f"non-JSON line ignored: {line[:120]!r}")
            continue
        if not isinstance(obj, dict):
            log(f"non-object JSON ignored: {line[:120]!r}")
            continue
        yield obj


def send(stream, obj) -> None:
    stream.write(json.dumps(obj) + "\n")
    stream.flush()


def log(msg: str) -> None:
    print(f"[flux-mcp] {msg}", file=sys.stderr, flush=True)
