#!/usr/bin/env python3
"""Worker CLI: log a single inbound p2p frame to the worker's JSONL.

Usage (invoked by the worker LLM on every received message):
  python3 bin/log_inbound.py \\
    --log-path runs/<run_id>/worker_alpha.jsonl \\
    --run-id <run_id> --step-id <N> \\
    --raw-frame '[from: worker_bravo] COUNTER:{"value":5}'

Parses the frame's [from: X] header (and `| one-way` suffix), parses the
body, and appends one inbound_frame event.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Allow running from anywhere
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.log import write_inbound_frame
from lib.proto import parse_body, MessageClass

HEADER_RE = re.compile(r"^\[from:\s*(?P<from>[^\]|]+?)(?:\s*\|\s*(?P<oneway>one-way))?\s*\]\s*(?P<body>.*)$",
                       re.DOTALL)


def parse_frame(raw: str) -> tuple[str | None, str, bool]:
    m = HEADER_RE.match(raw)
    if not m:
        return None, raw, False
    from_title = m.group("from").strip()
    body = m.group("body").lstrip()
    one_way = m.group("oneway") is not None
    return from_title, body, one_way


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--log-path", required=True, type=Path)
    p.add_argument("--run-id", required=True)
    p.add_argument("--step-id", required=True, type=int)
    p.add_argument("--raw-frame", required=True)
    args = p.parse_args()

    from_title, body, one_way = parse_frame(args.raw_frame)
    parsed = parse_body(body)
    parse_status = "ok" if parsed.parse_error is None and parsed.kind != MessageClass.UNKNOWN else (
        parsed.parse_error or "unknown_namespace"
    )

    write_inbound_frame(
        args.log_path,
        run_id=args.run_id, step_id=args.step_id,
        raw_frame=args.raw_frame,
        from_title=from_title or "<unknown>",
        body=body,
        one_way=one_way,
        parse_status=parse_status,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
