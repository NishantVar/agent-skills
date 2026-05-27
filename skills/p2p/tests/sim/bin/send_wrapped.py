#!/usr/bin/env python3
"""Shared CLI: invoke lib.send.send_and_log with command-line args."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.send import send_and_log


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--log-path", required=True, type=Path)
    p.add_argument("--run-id", required=True)
    p.add_argument("--step-id", required=True, type=int)
    p.add_argument("--attempt-id", required=True)
    p.add_argument("--peer", required=True)
    p.add_argument("--message-file", required=True, type=Path)
    p.add_argument("--my-title", default=None)
    p.add_argument("--peer-surface", default=None)
    p.add_argument("--bootstrap-suggested-title", default=None)
    p.add_argument("--one-way", action="store_true")
    p.add_argument("--workspace", default=None)
    args = p.parse_args()

    result = send_and_log(
        peer=args.peer, message_file=args.message_file,
        log_path=args.log_path,
        run_id=args.run_id, step_id=args.step_id, attempt_id=args.attempt_id,
        my_title=args.my_title, peer_surface=args.peer_surface,
        bootstrap_suggested_title=args.bootstrap_suggested_title,
        one_way=args.one_way, workspace=args.workspace,
    )
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
