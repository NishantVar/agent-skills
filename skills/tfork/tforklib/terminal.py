"""The terminal abstraction and the cmux backend.

``Terminal`` is the minimal multiplexer interface the orchestration layer
depends on. ``CmuxTerminal`` is the only concrete backend — built on the
``cmux`` command-line interface. To add a backend, write one ``Terminal``
subclass and add it to ``TERMINALS``; surface resolution, the placement
modes, and the sentinel-wrapped spawn stay the backend's concern.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import time
from abc import ABC, abstractmethod

from .errors import (
    err_anchor_ambiguous,
    err_anchor_not_found,
    err_bad_arguments,
    err_no_terminal,
    err_spawn_failed,
    err_split_failed,
    err_surface_resolution_failed,
    err_window_create_failed,
    err_window_unknown,
    err_workspace_ambiguous,
    err_workspace_unknown,
)


SURFACE_REF_RE = re.compile(r"^surface:\d+$")
# Workspace refs come back as ``workspace:N`` or as a UUID. Treat either
# as an explicit ref (no implicit creation on a ref miss).
_WORKSPACE_REF_RE = re.compile(r"^(?:workspace:\d+|[0-9a-fA-F-]{16,})$")

# User-facing split directions. Mapped to cmux's ``new-split`` argot below
# (cmux speaks ``up``/``down``; tfork keeps the more intuitive
# ``top``/``bottom`` at the front door).
SPLIT_DIRS = ("right", "left", "top", "bottom")
_CMUX_DIRECTION = {"right": "right", "left": "left",
                   "top": "up", "bottom": "down"}


def is_workspace_ref(value):
    """True when ``value`` looks like a cmux workspace ref (workspace:N or
    a UUID-shaped string). Used to skip title lookup."""
    return bool(_WORKSPACE_REF_RE.match(value or ""))


class Terminal(ABC):
    """Minimal multiplexer interface. A backend is one subclass + one entry in
    ``TERMINALS``; surface resolution, placement, and sentinel-wrapped spawn
    are backend concerns, not the orchestrator's."""

    @classmethod
    @abstractmethod
    def detect(cls) -> bool:
        """True when the caller is running inside this multiplexer."""

    @abstractmethod
    def fork(self, command, placement, cwd, nonce, anchor=None,
             workspace=None) -> object:
        """Open a new pane, paste the sentinel-wrapped command, and return
        an opaque session handle for the new surface.

        ``placement`` is one of ``"right"``, ``"left"``, ``"top"``,
        ``"bottom"`` (split) or ``None`` (no explicit direction — only
        valid with ``workspace``: opens a fresh pane in the workspace).
        ``anchor`` may be a surface ref or a tab title; ``None`` means
        the caller's own surface. ``workspace`` is the resolved
        ``{ref, title, created}`` dict from ``resolve_workspace`` and is
        mutually exclusive with ``anchor`` (the front door enforces).
        """

    @abstractmethod
    def resolve_workspace(self, value, cwd) -> dict:
        """Resolve a ``--workspace`` value to ``{ref, title, created}``.

        ``value`` is a cmux workspace ref (workspace:N or a UUID) or a
        title. A ref must already resolve — refs are not names and miss
        → ``workspace_unknown`` (no implicit creation). A title with
        exactly one match is reused (created=False); zero matches creates
        via ``cmux new-workspace --name <title> --cwd <cwd>``; two or
        more → ``workspace_ambiguous`` with each candidate.
        """

    @abstractmethod
    def resolve_window(self, value, workspace, cwd) -> tuple:
        """Resolve ``--window`` into ``(window_info, workspace_info)``.

        ``value`` is ``"new"`` (open a fresh top-level window, without
        stealing focus from the caller's window) or a window ref/index/UUID
        (target an existing window). ``workspace`` is the optional
        ``--workspace`` title.

        Returns ``({"ref", "created"}, {"ref", "title", "created"})``.
        For a new window the seeded workspace is reused (renamed when a
        ``workspace`` title is given) so the window does not accumulate an
        orphan default workspace. For an existing window the workspace is
        resolved within that window — a matching title is reused, otherwise
        a fresh workspace is created in it. A window-ref miss raises
        ``window_unknown``.
        """

    @abstractmethod
    def pane_process(self, session) -> "str | None":
        """The foreground process name in ``session``, or None if none/dead."""

    @abstractmethod
    def pane_text(self, session) -> str:
        """The full scrollback of ``session`` (top to bottom)."""

    @abstractmethod
    def kill(self, session) -> None:
        """Close the pane identified by ``session``."""

    @abstractmethod
    def rename_tab(self, session, title) -> tuple:
        """Rename the tab containing ``session`` to ``title``.

        Returns ``(error_or_none, duplicate_refs)``: ``error_or_none`` is a
        one-line stderr-style string when the underlying rename failed (None
        on success), and ``duplicate_refs`` is the list of other surface refs
        in the same workspace that already carried ``title`` (empty when the
        title is unique). The pane is not killed on rename failure — a tab
        without the requested title is still a working fork."""


def _run(cmd, timeout=10):
    """Run a subprocess, never raising — failures surface as a non-zero code."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(cmd, 255, "", str(exc))


def _norm_tty(tty):
    return (tty or "").replace("/dev/", "").strip()


def _ancestor_ttys():
    """The caller's controlling tty and those of its ancestors, nearest first.

    Agent runtimes differ in how many process layers — and how many private
    ptys — sit between this script and the cmux pane shell, so every ancestor
    tty is collected in walk order; the caller matches them against cmux's
    known set and takes the first hit rather than trusting the nearest tty.
    """
    ttys = []
    pid = os.getpid()
    seen = set()
    for _ in range(30):
        if pid <= 1 or pid in seen:
            break
        seen.add(pid)
        result = _run(["ps", "-o", "tty=,ppid=", "-p", str(pid)])
        parts = result.stdout.split()
        if result.returncode != 0 or len(parts) < 2:
            break
        tty, ppid = parts[0], parts[1]
        norm = _norm_tty(tty)
        if tty not in ("?", "??", "-") and norm and norm not in ttys:
            ttys.append(norm)
        try:
            pid = int(ppid)
        except ValueError:
            break
    return ttys


def _cmux_tree():
    """Full ``cmux tree --all`` document or ``{}`` on failure.

    ``--id-format both`` keeps every node's short ``ref`` and additionally
    populates its UUID ``id`` — needed to match a freshly-created window
    (``cmux new-window`` hands back a UUID) back to its tree node, since the
    default tree leaves ``id`` null."""
    result = _run(["cmux", "--json", "--id-format", "both", "tree", "--all"])
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def _all_surfaces(tree):
    """Yield every surface dict in a ``cmux tree --all`` document."""
    for window in tree.get("windows", []):
        for workspace in window.get("workspaces", []):
            for pane in workspace.get("panes", []):
                for surface in pane.get("surfaces", []):
                    yield surface


def _workspace_of(surface_ref, tree=None):
    """Workspace ref containing ``surface_ref``, or None when the surface is
    not in the tree.

    cmux's ``new-split`` and ``close-surface`` are workspace-scoped: when the
    surface lives in a workspace other than the caller's, they fall back to
    ``$CMUX_WORKSPACE_ID`` and return ``not_found``. Looking up the
    containing workspace lets us pass ``--workspace`` explicitly so the
    lookup succeeds regardless of where the caller is sitting."""
    if tree is None:
        tree = _cmux_tree()
    for window in tree.get("windows", []):
        for ws in window.get("workspaces", []):
            for pane in ws.get("panes", []):
                for surface in pane.get("surfaces", []):
                    if surface.get("ref") == surface_ref:
                        return ws.get("ref")
    return None


def _cmux_surfaces_by_tty():
    """Map normalized tty -> surface ref for every live cmux surface."""
    out = {}
    for surface in _all_surfaces(_cmux_tree()):
        tty = _norm_tty(surface.get("tty"))
        ref = surface.get("ref")
        if tty and ref:
            out[tty] = ref
    return out


def _walk_processes(node):
    """Yield a ``cmux top`` process node and every process nested under it."""
    yield node
    for child in node.get("children", []):
        yield from _walk_processes(child)


def _find_surface_node(data, surface_ref):
    """Find the ``kind == "surface"`` node for ``surface_ref`` anywhere in a
    ``cmux top`` JSON document, or None when the surface is gone."""
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("kind") == "surface" and node.get("ref") == surface_ref:
                return node
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None


def resolve_anchor(value):
    """Return a surface ref for ``value`` — accepting a ref directly or a
    tab title to look up.

    A literal ``surface:N`` ref is returned untouched; a name is matched
    case-sensitively against every live surface's ``title``. Zero matches
    raises ``anchor_not_found``; multiple matches raises ``anchor_ambiguous``
    with each candidate's surface ref plus its containing workspace, so the
    user can disambiguate by workspace name rather than guessing which
    ``surface:N`` belongs where.
    """
    if SURFACE_REF_RE.match(value or ""):
        return value
    candidates = []
    tree = _cmux_tree()
    for window in tree.get("windows", []):
        for ws in window.get("workspaces", []):
            for pane in ws.get("panes", []):
                for surface in pane.get("surfaces", []):
                    if surface.get("title") != value:
                        continue
                    candidates.append({
                        "ref": surface.get("ref"),
                        "workspace_ref": ws.get("ref"),
                        "workspace_title": ws.get("title"),
                    })
    if not candidates:
        raise err_anchor_not_found(value)
    if len(candidates) > 1:
        raise err_anchor_ambiguous(value, candidates)
    return candidates[0]["ref"]


class CmuxTerminal(Terminal):
    """The cmux backend — the only concrete ``Terminal`` for now.

    Built on the ``cmux`` command-line interface. Surface resolution, the
    placement modes, sentinel-wrapped spawn, and inspection are all exercised
    against a live cmux session by the end-to-end tests.
    """

    READY_TIMEOUT = 12   # seconds to wait for a new pane's shell to come up

    def __init__(self):
        # surface_ref -> workspace_ref cache. Every cmux surface command
        # (``new-split``, ``close-surface``, ``paste-buffer``, ``send-key``,
        # ``read-screen``) is workspace-scoped: when the surface lives outside
        # the caller's ``$CMUX_WORKSPACE_ID`` the command returns
        # ``not_found``. Caching at fork time keeps us from re-walking the
        # tree on every per-pane call.
        self._workspaces = {}

    @classmethod
    def detect(cls):
        if shutil.which("cmux") is None:
            return False
        return _run(["cmux", "identify", "--json"]).returncode == 0

    def fork(self, command, placement, cwd, nonce, anchor=None,
             workspace=None):
        """Open the new surface and paste the sentinel-wrapped command into it."""
        session = self._open_surface(placement, anchor, workspace)
        self._wait_ready(session)
        line = _build_wrapper(nonce, cwd, command)
        self._spawn(session, line)
        return session

    def _workspace_args(self, session):
        """``["--workspace", ws_ref]`` for ``session`` or ``[]`` when unknown.

        cmux surface commands fall back to ``$CMUX_WORKSPACE_ID`` and return
        ``not_found`` when the surface lives elsewhere; passing
        ``--workspace`` explicitly fixes the cross-workspace case. The cache
        is populated at surface-creation time so steady-state calls don't pay
        the cost of a tree walk."""
        ws_ref = self._workspaces.get(session)
        if ws_ref is None:
            ws_ref = _workspace_of(session)
            if ws_ref:
                self._workspaces[session] = ws_ref
        return ["--workspace", ws_ref] if ws_ref else []

    # -- surface resolution -------------------------------------------------

    def _resolve_origin_surface(self):
        """Resolve the caller's *own* surface — never the focused pane.

        Order: an explicit ``TFORK_SURFACE_ID`` override, then cmux's
        self-identify (the ``caller`` block, keyed off the caller's inherited
        ``$CMUX_SURFACE_ID`` — not ``focused``, which is wherever the human
        is clicking), then an ancestor-tty walk against cmux's known
        surfaces. Exhausting all three is a hard failure.
        """
        override = os.environ.get("TFORK_SURFACE_ID")
        if override:
            return override
        result = _run(["cmux", "identify", "--json"])
        if result.returncode == 0:
            try:
                caller = json.loads(result.stdout).get("caller") or {}
            except json.JSONDecodeError:
                caller = {}
            if caller.get("surface_ref"):
                return caller["surface_ref"]
        walked = self._resolve_via_tty()
        if walked:
            return walked
        raise err_surface_resolution_failed()

    def _resolve_via_tty(self):
        """Match the caller's ancestor ttys against cmux's known surfaces; the
        nearest ancestor whose tty cmux recognises wins."""
        known = _cmux_surfaces_by_tty()
        if not known:
            return None
        for tty in _ancestor_ttys():
            if tty in known:
                return known[tty]
        return None

    # -- placement ----------------------------------------------------------

    def _open_surface(self, placement, anchor, workspace):
        """Open the new surface and return its ref.

        Four placement modes, set by which of ``workspace`` / ``placement``
        / ``anchor`` are populated (the front door enforces the mutex):

          * ``workspace`` + no ``placement`` → fresh pane in workspace.
          * ``workspace`` + ``placement`` direction → split workspace's
            active pane in that direction.
          * ``placement`` direction + ``anchor`` → split anchor.
          * ``placement`` direction only → split caller.
        """
        if workspace is not None:
            ws_ref = workspace.get("ref")
            if placement is None:
                # cmux new-workspace already created an initial pane with
                # a single surface; reusing it avoids leaving an orphan
                # blank pane next to the one tfork actually runs in.
                if workspace.get("created"):
                    seeded = self._initial_workspace_surface(ws_ref)
                    if seeded:
                        self._workspaces[seeded] = ws_ref
                        return seeded
                return self._new_pane_in_workspace(ws_ref, direction=None)
            if placement not in SPLIT_DIRS:
                raise err_split_failed(
                    f"unknown placement '{placement}'; expected one of "
                    f"{SPLIT_DIRS}"
                )
            return self._new_pane_in_workspace(ws_ref, direction=placement)
        if placement is None:
            placement = "right"  # historic default when no workspace
        if placement not in SPLIT_DIRS:
            raise err_split_failed(
                f"unknown placement '{placement}'; expected one of "
                f"{SPLIT_DIRS}"
            )
        origin = resolve_anchor(anchor) if anchor else self._resolve_origin_surface()
        return self._new_split(placement, origin)

    def _new_split(self, direction, origin_surface):
        """Split a new pane off ``origin_surface`` and return its ref.

        ``--focus true`` is load-bearing: cmux instantiates a split's terminal
        lazily, and an unfocused split can sit indefinitely as a surface
        record with no shell. Focusing it forces the shell to come up.

        ``--workspace`` is passed explicitly whenever the surface lives in a
        workspace other than the caller's — cmux's ``new-split`` defaults to
        ``$CMUX_WORKSPACE_ID`` and would return ``not_found`` for a
        cross-workspace anchor otherwise."""
        cmux_dir = _CMUX_DIRECTION.get(direction, direction)
        cmd = ["cmux", "--json", "new-split", cmux_dir,
               "--surface", origin_surface, "--focus", "true"]
        cmd += self._workspace_args(origin_surface)
        result = _run(cmd)
        if result.returncode != 0:
            raise err_split_failed(
                result.stderr.strip() or "cmux new-split failed")
        try:
            ref = json.loads(result.stdout).get("surface_ref")
        except json.JSONDecodeError:
            ref = None
        if not ref:
            raise err_split_failed("could not capture the new surface ref")
        # A split lands in the same workspace as its origin; seed the cache
        # so subsequent per-pane calls (paste-buffer, send-key, read-screen,
        # close-surface) skip the tree walk.
        ws_ref = self._workspaces.get(origin_surface)
        if ws_ref:
            self._workspaces[ref] = ws_ref
        return ref

    def resolve_workspace(self, value, cwd):
        """Resolve a ``--workspace`` value to ``{ref, title, created}``.

        Refs go through verbatim if they resolve; a ref miss is
        ``workspace_unknown`` (no implicit creation — refs are not names).
        Titles are case-sensitive exact matches against ``cmux
        list-workspaces``: zero matches creates with
        ``cmux new-workspace --name <title> --cwd <cwd>``; one match is
        reused; two or more is ``workspace_ambiguous``.
        """
        if is_workspace_ref(value):
            for ws_ref, ws_title in self._list_workspaces():
                if ws_ref == value:
                    return {"ref": ws_ref, "title": ws_title or "",
                            "created": False}
            raise err_workspace_unknown(value)

        matches = [(r, t) for r, t in self._list_workspaces()
                   if t == value]
        if len(matches) == 1:
            return {"ref": matches[0][0], "title": matches[0][1],
                    "created": False}
        if len(matches) > 1:
            raise err_workspace_ambiguous(
                value,
                [{"ref": r, "title": t} for r, t in matches],
            )
        ws_ref, detail = self._create_workspace(value, cwd)
        if not ws_ref:
            # Best-effort recovery from a TOCTOU race: another spawner
            # may have created the same title between our list_workspaces
            # call and our new-workspace call. Re-list and reuse if
            # exactly one match exists now.
            recheck = [(r, t) for r, t in self._list_workspaces()
                       if t == value]
            if len(recheck) == 1:
                return {"ref": recheck[0][0], "title": recheck[0][1],
                        "created": False}
            raise err_workspace_unknown(value, detail=detail)
        return {"ref": ws_ref, "title": value, "created": True}

    # -- window resolution --------------------------------------------------

    def resolve_window(self, value, workspace, cwd):
        """Resolve ``--window`` into ``(window_info, workspace_info)``.

        ``new`` opens a fresh window and reuses its seeded workspace (renamed
        when ``workspace`` is given); a ref/index/UUID targets an existing
        window and resolves the workspace within it. See the
        ``Terminal.resolve_window`` contract for the full behavior."""
        if value == "new":
            return self._resolve_new_window(workspace)
        return self._resolve_existing_window(value, workspace, cwd)

    def _resolve_new_window(self, workspace):
        """Open a fresh window, reuse its seeded workspace.

        The window comes up with exactly one workspace; reusing it (renamed
        when a title is given) avoids leaving an orphan default workspace
        beside the one tfork runs in.

        A fresh window's seeded workspace can only be *named*, never bound to
        an existing workspace ref — that workspace already lives elsewhere.
        So a ref-shaped ``--workspace`` value is rejected here rather than
        silently turned into a literal title like ``'workspace:1'``."""
        if workspace and is_workspace_ref(workspace):
            raise err_bad_arguments(
                f"--window new seeds its own workspace, so --workspace must "
                f"be a title to name it, not a ref ({workspace!r})")
        win_uuid = self._new_window()
        window = self._window_node(win_uuid)
        if window is None:
            raise err_window_create_failed(
                "the new window did not appear in the cmux tree")
        win_ref = window.get("ref") or win_uuid
        workspaces = window.get("workspaces", []) or []
        if len(workspaces) != 1:
            raise err_window_create_failed(
                "the new window did not come up with a single workspace")
        seeded = workspaces[0]
        ws_ref = seeded.get("ref")
        if workspace:
            self._rename_workspace(ws_ref, workspace, win_ref)
            title = workspace
        else:
            title = seeded.get("title") or ""
        return ({"ref": win_ref, "created": True},
                {"ref": ws_ref, "title": title, "created": True})

    def _resolve_existing_window(self, value, workspace, cwd):
        """Target an existing window. The window is resolved up front — a miss
        is ``window_unknown`` — and its canonical ``window:N`` ref is used for
        the returned info and every follow-up call, so an index/UUID input
        does not leak through into the result JSON."""
        window = self._window_node(value)
        if window is None:
            raise err_window_unknown(value)
        win_ref = window.get("ref") or value
        if workspace:
            ws_info = self._resolve_workspace_in_window(workspace, win_ref, cwd)
        else:
            ws_ref, detail = self._create_workspace(None, cwd, window=win_ref)
            if not ws_ref:
                raise err_window_unknown(win_ref, detail=detail)
            ws_info = {"ref": ws_ref, "title": "", "created": True}
        return {"ref": win_ref, "created": False}, ws_info

    def _resolve_workspace_in_window(self, value, win_ref, cwd):
        """Resolve a ``--workspace`` value scoped to ``win_ref``.

        Mirrors ``resolve_workspace``'s ref/title split: a ref (workspace:N
        or UUID) is reused only when it already lives in this window and is
        never created on a miss (refs are not names); a title reuses a single
        in-window match, errors on ``workspace_ambiguous`` for two or more,
        and is created in the window when absent."""
        in_window = self._workspaces_in_window(win_ref)
        if is_workspace_ref(value):
            # A ref may be the short workspace:N or the UUID; match either and
            # always return the canonical short ref.
            for r, t, uid in in_window:
                if value in (r, uid):
                    return {"ref": r, "title": t, "created": False}
            raise err_workspace_unknown(value)
        matches = [(r, t) for r, t, _uid in in_window if t == value]
        if len(matches) == 1:
            return {"ref": matches[0][0], "title": matches[0][1],
                    "created": False}
        if len(matches) > 1:
            raise err_workspace_ambiguous(
                value, [{"ref": r, "title": t} for r, t in matches])
        ws_ref, detail = self._create_workspace(value, cwd, window=win_ref)
        if not ws_ref:
            raise err_window_unknown(win_ref, detail=detail)
        return {"ref": ws_ref, "title": value, "created": True}

    def _new_window(self):
        """Create a fresh top-level window and return its UUID.

        ``cmux new-window`` prints ``OK <window-uuid>``; the UUID is a valid
        handle for the follow-up tree lookup and is translated to a short ref
        by the caller."""
        result = _run(["cmux", "new-window"])
        if result.returncode != 0:
            raise err_window_create_failed(
                result.stderr.strip() or "cmux new-window failed")
        for token in result.stdout.split():
            if token != "OK":
                return token
        raise err_window_create_failed("could not capture the new window ref")

    def _window_node(self, win_ref):
        """The tree window dict matching ``win_ref`` by ref, UUID, or index;
        None when nothing matches."""
        for window in _cmux_tree().get("windows", []):
            if win_ref in (window.get("ref"), window.get("id"),
                           str(window.get("index"))):
                return window
        return None

    def _workspaces_in_window(self, win_ref):
        """``(ref, title, uuid)`` for every workspace in ``win_ref`` — empty
        when the window is not found. The UUID is carried so a ref-shaped
        ``--workspace`` value can match either the short ref or the UUID."""
        window = self._window_node(win_ref)
        if window is None:
            return []
        return [(ws.get("ref"), ws.get("title") or "", ws.get("id"))
                for ws in window.get("workspaces", []) if ws.get("ref")]

    def _rename_workspace(self, ws_ref, title, win_ref):
        """Best-effort rename of ``ws_ref`` to ``title``. A rename miss is not
        fatal — the fork still lands in the right workspace, just under cmux's
        default name."""
        _run(["cmux", "rename-workspace", "--workspace", ws_ref,
              "--window", win_ref, title])

    def _list_workspaces(self):
        """Yield ``(ref, title)`` for every live cmux workspace.

        Walks ``cmux tree --all`` rather than calling ``cmux
        list-workspaces`` separately — the tree we already use for
        surface resolution carries the same data and avoids a second
        subprocess hop. Returns a list, not a generator, so callers can
        re-iterate cheaply.
        """
        out = []
        for window in _cmux_tree().get("windows", []):
            for ws in window.get("workspaces", []):
                ref = ws.get("ref")
                if ref:
                    out.append((ref, ws.get("title") or ""))
        return out

    def _create_workspace(self, title, cwd, window=None):
        """Create a workspace; return ``(ref-or-None, detail)``.

        ``title`` names it (omitted → cmux's default name); ``window``
        targets a specific window (omitted → the caller's window).
        ``--focus false`` keeps cmux's window from jumping to the new
        workspace — the multi-agent use case is "spawn N agents without
        my view bouncing around." A future ``--focus`` toggle can be
        added if needed.
        """
        cmd = ["cmux", "new-workspace", "--cwd", cwd, "--focus", "false"]
        if title:
            cmd += ["--name", title]
        if window:
            cmd += ["--window", window]
        result = _run(cmd)
        if result.returncode != 0:
            return None, result.stderr.strip() or "cmux new-workspace failed"
        ws_ref = None
        try:
            ws_ref = (json.loads(result.stdout) or {}).get("workspace_ref")
        except json.JSONDecodeError:
            for token in result.stdout.split():
                if token.startswith("workspace:"):
                    ws_ref = token
                    break
        if not ws_ref:
            return None, "could not capture the new workspace ref"
        return ws_ref, None

    def _initial_workspace_surface(self, ws_ref):
        """Return the workspace's existing surface ref when it holds
        exactly one pane with one surface; ``None`` otherwise.

        This is the post-``new-workspace`` shape: cmux always seeds the
        workspace with an initial terminal. Reusing that surface keeps
        the workspace from accumulating an empty pane next to ours."""
        for window in _cmux_tree().get("windows", []):
            for ws in window.get("workspaces", []):
                if ws.get("ref") != ws_ref:
                    continue
                panes = ws.get("panes", []) or []
                if len(panes) != 1:
                    return None
                surfaces = panes[0].get("surfaces", []) or []
                if len(surfaces) != 1:
                    return None
                return surfaces[0].get("ref")
        return None

    def _new_pane_in_workspace(self, ws_ref, direction):
        """Open a pane in ``ws_ref`` — fresh when ``direction`` is None,
        otherwise a directional split of the workspace's active pane.

        cmux's ``new-pane --workspace <ref> [--direction <dir>]`` is
        the path the spec names; ``--focus false`` keeps the cmux window
        from jumping.
        """
        cmd = ["cmux", "--json", "new-pane",
               "--workspace", ws_ref, "--focus", "false"]
        if direction:
            cmux_dir = _CMUX_DIRECTION.get(direction, direction)
            cmd += ["--direction", cmux_dir]
        result = _run(cmd)
        if result.returncode != 0:
            raise err_split_failed(
                result.stderr.strip() or "cmux new-pane failed")
        try:
            payload = json.loads(result.stdout) or {}
        except json.JSONDecodeError:
            payload = {}
        ref = payload.get("surface_ref")
        if not ref:
            # Fall back to walking the tree: the newest pane in ws_ref
            # whose ref we don't already know is the new one.
            known = set(self._workspaces.keys())
            for window in _cmux_tree().get("windows", []):
                for ws in window.get("workspaces", []):
                    if ws.get("ref") != ws_ref:
                        continue
                    for pane in ws.get("panes", []):
                        for surface in pane.get("surfaces", []):
                            sref = surface.get("ref")
                            if sref and sref not in known:
                                ref = sref
                                break
                        if ref:
                            break
                    if ref:
                        break
                if ref:
                    break
        if not ref:
            raise err_split_failed("could not capture the new surface ref")
        self._workspaces[ref] = ws_ref
        return ref

    # -- readiness ----------------------------------------------------------

    def _wait_ready(self, session):
        """Block until the new pane's shell can accept input, bounded.

        Until the lazily-instantiated terminal is up, ``read-screen`` fails;
        once it succeeds the shell is live. A pane that never comes up is
        left to surface downstream as a spawn or verification failure, not a
        hang.
        """
        deadline = time.monotonic() + self.READY_TIMEOUT
        ws_args = self._workspace_args(session)
        while time.monotonic() < deadline:
            ready = _run(["cmux", "read-screen", "--surface", session,
                          "--lines", "1", *ws_args])
            if ready.returncode == 0:
                return
            time.sleep(0.5)

    # -- spawn --------------------------------------------------------------

    def _spawn(self, session, line):
        """Deliver one pre-built shell line into ``session``.

        ``cmux send`` truncates long arguments, so the line goes through a
        named buffer (``set-buffer`` + ``paste-buffer`` — the transport the
        p2p skill uses), then a brief pause so the paste lands before Enter.
        The pane is itself an interactive shell, so any user alias in
        ``line`` resolves there without any wrapper of our own."""
        ws_args = self._workspace_args(session)
        set_buf = _run(["cmux", "set-buffer", "--name", "tfork", "--", line])
        paste = _run(["cmux", "paste-buffer", "--name", "tfork",
                      "--surface", session, *ws_args])
        if set_buf.returncode != 0 or paste.returncode != 0:
            detail = (set_buf.stderr + paste.stderr).strip()
            self.kill(session)  # spawn_failed: the pane is killed first
            raise err_spawn_failed(detail or "cmux buffer paste failed")
        time.sleep(0.3)
        send = _run(["cmux", "send-key", "--surface", session, "enter",
                     *ws_args])
        if send.returncode != 0:
            self.kill(session)
            raise err_spawn_failed(send.stderr.strip() or "cmux send-key failed")

    # -- inspection ---------------------------------------------------------

    def pane_process(self, session):
        """The foreground process name in ``session``, or None when the
        surface is gone. Reads cmux's own process accounting: the surface node
        carries ``foreground_pgids``; the process in its tree whose ``pgid``
        matches is the one in the foreground."""
        result = _run(["cmux", "--json", "top", "--processes", "--all"])
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        node = _find_surface_node(data, session)
        if node is None:
            return None
        foreground = set(node.get("foreground_pgids") or [])
        if not foreground:
            return None
        for proc in node.get("processes", []):
            for p in _walk_processes(proc):
                if p.get("pgid") in foreground:
                    return p.get("name")
        # Surface is live but cmux's foreground accounting did not name any
        # tracked process. Refuse to invent one: returning an arbitrary "last
        # seen" name here would feed the verify matrix a false agent signal.
        return None

    def pane_text(self, session):
        """The full scrollback of ``session`` — top to bottom.

        Verification reads from the top so the per-fork start sentinel (the
        first line the wrapper ever prints) is always in range, regardless
        of how much output the command has produced since.
        """
        result = _run(["cmux", "read-screen", "--surface", session,
                       "--scrollback", *self._workspace_args(session)])
        return result.stdout if result.returncode == 0 else ""

    def kill(self, session):
        """Close the pane. ``--workspace`` is passed when known for the same
        cross-workspace reason as ``_new_split`` — ``close-surface`` is
        workspace-scoped too."""
        cmd = ["cmux", "close-surface", "--surface", session,
               *self._workspace_args(session)]
        _run(cmd)

    def rename_tab(self, session, title):
        """Rename ``session``'s tab to ``title``; also report duplicates.

        cmux allows duplicate tab titles within a workspace, so the rename
        always succeeds when the surface is live. After the rename, the
        workspace tree is walked once to surface every other live surface
        sharing ``title`` — the caller bubbles that up via the result ``note``
        so the spawner is not surprised when a later p2p ``send`` returns
        ``peer_ambiguous`` on this title.
        """
        ws_args = self._workspace_args(session)
        result = _run(["cmux", "rename-tab", "--surface", session,
                       *ws_args, title])
        if result.returncode != 0:
            return result.stderr.strip() or "cmux rename-tab failed", []
        ws_ref = self._workspaces.get(session) or _workspace_of(session)
        duplicates = []
        for window in _cmux_tree().get("windows", []):
            for ws in window.get("workspaces", []):
                if ws_ref and ws.get("ref") != ws_ref:
                    continue
                for pane in ws.get("panes", []):
                    for surface in pane.get("surfaces", []):
                        ref = surface.get("ref")
                        if (surface.get("title") == title
                                and ref and ref != session):
                            duplicates.append(ref)
        return None, duplicates


def _build_wrapper(nonce, cwd, command):
    """Build the one-line sentinel-wrapped shell command pasted into a fork.

    The nonce expands at runtime (via ``%s`` + ``$__tfork_nonce``), not at
    paste time, so the literal expanded marker only ever appears in the
    pane's scrollback when ``printf`` actually executes — defeating the
    case where the shell echoes the pasted line back into scrollback before
    running it. ``set +e`` keeps an errexit-enabled shell from terminating
    the wrapper mid-line if the user's command exits non-zero.
    """
    cwd_q = shlex.quote(cwd)
    return (
        f"__tfork_nonce={nonce}; set +e; "
        f"printf '\\n__tfork_start_%s__\\n' \"$__tfork_nonce\"; "
        f"cd {cwd_q} && {command}; "
        f"__tfork_ec=$?; "
        f"printf '\\n__tfork_end_%s=%d__\\n' \"$__tfork_nonce\" \"$__tfork_ec\""
    )


TERMINALS = (CmuxTerminal,)


def resolve_terminal():
    """Return the first registered terminal whose ``detect()`` is true."""
    for cls in TERMINALS:
        try:
            if cls.detect():
                return cls()
        except Exception:
            continue
    raise err_no_terminal()
