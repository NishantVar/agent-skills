"""Line-delimited JSON-RPC over text streams — the MCP stdio transport.

One JSON object per line. No `mcp` SDK dependency (spec §11). stderr is the
only safe debug channel; never write logs to the JSON-RPC stdout stream.
"""

from __future__ import annotations

import json
import sys


def iter_requests(stream):
    """Yield parsed JSON objects, one per non-blank line. Bad lines skipped."""
    for line in stream:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            log(f"non-JSON line ignored: {line[:120]!r}")


def send(stream, obj) -> None:
    stream.write(json.dumps(obj) + "\n")
    stream.flush()


def log(msg: str) -> None:
    print(f"[flux-mcp] {msg}", file=sys.stderr, flush=True)
