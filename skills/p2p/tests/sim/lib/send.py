"""Wrapper around `agent_msg.py send` that auto-logs every invocation."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from lib.log import write_send_result

AGENT_MSG = os.path.expanduser("~/.claude/skills/p2p/agent_msg.py")


def send_and_log(
    *,
    peer: str,
    message_file: Path,
    log_path: Path,
    run_id: str,
    step_id: int,
    attempt_id: str,
    my_title: str | None = None,
    peer_surface: str | None = None,
    bootstrap_suggested_title: str | None = None,
    one_way: bool = False,
    workspace: str | None = None,
) -> dict[str, Any]:
    """Invoke agent_msg.py send and append a send_result event to log_path.

    Returns the parsed JSON stdout dict.
    """
    cmd: list[str] = ["python3", AGENT_MSG, "send",
                      "--peer", peer,
                      "--message-file", str(message_file)]
    if my_title:
        cmd += ["--my-title", my_title]
    if peer_surface:
        cmd += ["--peer-surface", peer_surface]
    if bootstrap_suggested_title:
        cmd += ["--bootstrap-suggested-title", bootstrap_suggested_title]
    if one_way:
        cmd += ["--one-way"]
    if workspace:
        cmd += ["--workspace", workspace]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    raw_stdout = json.loads(proc.stdout) if proc.stdout.strip() else {
        "ok": False, "code": "sim_send_no_stdout",
        "stderr": proc.stderr, "returncode": proc.returncode,
    }

    write_send_result(
        log_path,
        run_id=run_id, step_id=step_id, attempt_id=attempt_id,
        intended_peer=peer, raw_stdout=raw_stdout,
    )
    return raw_stdout
