"""Subprocess wrappers and parsers for the cmux CLI."""

from __future__ import annotations

import re

from ..model import Surface, Workspace

# Lines look like (annotations may appear in any order at the end):
#   window window:1 [current] ◀ active
#   ├── workspace workspace:2 "Meta Eval"
#   │   ├── pane pane:2 [focused]
#   │   │   └── surface surface:2 [terminal] "design_coordinator" [selected] tty=ttys005
# We extract by entity keyword + ref + (optional) quoted title + trailing
# tty=. Strip [..] flags and ◀ ... ◀ ... annotations defensively.

_WINDOW_RE   = re.compile(r"\bwindow (window:\d+)")
_WORKSPACE_RE = re.compile(r'\bworkspace (workspace:\d+)\s+"([^"]*)"')
_PANE_RE     = re.compile(r"\bpane (pane:\d+)")
_SURFACE_RE  = re.compile(
    r'\bsurface (surface:\d+)\s+\[(terminal|browser)\]\s+"([^"]*)"'
    r'(?:.*?\btty=(\S+))?'
)


def parse_tree(stdout: str) -> list[Workspace]:
    """Parse `cmux tree --all` output into a list of Workspaces with their
    Surfaces attached. Pane refs are stored on each Surface for back-refs.
    """
    workspaces: list[Workspace] = []
    cur_window: str | None = None
    cur_workspace: Workspace | None = None
    cur_pane_ref: str | None = None

    for raw in stdout.splitlines():
        # Strip tree-drawing prefix characters but keep the entity tokens.
        line = raw.strip()
        if not line:
            continue

        m = _WINDOW_RE.search(line)
        if m and " workspace " not in line:
            cur_window = m.group(1)
            continue

        m = _WORKSPACE_RE.search(line)
        if m:
            cur_workspace = Workspace(
                ref=m.group(1),
                title=m.group(2),
                window_ref=cur_window or "window:?",
                surfaces=[],
            )
            workspaces.append(cur_workspace)
            cur_pane_ref = None
            continue

        m = _PANE_RE.search(line)
        if m and " surface " not in line:
            cur_pane_ref = m.group(1)
            continue

        m = _SURFACE_RE.search(line)
        if m and cur_workspace is not None and cur_pane_ref is not None:
            ref, kind, title, tty = m.groups()
            cur_workspace.surfaces.append(Surface(
                ref=ref,
                pane_ref=cur_pane_ref,
                workspace_ref=cur_workspace.ref,
                kind=kind,
                title=title,
                tty=tty,
            ))

    return workspaces
