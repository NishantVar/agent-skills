"""Append-only JSONL logger for p2p-sim workers and driver.

Two event types:
  - send_result : every agent_msg.py invocation
  - inbound_frame : every received p2p message (counter, SIM:, DEATH_NOTICE:)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append(log_path: Path, record: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, separators=(",", ":"), sort_keys=False)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def write_send_result(
    log_path: Path,
    *,
    run_id: str,
    step_id: int,
    attempt_id: str,
    intended_peer: str,
    raw_stdout: dict[str, Any],
) -> None:
    """Log one send_result event derived from agent_msg.py JSON stdout."""
    rec = {
        "event": "send_result",
        "ts": _now_iso(),
        "run_id": run_id,
        "step_id": step_id,
        "attempt_id": attempt_id,
        "intended_peer": intended_peer,
        "raw_stdout": raw_stdout,
        "observed_code": raw_stdout.get("code"),
        "observed_kind": raw_stdout.get("kind"),
        "peer_status": raw_stdout.get("peer_status"),
        "resolved_by": raw_stdout.get("resolved_by"),
        "payload_file": raw_stdout.get("payload_file"),
        "action_required": raw_stdout.get("action_required"),
        "retryable": raw_stdout.get("retryable"),
        "handoff_skill": raw_stdout.get("handoff_skill"),
        "candidates": raw_stdout.get("candidates"),
        "one_way": raw_stdout.get("one_way"),
    }
    _append(log_path, rec)


def write_inbound_frame(
    log_path: Path,
    *,
    run_id: str,
    step_id: int,
    raw_frame: str,
    from_title: str,
    body: str,
    one_way: bool,
    parse_status: str,
) -> None:
    """Log one inbound_frame event for a received p2p message."""
    rec = {
        "event": "inbound_frame",
        "ts": _now_iso(),
        "run_id": run_id,
        "step_id": step_id,
        "raw_frame": raw_frame,
        "from_title": from_title,
        "body": body,
        "one_way": one_way,
        "parse_status": parse_status,
    }
    _append(log_path, rec)
