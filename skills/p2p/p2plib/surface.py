"""Cmux surface and workspace discovery.

`my_surface()` resolves the caller's own surface_ref, cross-checking
$CMUX_SURFACE_ID (which is inherited across forks and can lie) against
the controlling-tty walk (ground truth, but sometimes unavailable).

`_workspace_of()` lifts the workspace the surface lives in, so every
surface-targeted cmux call can pass `--workspace <ws>` and route to the
right pane regardless of where the caller is sitting. cmux's
paste-buffer / send / send-key all fall back to $CMUX_WORKSPACE_ID
when --workspace is omitted, so omitting it means cross-workspace
messaging silently routes to the caller's workspace and fails as
"Surface is not a terminal".
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys


# A cmux workspace ref looks like ``workspace:N`` or a long
# UUID-shaped string. The title path runs only when neither form matches.
_WORKSPACE_REF_RE = re.compile(r"^(?:workspace:\d+|[0-9a-fA-F-]{16,})$")
_WINDOW_REF_RE = re.compile(r"^(?:window:\d+|[0-9a-fA-F-]{16,}|\d+)$")


def is_workspace_ref(value: str) -> bool:
    return bool(_WORKSPACE_REF_RE.match(value or ""))


def is_window_ref(value: str) -> bool:
    return bool(_WINDOW_REF_RE.match(value or ""))


def list_windows(tree: dict | None = None) -> list[dict]:
    """Every live cmux window as {ref, id, index}."""
    tree = cmux_tree() if tree is None else tree
    out: list[dict] = []
    for window in tree.get("windows", []):
        ref = window.get("ref")
        if not ref:
            continue
        out.append({
            "ref": ref,
            "id": window.get("id"),
            "index": window.get("index"),
        })
    return out


def resolve_window(value: str, tree: dict | None = None) -> dict | None:
    """Resolve a window ref / UUID / index to the live window record."""
    for window in list_windows(tree):
        if value in (
            window.get("ref"),
            window.get("id"),
            str(window.get("index")),
        ):
            return window
    return None


def list_workspaces(tree: dict | None = None) -> list[tuple[str, str]]:
    """``(ref, title)`` for every live cmux workspace."""
    return [(w["ref"], w["title"]) for w in workspace_records(tree)]


def workspace_records(tree: dict | None = None,
                      window_ref: str | None = None) -> list[dict]:
    """Every live workspace as {ref, title, id, window_ref}.

    ``window_ref`` scopes the listing to one window when supplied.
    """
    tree = cmux_tree() if tree is None else tree
    out: list[dict] = []
    for window in tree.get("windows", []):
        win_ref = window.get("ref")
        if window_ref is not None and win_ref != window_ref:
            continue
        for ws in window.get("workspaces", []):
            ref = ws.get("ref")
            if ref:
                out.append({
                    "ref": ref,
                    "title": ws.get("title") or "",
                    "id": ws.get("id"),
                    "window_ref": win_ref,
                })
    return out


def _run(cmd: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(cmd, 255, "", str(exc))


def cmux_tree() -> dict:
    r = _run(["cmux", "--json", "--id-format", "both", "tree", "--all"])
    if r.returncode != 0:
        return {}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {}


def _iter_surfaces(tree: dict):
    for window in tree.get("windows", []):
        for ws in window.get("workspaces", []):
            for pane in ws.get("panes", []):
                for surface in pane.get("surfaces", []):
                    yield window, ws, surface


def live_surfaces(tree: dict | None = None) -> set[str]:
    tree = cmux_tree() if tree is None else tree
    return {s.get("ref") for _, _, s in _iter_surfaces(tree)
            if s.get("ref")}


def surface_index(tree: dict | None = None) -> dict[str, dict]:
    """Map surface_ref -> cmux metadata for routing."""
    tree = cmux_tree() if tree is None else tree
    out: dict[str, dict] = {}
    for window, ws, s in _iter_surfaces(tree):
        ref = s.get("ref")
        if not ref:
            continue
        out[ref] = {
            "ref": ref,
            "tty": s.get("tty") or "",
            "title": s.get("title") or "",
            "workspace_ref": ws.get("ref"),
            "workspace_title": ws.get("title") or "",
            "window_ref": window.get("ref"),
            "window_id": window.get("id"),
            "window_index": window.get("index"),
        }
    return out


def workspace_of(surface_ref: str, tree: dict | None = None) -> str | None:
    return (surface_index(tree).get(surface_ref) or {}).get("workspace_ref")


def window_of(surface_ref: str, tree: dict | None = None) -> str | None:
    return (surface_index(tree).get(surface_ref) or {}).get("window_ref")


def _ancestor_ttys():
    pid = os.getpid()
    seen: set[int] = set()
    for _ in range(30):
        if pid <= 1 or pid in seen:
            return
        seen.add(pid)
        r = _run(["ps", "-o", "tty=,ppid=", "-p", str(pid)])
        if r.returncode != 0 or not r.stdout.strip():
            return
        parts = r.stdout.strip().split()
        if len(parts) < 2:
            return
        tty, ppid = parts[0], parts[1]
        if tty and tty not in ("?", "??", "-"):
            yield tty
        try:
            pid = int(ppid)
        except ValueError:
            return


def _surface_from_tty_walk(tree: dict | None = None) -> str | None:
    tree = cmux_tree() if tree is None else tree
    by_tty = {s["tty"]: ref for ref, s in surface_index(tree).items()
              if s["tty"]}
    if not by_tty:
        return None
    for tty in _ancestor_ttys():
        if tty in by_tty:
            return by_tty[tty]
    return None


def my_surface() -> str | None:
    """Resolve the caller's surface_ref. None when neither source agrees."""
    override = os.environ.get("AGENT_MSG_SURFACE_ID")
    if override:
        return override

    env_surf = None
    r = _run(["cmux", "identify", "--json"])
    if r.returncode == 0:
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            data = {}
        caller = data.get("caller") or {}
        env_surf = caller.get("surface_ref") or None

    tree = cmux_tree()
    tty_surf = _surface_from_tty_walk(tree)

    if env_surf and tty_surf:
        if env_surf == tty_surf:
            return env_surf
        print(
            f"warning: cmux identify says {env_surf} but controlling tty "
            f"says {tty_surf}. Trusting tty. $CMUX_SURFACE_ID was likely "
            f"inherited from another pane. Override with "
            f"AGENT_MSG_SURFACE_ID=surface:<N> to silence.",
            file=sys.stderr,
        )
        return tty_surf

    return tty_surf or env_surf
