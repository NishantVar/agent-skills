"""Heuristic scrollback classifier.

Inspects the last :data:`SCROLLBACK_WINDOW_BYTES` of a surface's read-screen
output and decides whether it looks like a coding agent (claude_code, codex,
or gemini). Used as a fallback when ``cmux_tag`` is absent.

Marker regexes were derived from live ``cmux read-screen`` output:

* ``claude_code`` — the Claude Code CLI's footer/prompt rail (``❯`` prompt,
  ``ctx:NN%`` context badge, ``⏵⏵ bypass permissions`` permission hint, plus
  the ``⏺`` bullet used for agent messages and the literal ``claude-code``
  substring shown in the update banner).
* ``codex`` — Codex CLI markers (``› `` prompt prefix, ``─ Worked for ...``
  trailer, the ``xhigh``/``Context NN% left`` status line, and the literal
  ``codex`` substring).
* ``gemini`` — Gemini CLI markers (``✦`` sparkle bullet, ``gemini-N.N``
  model tag, ``Using gemini`` line). Best-effort: no live Gemini surface was
  available for sampling. qa_lead validates against live Gemini scrollback at
  the Phase-1 mid-checkpoint smoke.

Tie-break order on equal marker counts: ``claude_code`` > ``codex`` >
``gemini``. Counts always dominate; tie-break is only consulted when two or
more kinds match the same number of distinct markers.
"""

from __future__ import annotations

import re


SCROLLBACK_WINDOW_BYTES = 2048


_CLAUDE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ctx:\d+%"),
    re.compile(r"(?m)^\s*❯ "),
    re.compile(r"⏵⏵ bypass permissions"),
    re.compile(r"(?m)^\s*⏺ "),
    re.compile(r"claude-code"),
)

_CODEX_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?m)^\s*› "),
    re.compile(r"─ Worked for "),
    re.compile(r"\bxhigh\b"),
    re.compile(r"Context \d+% left"),
    re.compile(r"\bcodex\b"),
)

_GEMINI_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?m)^\s*✦ "),
    re.compile(r"\bgemini-\d"),
    re.compile(r"Using gemini\b"),
)


# Ordered to encode the tie-break: earlier wins when counts are equal.
_KINDS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    ("claude_code", _CLAUDE_PATTERNS),
    ("codex",       _CODEX_PATTERNS),
    ("gemini",      _GEMINI_PATTERNS),
)


def classify_from_scrollback(tail: str) -> tuple[str | None, float]:
    """Inspect the last ~2 KB of a surface's screen text and decide if it looks
    like a coding agent. Returns ``(agent_kind, confidence)`` or
    ``(None, 0.0)``.

    ``agent_kind`` is one of ``"claude_code"``, ``"codex"``, ``"gemini"``.
    ``confidence`` is ``0.5`` for one matching marker, ``0.7`` for two,
    ``0.8`` for three or more.
    """
    if not tail or not tail.strip():
        return (None, 0.0)

    # Tail-truncate on byte boundary so the window cap is honest for non-ASCII
    # content. UTF-8 boundary repair is left to the decoder; we only care that
    # the *byte* window is bounded.
    encoded = tail.encode("utf-8", errors="replace")
    if len(encoded) > SCROLLBACK_WINDOW_BYTES:
        encoded = encoded[-SCROLLBACK_WINDOW_BYTES:]
    window = encoded.decode("utf-8", errors="replace")

    best_kind: str | None = None
    best_count = 0
    for kind, patterns in _KINDS:
        count = sum(1 for p in patterns if p.search(window))
        if count > best_count:
            best_kind = kind
            best_count = count

    if best_count == 0:
        return (None, 0.0)

    if best_count == 1:
        confidence = 0.5
    elif best_count == 2:
        confidence = 0.7
    else:
        confidence = 0.8

    return (best_kind, confidence)
