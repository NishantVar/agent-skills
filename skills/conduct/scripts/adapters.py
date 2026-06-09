"""Runtime adapters — one per coding-agent runtime (mirrors afork's
``aforklib/adapters.py``).

conduct is agnostic to a runtime's slash-commands and key bindings; the adapter
owns the mapping from an agnostic lifecycle *verb* (clear / compact / exit /
kill / interrupt) to that runtime's real keystroke sequence, plus how to read a
context-percentage from its screen.

A keystroke sequence is a list of steps. Each step is one of:
  ("text", "<literal>")  -> cmux send (does NOT press Enter)
  ("key",  "<keyname>")  -> cmux send-key (enter / escape / c-c / ...)
  ("close", None)         -> cmux close-surface (hard pane kill)

Atomicity (spec §5.2): a verb is one sequence with no implicit composition —
there is no interrupt-then-clear. ``kill`` is the only verb that uses ``close``;
everything else is keystrokes into the live runtime.

Fail-closed: a runtime with no adapter, or a verb the adapter does not map,
is REFUSED upstream — never injected blindly. ``supports(verb)`` is the gate.

Runtime identification is by foreground process name (from ``cmux top``).
Real process names vary by platform/build and are sometimes truncated by the
process table, so matching is by prefix on a curated allow-list rather than
exact equality (see ``_RUNTIME_PREFIXES`` and ``runtime_from_processes``):
  * claude  <- ``claude``, ``claude.exe`` (ground-truth: ``claude.exe``)
  * codex   <- ``codex``, ``codex.exe``, ``codex-aarch64-apple-...`` etc.
              (ground-truth: ``codex-aarch64-a`` — a truncated arch-suffixed
              binary name)
  * pi      <- ``pi``, ``pi.exe`` (exact only — ``pi`` is too short to prefix
              safely; ``pip``/``pipenv``/``pixi`` must NOT match)

CONTEXT-PERCENTAGE SEMANTICS: ``context_pct`` is the percent of the context
window CONSUMED (used) — higher means closer to full. Runtimes report this
differently:
  * claude's status line shows ``ctx:NN%`` where NN is the USED percentage
    (this deployment's statusline uses ``context_window.used_percentage``),
    so it maps straight through.
  * codex's footer shows ``Context NN% left`` (REMAINING), so it is converted
    to used via ``100 - NN`` to stay consistent with claude's meaning.
  * pi exposes no parseable context indicator -> null.
"""

from __future__ import annotations

import re
from typing import Optional


class ClaudeAdapter:
    runtime = "claude"
    # claude's TUI status line exposes context USED as `ctx:NN%`.
    _ctx_re = re.compile(r"ctx:\s*(\d{1,3})%", re.IGNORECASE)

    # Slash commands are single-line; type the command then press Enter.
    _SEQUENCES = {
        "clear":   [("text", "/clear"), ("key", "enter")],
        "compact": [("text", "/compact"), ("key", "enter")],
        "exit":    [("text", "/exit"), ("key", "enter")],
        # Esc halts a busy claude turn.
        "interrupt": [("key", "escape")],
        # Hard kill closes the pane outright (no graceful slash command).
        "kill":    [("close", None)],
    }

    def supports(self, verb: str) -> bool:
        return verb in self._SEQUENCES

    def sequence(self, verb: str):
        return self._SEQUENCES.get(verb)

    def context_pct(self, screen: str) -> Optional[int]:
        if not screen:
            return None
        m = self._ctx_re.search(screen)
        return int(m.group(1)) if m else None

    def state(self, screen: str) -> Optional[str]:
        return _busy_or_none(screen)


class CodexAdapter:
    runtime = "codex"
    # codex's footer reports context REMAINING, e.g. `Context 37% left` (also
    # accept the `37% context left` word order). We convert to USED below to
    # stay consistent with claude's `ctx:NN%` (used) meaning.
    _ctx_left_re = re.compile(
        r"context\s*(\d{1,3})%\s*left|(\d{1,3})%\s*context\s*left",
        re.IGNORECASE)

    _SEQUENCES = {
        # Codex uses slash-commands for session control like claude.
        "clear":   [("text", "/clear"), ("key", "enter")],
        "compact": [("text", "/compact"), ("key", "enter")],
        "exit":    [("text", "/quit"), ("key", "enter")],
        "interrupt": [("key", "escape")],
        "kill":    [("close", None)],
    }

    def supports(self, verb: str) -> bool:
        return verb in self._SEQUENCES

    def sequence(self, verb: str):
        return self._SEQUENCES.get(verb)

    def context_pct(self, screen: str) -> Optional[int]:
        # codex reports context LEFT; convert to USED to match claude's meaning.
        if not screen:
            return None
        m = self._ctx_left_re.search(screen)
        if not m:
            return None
        left = int(m.group(1) if m.group(1) is not None else m.group(2))
        return max(0, min(100, 100 - left))

    def state(self, screen: str) -> Optional[str]:
        return _busy_or_none(screen)


class PiAdapter:
    runtime = "pi"
    _SEQUENCES = {
        "clear":   [("text", "/clear"), ("key", "enter")],
        "exit":    [("text", "/exit"), ("key", "enter")],
        "interrupt": [("key", "escape")],
        "kill":    [("close", None)],
        # pi has no compact command this round -> unsupported (fail closed).
    }

    def supports(self, verb: str) -> bool:
        return verb in self._SEQUENCES

    def sequence(self, verb: str):
        return self._SEQUENCES.get(verb)

    def context_pct(self, _screen: str) -> Optional[int]:
        # pi exposes no parseable context% this round -> report null.
        return None

    def state(self, screen: str) -> Optional[str]:
        return _busy_or_none(screen)


# Coarse, high-confidence busy detector shared by all adapters. claude and
# codex both render an "esc to interrupt" affordance while a turn is running;
# its presence => "busy". Anything else is reported as null rather than guessed
# — fine-grained state classification (idle / needs-input / error) is the job
# of the watchdog / observability skills, which read full scrollback. conduct
# only surfaces the cheap, unambiguous signal it already has from the screen it
# reads for context%.
_BUSY_RE = re.compile(r"esc to interrupt", re.IGNORECASE)


def _busy_or_none(screen: str) -> Optional[str]:
    if screen and _BUSY_RE.search(screen):
        return "busy"
    return None


_ADAPTERS = {
    "claude": ClaudeAdapter,
    "codex": CodexAdapter,
    "pi": PiAdapter,
}

# Exact foreground process names (from `cmux top`) that pin a runtime.
_PROCESS_EXACT = {
    "claude": "claude",
    "claude.exe": "claude",
    "codex": "codex",
    "codex.exe": "codex",
    "pi": "pi",
    "pi.exe": "pi",
}

# Prefix patterns for runtimes whose real binary name carries a build/arch
# suffix and may be truncated by the process table (e.g. codex ships as
# `codex-aarch64-apple-darwin`, seen truncated as `codex-aarch64-a`). Only
# runtimes with a long, unambiguous stem belong here. `pi` is deliberately
# EXCLUDED — it is too short to prefix-match without catching pip/pipenv/pixi.
_PROCESS_PREFIXES = (
    ("claude-", "claude"),
    ("codex-", "codex"),
)


def get_adapter(runtime: Optional[str]):
    """Return an adapter instance, or None when the runtime has no adapter
    (the fail-closed pivot for lifecycle verbs)."""
    cls = _ADAPTERS.get(runtime or "")
    return cls() if cls else None


def runtime_from_processes(process_names) -> Optional[str]:
    """Identify a target's runtime from its foreground process names.

    Matches by exact name first, then by a curated prefix allow-list so that
    arch-suffixed / truncated binary names (e.g. `codex-aarch64-a`) still
    resolve, WITHOUT over-matching unrelated processes. Returns None when no
    supported runtime is found (-> runtime_unknown, fail closed)."""
    for raw in process_names or []:
        name = raw.strip().lower()
        rt = _PROCESS_EXACT.get(name)
        if rt:
            return rt
        for prefix, runtime in _PROCESS_PREFIXES:
            if name.startswith(prefix):
                return runtime
    return None
