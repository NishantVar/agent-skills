#!/usr/bin/env python3
"""Build a COUNTER body via proto.encode_counter, write it to a temp
file, and send through lib.send.send_and_log.

Workers use this on `SIM:PRIME ... role=sender` or on COUNTER forwarding
so they never have to inline-quote JSON in a shell command (which was
the root cause of the attempt_id=")" corruption observed in run
fbc3d78bad5f411a).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.proto import encode_counter
from lib.send import send_and_log


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--log-path", required=True, type=Path)
    p.add_argument("--run-id", required=True)
    p.add_argument("--step-id", required=True, type=int)
    p.add_argument("--sender", required=True,
                   help="this worker's title (goes into the COUNTER payload)")
    p.add_argument("--peer", required=True,
                   help="destination title (next_peer or override)")
    p.add_argument("--value", required=True, type=int)
    p.add_argument("--attempt-id", default=None,
                   help="optional; auto-minted if omitted")
    p.add_argument("--my-title", default=None,
                   help="set on first send only")
    p.add_argument("--peer-surface", default=None)
    p.add_argument("--one-way", action="store_true")
    p.add_argument("--workspace", default=None)
    args = p.parse_args()

    attempt_id = args.attempt_id or uuid.uuid4().hex
    body = encode_counter(
        run_id=args.run_id, step_id=args.step_id, attempt_id=attempt_id,
        sender=args.sender, value=args.value,
    )

    with tempfile.NamedTemporaryFile(
            mode="w", suffix=".counter.txt", delete=False) as tf:
        tf.write(body)
        msg_path = Path(tf.name)

    result = send_and_log(
        peer=args.peer, message_file=msg_path,
        log_path=args.log_path,
        run_id=args.run_id, step_id=args.step_id, attempt_id=attempt_id,
        my_title=args.my_title, peer_surface=args.peer_surface,
        one_way=args.one_way, workspace=args.workspace,
    )
    print(json.dumps({"attempt_id": attempt_id, "send": result}))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
