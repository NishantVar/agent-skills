"""Bootstrap text + spawn-payload generation, plus a scrollback parser
used only when explicit flags aren't supplied.
"""

from __future__ import annotations

import os
import re
import secrets

BOOTSTRAP_TAG = "[p2p-bootstrap]"

_KV_RE = re.compile(r"^(peer_name|peer_surface|suggested_name)\s*=\s*(.+)$")


def build_bootstrap(peer_name: str, peer_surface: str,
                    suggested_name: str | None,
                    first_message: str | None,
                    one_way: bool = False) -> str:
    suggest_line = (f"suggested_name={suggested_name}\n"
                    if suggested_name else "")
    if one_way:
        trailer = (
            f"Please load the p2p skill and register yourself with a "
            f"stable short name (use the suggested name above, or your "
            f"cmux tab title, when you do not already have one). This "
            f"is a one-way notification — no reply is expected."
        )
    else:
        trailer = (
            f"Please load the p2p skill, register yourself with a "
            f"stable short name (use the suggested name above, or your "
            f"cmux tab title, when you do not already have one), and "
            f"reply when ready."
        )
    body = (
        f"{BOOTSTRAP_TAG} You have an incoming peer-messaging connection.\n"
        f"peer_name={peer_name}\n"
        f"peer_surface={peer_surface}\n"
        f"{suggest_line}"
        f"{trailer}"
    )
    if first_message and first_message.strip():
        marker = " (one-way, no reply expected)" if one_way else ""
        body += (f"\n\nFirst message from {peer_name}{marker}: "
                 f"{first_message}")
    return body


def build_spawn_bootstrap(peer_name: str, peer_surface: str,
                          suggested_name: str | None,
                          first_message: str | None,
                          one_way: bool = False) -> str:
    """Same as build_bootstrap but phrased for a freshly-spawned agent
    that has no prior context. The tfork skill is expected to deliver
    this as the new agent's first user-turn prompt via whatever
    delayed-input mechanism it currently exposes — p2p does not
    prescribe a flag."""
    suggest_line = (f"suggested_name={suggested_name}\n"
                    if suggested_name else "")
    if one_way:
        trailer = (
            f"Pick a short snake_case name for yourself (or accept the "
            f"suggested_name if provided), load the p2p skill, and "
            f"register. This is a one-way notification — no reply is "
            f"expected."
        )
    else:
        trailer = (
            f"Pick a short snake_case name for yourself (or accept the "
            f"suggested_name if provided), load the p2p skill, register, "
            f"and reply."
        )
    body = (
        f"{BOOTSTRAP_TAG} You were spawned by peer-messaging.\n"
        f"peer_name={peer_name}\n"
        f"peer_surface={peer_surface}\n"
        f"{suggest_line}"
        f"{trailer}"
    )
    if first_message and first_message.strip():
        marker = " (one-way, no reply expected)" if one_way else ""
        body += (f"\n\nFirst message from {peer_name}{marker}: "
                 f"{first_message}")
    return body


def write_spawn_payload(peer_name: str, payload: str) -> str:
    """Write spawn payload to /tmp with O_EXCL 0600. Returns the path."""
    path = (f"/tmp/p2p-spawn-{peer_name}-{os.getpid()}-"
            f"{secrets.token_hex(4)}.txt")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, payload.encode())
    finally:
        os.close(fd)
    return path


def parse_bootstrap_text(text: str) -> dict | None:
    """Find the most recent [p2p-bootstrap] block in `text` and extract
    peer_name / peer_surface / suggested_name. Returns None when no
    block is found or required fields are missing."""
    lines = text.splitlines()
    idx = None
    for i in range(len(lines) - 1, -1, -1):
        if BOOTSTRAP_TAG in lines[i]:
            idx = i
            break
    if idx is None:
        return None
    out: dict[str, str] = {}
    for ln in lines[idx:idx + 20]:
        m = _KV_RE.match(ln.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
    if not out.get("peer_name") or not out.get("peer_surface"):
        return None
    return out
