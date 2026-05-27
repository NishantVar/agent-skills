"""Subprocess wrappers and parsers for the cmux CLI."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field

from ..errors import CmuxUnavailable
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


@dataclass
class TagLine:
    kind: str           # "claude_code" | "codex" | "opencode" | "gemini" | ...
    state: str          # raw cmux state string, e.g. "Running" / "Needs input"
    pid: int | None


@dataclass
class SurfaceStats:
    cpu_pct: float
    mem_bytes: int


@dataclass
class TopResult:
    tags_by_workspace: dict[str, list[TagLine]] = field(default_factory=dict)
    stats_by_surface: dict[str, SurfaceStats] = field(default_factory=dict)


_TOP_WORKSPACE_RE = re.compile(r"workspace (workspace:\d+)")
_TOP_TAG_RE       = re.compile(
    r'\btag\s+(\S+)\s+"([^"]+)"\s+pid=(\d+)'
)
_TOP_SURFACE_RE   = re.compile(
    r"^\s*([\d.]+)%\s+([\d.]+)\s+(KB|MB|GB|B)\s+\d+\s+.*\bsurface (surface:\d+)"
)


def _to_bytes(value: float, unit: str) -> int:
    mul = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}[unit]
    return int(value * mul)


def parse_top(stdout: str) -> TopResult:
    """Parse `cmux top --all` output. `tag <kind> "<state>" pid=N` lines are
    attributed to the most recently seen workspace line (cmux groups them
    under their workspace)."""
    result = TopResult()
    cur_workspace: str | None = None

    for raw in stdout.splitlines():
        m = _TOP_WORKSPACE_RE.search(raw)
        if m:
            cur_workspace = m.group(1)
            continue

        m = _TOP_TAG_RE.search(raw)
        if m and cur_workspace is not None:
            kind, state, pid_s = m.groups()
            result.tags_by_workspace.setdefault(cur_workspace, []).append(
                TagLine(kind=kind, state=state, pid=int(pid_s))
            )
            continue

        m = _TOP_SURFACE_RE.match(raw)
        if m:
            cpu_s, mem_s, unit, surface_ref = m.groups()
            result.stats_by_surface[surface_ref] = SurfaceStats(
                cpu_pct=float(cpu_s),
                mem_bytes=_to_bytes(float(mem_s), unit),
            )

    return result


def _run_cmux(*args: str) -> str:
    """Invoke `cmux <args>` and return stdout as text. Raises
    `CmuxUnavailable` when the binary is missing or the call returns
    non-zero (callers map to a non-fatal Failure record)."""
    if shutil.which("cmux") is None:
        raise CmuxUnavailable("cmux binary not on PATH")
    try:
        cp = subprocess.run(
            ["cmux", *args],
            check=False,
            text=True,
            capture_output=True,
        )
    except (FileNotFoundError, OSError) as e:
        raise CmuxUnavailable(str(e)) from e
    if cp.returncode != 0:
        raise CmuxUnavailable(
            f"cmux {' '.join(args)!r} exited {cp.returncode}: {cp.stderr.strip()}"
        )
    return cp.stdout


def fetch_tree() -> list[Workspace]:
    # `cmux tree --all` matches the documented output and the parser fixtures.
    # Do NOT add `--id-format both` — it inserts UUID tokens between the ref
    # and the title that break the parser fixtures.
    return parse_tree(_run_cmux("tree", "--all"))


def fetch_top() -> TopResult:
    return parse_top(_run_cmux("top", "--all"))


def read_screen(surface_ref: str, lines: int = 150) -> str:
    """Capture up to `lines` lines of scrollback for a given surface. Raises
    `CmuxUnavailable` if the call fails — callers degrade per-surface."""
    return _run_cmux(
        "read-screen", "--surface", surface_ref,
        "--scrollback", "--lines", str(lines),
    )


def cmux_version() -> str | None:
    try:
        return _run_cmux("version").strip() or None
    except CmuxUnavailable:
        return None
