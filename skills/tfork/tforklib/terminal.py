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
    err_no_terminal,
    err_spawn_failed,
    err_split_failed,
    err_surface_resolution_failed,
)


SURFACE_REF_RE = re.compile(r"^surface:\d+$")

# User-facing split directions. Mapped to cmux's ``new-split`` argot below
# (cmux speaks ``up``/``down``; tfork keeps the more intuitive
# ``top``/``bottom`` at the front door).
SPLIT_DIRS = ("right", "left", "top", "bottom")
_CMUX_DIRECTION = {"right": "right", "left": "left",
                   "top": "up", "bottom": "down"}

# Placement value that opens a fresh workspace tab instead of splitting.
NEW_WORKSPACE = "new-workspace"


class Terminal(ABC):
    """Minimal multiplexer interface. A backend is one subclass + one entry in
    ``TERMINALS``; surface resolution, placement, and sentinel-wrapped spawn
    are backend concerns, not the orchestrator's."""

    @classmethod
    @abstractmethod
    def detect(cls) -> bool:
        """True when the caller is running inside this multiplexer."""

    @abstractmethod
    def fork(self, command, placement, cwd, nonce, anchor=None) -> object:
        """Open a new pane (or a new workspace), paste the sentinel-wrapped
        command, and return an opaque session handle for the new surface.

        ``placement`` is one of ``"right"``, ``"left"``, ``"top"``,
        ``"bottom"`` (split next to ``anchor`` or the caller) or
        ``"new-workspace"`` (open a fresh workspace tab — ``anchor`` is
        ignored). ``anchor`` may be a surface ref or a tab title; ``None``
        means the caller's own surface.
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
    """Full ``cmux tree --all`` document or ``{}`` on failure."""
    result = _run(["cmux", "--json", "tree", "--all"])
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

    def fork(self, command, placement, cwd, nonce, anchor=None):
        """Open the new surface and paste the sentinel-wrapped command into it."""
        session = self._open_surface(placement, anchor)
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

    def _open_surface(self, placement, anchor):
        """Open the new surface and return its ref — by split or workspace."""
        if placement == NEW_WORKSPACE:
            return self._new_workspace_surface()
        if placement not in SPLIT_DIRS:
            raise err_split_failed(
                f"unknown placement '{placement}'; expected one of "
                f"{SPLIT_DIRS + (NEW_WORKSPACE,)}"
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

    def _new_workspace_surface(self):
        """Open a fresh workspace tab and return the ref of its initial surface.

        cmux's ``new-workspace`` prints ``OK <workspace-ref>``; the surface
        inside it is then looked up via ``cmux tree``. ``--focus true`` is
        load-bearing here too — without it cmux leaves the workspace's
        terminal uninstantiated and ``read-screen`` would never come ready.
        """
        result = _run(["cmux", "new-workspace", "--focus", "true"])
        if result.returncode != 0:
            raise err_split_failed(
                result.stderr.strip() or "cmux new-workspace failed")
        ws_ref = None
        for token in result.stdout.split():
            if token.startswith("workspace:"):
                ws_ref = token
                break
        if not ws_ref:
            raise err_split_failed(
                "could not capture the new workspace ref")
        # The freshly-created workspace contains exactly one pane with one
        # surface; pull its ref out of the tree.
        for window in _cmux_tree().get("windows", []):
            for ws in window.get("workspaces", []):
                if ws.get("ref") != ws_ref:
                    continue
                for pane in ws.get("panes", []):
                    for surface in pane.get("surfaces", []):
                        ref = surface.get("ref")
                        if ref:
                            self._workspaces[ref] = ws_ref
                            return ref
        raise err_split_failed(
            f"could not locate the initial surface for {ws_ref}")

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
