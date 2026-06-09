"""The cmux backend seam.

Every cmux subprocess call lives here and nowhere else, so the ownership and
lifecycle logic in the rest of the skill stays portable beyond cmux (spec §7).
The functions return plain Python data (dicts, lists, strings); they never raise
on a cmux non-zero exit — they degrade to empty/None so callers fail closed
rather than crash. Injection helpers (``send`` / ``send_key``) DO raise
``CmuxError`` because a half-delivered keystroke sequence must surface loudly.

cmux note: ``cmux send`` does NOT press Enter — a paste/text send must be
followed by an explicit ``send-key Enter`` (see ``send_key``).
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Optional


class CmuxError(RuntimeError):
    """A cmux call that must not silently fail (injection / lifecycle)."""


def _run(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(cmd, 255, "", str(exc))


def _run_json(cmd: list[str], timeout: int = 15) -> Any:
    r = _run(cmd, timeout=timeout)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


# ---------------- discovery (read-only) ----------------

def identify() -> dict:
    """`cmux identify` with both refs and UUIDs. Returns {} on failure."""
    return _run_json(["cmux", "--json", "identify", "--id-format", "both"]) or {}


def caller_surface_uuid() -> Optional[str]:
    """The caller's own surface UUID. Prefers $CMUX_SURFACE_ID, falls back to
    `cmux identify`'s caller.surface_id. None when neither resolves."""
    env = os.environ.get("CMUX_SURFACE_ID")
    if env:
        # $CMUX_SURFACE_ID may carry a UUID or a `surface:N` ref. If it is a
        # ref, resolve it through the tree below; a bare UUID is returned as-is.
        if "-" in env and not env.startswith("surface:"):
            return env
    data = identify()
    caller = (data.get("caller") or {}) if isinstance(data, dict) else {}
    return caller.get("surface_id") or None


def tree() -> dict:
    """`cmux tree --all` with both refs and UUIDs. {} on failure."""
    return _run_json(
        ["cmux", "--json", "tree", "--all", "--id-format", "both"]) or {}


def _iter_surfaces(t: dict):
    """Yield (workspace_node, window_node, surface_node) for every surface."""
    for window in t.get("windows", []) or []:
        for ws in window.get("workspaces", []) or []:
            for pane in ws.get("panes", []) or []:
                for s in pane.get("surfaces", []) or []:
                    yield ws, window, s


def surface_index(t: Optional[dict] = None) -> dict:
    """Map surface UUID -> rich record. Includes the disposable `surface:N`
    ref, title, type, tty, and current workspace/window — all derived live,
    never stored. Keyed on UUID because that is conduct's identity contract."""
    t = tree() if t is None else t
    out: dict[str, dict] = {}
    for ws, window, s in _iter_surfaces(t):
        uuid = s.get("id")
        if not uuid:
            continue
        out[uuid] = {
            "uuid": uuid,
            "surface_ref": s.get("ref") or "",
            "title": s.get("title") or "",
            "type": s.get("type") or "",
            "tty": s.get("tty") or "",
            "workspace_ref": ws.get("ref") or "",
            "workspace_title": ws.get("title") or "",
            "window_ref": window.get("ref") or "",
        }
    return out


def live_surface_uuids(t: Optional[dict] = None) -> set:
    """Set of surface UUIDs currently in the live cmux tree. The membership
    test that powers orphan-reclaim (spec §3.3)."""
    t = tree() if t is None else t
    return {s.get("id") for _, _, s in _iter_surfaces(t) if s.get("id")}


def resolve_to_uuid(agent_ref: str, t: Optional[dict] = None) -> Optional[str]:
    """Resolve a `--agent` value to a surface UUID at call time.

    Accepts a bare UUID (returned if live), or a `surface:N` short ref
    (resolved through the live tree). Returns None when nothing matches.
    """
    idx = surface_index(t)
    if agent_ref in idx:  # already a live UUID
        return agent_ref
    for uuid, rec in idx.items():
        if rec["surface_ref"] == agent_ref:
            return uuid
    return None


def runtime_processes() -> dict:
    """Map surface UUID -> list of foreground process names, from
    `cmux top --all --processes`. Used to identify each target's runtime.

    Takes no tree argument: process attribution comes from `cmux top`, a
    distinct command from `cmux tree`, so it always issues its own call.
    Empty dict on failure (callers then fail closed on unknown runtime)."""
    data = _run_json(["cmux", "--json", "top", "--all", "--processes"])
    if not isinstance(data, dict):
        return {}
    out: dict[str, list] = {}

    def walk(node):
        if isinstance(node, dict):
            if node.get("kind") == "surface":
                uuid = _surface_uuid_from_top(node)
                if uuid is not None:
                    out[uuid] = _process_names(node.get("processes", []) or [])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(data)
    return out


def _surface_uuid_from_top(node: dict) -> Optional[str]:
    """top surface nodes don't carry the surface UUID at top level, but their
    child processes do (`cmux_surface_id`). Lift it from the first process."""
    direct = node.get("id") or node.get("surface_id")
    if direct:
        return direct
    for p in node.get("processes", []) or []:
        sid = p.get("cmux_surface_id")
        if sid:
            return sid
    return None


def _process_names(processes: list) -> list:
    names = []
    for p in processes:
        n = (p.get("name") or "").strip()
        if n:
            names.append(n)
    return names


def read_screen(surface_ref: str, workspace_ref: Optional[str],
                lines: int = 60) -> str:
    """Scrape a surface's visible screen (for claude's `ctx:NN%` status line).
    Returns '' on failure — context extraction degrades to null, never raises."""
    cmd = ["cmux", "read-screen", "--surface", surface_ref,
           "--lines", str(lines)]
    if workspace_ref:
        cmd += ["--workspace", workspace_ref]
    r = _run(cmd)
    return r.stdout if r.returncode == 0 else ""


# ---------------- injection (must raise) ----------------

def send_text(surface_ref: str, workspace_ref: Optional[str],
              text: str) -> None:
    """Type literal `text` into a surface. Does NOT press Enter — follow with
    send_key('enter'). Raises CmuxError so a partial sequence is never silent."""
    cmd = ["cmux", "send", "--surface", surface_ref]
    if workspace_ref:
        cmd += ["--workspace", workspace_ref]
    cmd += [text]
    r = _run(cmd)
    if r.returncode != 0:
        raise CmuxError(f"cmux send failed: {r.stderr.strip()}")


def send_key(surface_ref: str, workspace_ref: Optional[str], key: str) -> None:
    """Send a single key (`enter`, `escape`, `c-c`, ...). Raises on failure."""
    cmd = ["cmux", "send-key", "--surface", surface_ref]
    if workspace_ref:
        cmd += ["--workspace", workspace_ref]
    cmd += [key]
    r = _run(cmd)
    if r.returncode != 0:
        raise CmuxError(f"cmux send-key {key!r} failed: {r.stderr.strip()}")


def close_surface(surface_ref: str, workspace_ref: Optional[str]) -> None:
    """Hard-close a surface/pane (the `kill` verb's last resort). Raises."""
    cmd = ["cmux", "close-surface", "--surface", surface_ref]
    if workspace_ref:
        cmd += ["--workspace", workspace_ref]
    r = _run(cmd)
    if r.returncode != 0:
        raise CmuxError(f"cmux close-surface failed: {r.stderr.strip()}")
