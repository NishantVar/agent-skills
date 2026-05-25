"""cmux transport: workspace-aware set-buffer + paste-buffer + Enter.

Every cmux call that targets a surface passes `--workspace <ws>` —
without it, cmux falls back to $CMUX_WORKSPACE_ID and cross-workspace
messages fail as "Surface is not a terminal". Per-op buffer names
(`p2p-<pid>-<nonce>`) keep concurrent senders from interleaving into a
single buffer slot.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import time


def is_command(text: str) -> bool:
    """True when `text` would open a slash-command / Codex plugin
    dropdown — i.e. starts the line with `/` or `$`. Those messages
    bypass the `[from: <me>]` prefix and need a real space keystroke
    after the paste to dismiss the dropdown before Enter."""
    return text.startswith(("/", "$"))


def _buffer_name() -> str:
    return f"p2p-{os.getpid()}-{secrets.token_hex(4)}"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


class TransportError(RuntimeError):
    """Raised when any underlying cmux call fails."""


def send_buffer(surface_ref: str, workspace_ref: str | None,
                text: str) -> None:
    """Set, paste, and submit `text` into `surface_ref`.

    `workspace_ref` is required for cross-workspace delivery; pass None
    only when the surface is in the caller's workspace AND you have
    confirmed that — there's no good reason to omit it from a routed
    send. The function still works with None, but routing becomes
    workspace-implicit.
    """
    name = _buffer_name()

    r = _run(["cmux", "set-buffer", "--name", name, "--", text])
    if r.returncode != 0:
        raise TransportError(
            f"cmux set-buffer failed: {r.stderr.strip()}")

    paste = ["cmux", "paste-buffer", "--name", name,
             "--surface", surface_ref]
    if workspace_ref:
        paste += ["--workspace", workspace_ref]
    r = _run(paste)
    if r.returncode != 0:
        raise TransportError(
            f"cmux paste-buffer failed: {r.stderr.strip()}")

    # Give the target CLI time to ingest the paste before the keystroke,
    # or it races and the message sits unsent.
    time.sleep(0.3)

    if is_command(text):
        space = ["cmux", "send", "--surface", surface_ref, " "]
        if workspace_ref:
            space += ["--workspace", workspace_ref]
        r = _run(space)
        if r.returncode != 0:
            raise TransportError(
                f"cmux send space failed: {r.stderr.strip()}")
        time.sleep(0.3)

    enter = ["cmux", "send-key", "--surface", surface_ref, "enter"]
    if workspace_ref:
        enter += ["--workspace", workspace_ref]
    r = _run(enter)
    if r.returncode != 0:
        raise TransportError(
            f"cmux send-key enter failed: {r.stderr.strip()}")


def read_screen(surface_ref: str, workspace_ref: str | None,
                lines: int = 300) -> str:
    cmd = ["cmux", "read-screen", "--surface", surface_ref,
           "--lines", str(lines)]
    if workspace_ref:
        cmd += ["--workspace", workspace_ref]
    r = _run(cmd)
    if r.returncode != 0:
        raise TransportError(
            f"cmux read-screen failed: {r.stderr.strip()}")
    return r.stdout


def rename_tab(surface_ref: str, workspace_ref: str | None,
               title: str) -> None:
    """Cosmetic only; failures are silent because the manifest is the
    authoritative routing key."""
    cmd = ["cmux", "rename-tab", "--surface", surface_ref, title]
    if workspace_ref:
        cmd += ["--workspace", workspace_ref]
    _run(cmd)
