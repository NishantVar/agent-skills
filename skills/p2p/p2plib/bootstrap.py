"""First-contact bootstrap text for messaging an already-live peer,
plus a scrollback parser used only when explicit flags aren't supplied.
p2p does not spawn agents, so there is no spawn-payload generation here.
"""

from __future__ import annotations

import re

BOOTSTRAP_TAG = "[p2p-bootstrap]"

# Accept both the new keys (peer_title, suggested_title) and the legacy
# keys (peer_name, suggested_name). New writes only emit the title
# form; parsing tolerates the old form for one release.
_KV_RE = re.compile(
    r"^(peer_title|peer_name|peer_surface|peer_workspace|peer_window|"
    r"suggested_title|suggested_name)\s*=\s*(.+)$")


def build_bootstrap(peer_title: str, peer_surface: str,
                    suggested_title: str | None,
                    first_message: str | None,
                    one_way: bool = False,
                    peer_workspace: str | None = None,
                    peer_window: str | None = None) -> str:
    suggest_line = (f"suggested_title={suggested_title}\n"
                    if suggested_title else "")
    workspace_line = (f"peer_workspace={peer_workspace}\n"
                      if peer_workspace else "")
    window_line = (f"peer_window={peer_window}\n"
                   if peer_window else "")
    if one_way:
        trailer = (
            f"Please load the p2p skill and register yourself with a "
            f"stable short title (use the suggested title above, or "
            f"your cmux tab title, when you do not already have one). "
            f"This is a one-way notification — no reply is expected."
        )
    else:
        trailer = (
            f"Please load the p2p skill, register yourself with a "
            f"stable short title (use the suggested title above, or "
            f"your cmux tab title, when you do not already have one), "
            f"and reply when ready."
        )
    body = (
        f"{BOOTSTRAP_TAG} You have an incoming peer-messaging connection.\n"
        f"peer_title={peer_title}\n"
        f"peer_surface={peer_surface}\n"
        f"{workspace_line}"
        f"{window_line}"
        f"{suggest_line}"
        f"{trailer}"
    )
    if first_message and first_message.strip():
        marker = " (one-way, no reply expected)" if one_way else ""
        body += (f"\n\nFirst message from {peer_title}{marker}: "
                 f"{first_message}")
    return body


def parse_bootstrap_text(text: str) -> dict | None:
    """Find the most recent [p2p-bootstrap] block in `text` and extract
    peer_title (or legacy peer_name) / peer_surface / suggested_title
    (or legacy suggested_name). Returns a dict with normalized keys
    (peer_title, peer_surface, suggested_title) or None when no block
    is found or required fields are missing."""
    lines = text.splitlines()
    idx = None
    for i in range(len(lines) - 1, -1, -1):
        if BOOTSTRAP_TAG in lines[i]:
            idx = i
            break
    if idx is None:
        return None
    raw: dict[str, str] = {}
    for ln in lines[idx:idx + 20]:
        m = _KV_RE.match(ln.strip())
        if m:
            raw[m.group(1)] = m.group(2).strip()
    out: dict[str, str] = {}
    out["peer_title"] = raw.get("peer_title") or raw.get("peer_name") or ""
    out["peer_surface"] = raw.get("peer_surface", "")
    if raw.get("peer_workspace"):
        out["peer_workspace"] = raw["peer_workspace"]
    if raw.get("peer_window"):
        out["peer_window"] = raw["peer_window"]
    suggested = raw.get("suggested_title") or raw.get("suggested_name")
    if suggested:
        out["suggested_title"] = suggested
    if not out["peer_title"] or not out["peer_surface"]:
        return None
    return out
