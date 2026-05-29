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


# ---------------------------------------------------------------------------
# v1.2 — state_from_scrollback (post-Phase-B catalogue)
#
# Authoritative catalogue: see the v1.2 spec
# (cmux-observability-scrollback-state-design-2026-05-28.md, "Pattern catalogue"
# section, post-Phase-B revision).
#
# Design notes:
# - Autocomplete ghost text fills the prompt rail in real terminals, so
#   empty-prompt-line heuristics (`^❯ *$` / `^› *$`) never fire. Patterns
#   anchor on chrome-surrounding signals, not prompt-line emptiness.
# - Per-pattern weights, not the kind-classifier's count-ladder. Final
#   confidence is max-of-matching-weights (redundant signals don't compound).
# - Precedence inside this function: needs_input first (highest user impact),
#   then running, then idle. Return on first hit.
# - idle is a conjunct ("all of" the listed markers); the broader fallback
#   below catches the "quiet but no completion marker" case (claude_code_idle
#   __quiet fixture).
# ---------------------------------------------------------------------------

# Window: last ~24 lines OR ~2 KB whichever shorter.
_STATE_WINDOW_BYTES = 2048
_STATE_WINDOW_LINES = 24


# --- claude_code ---------------------------------------------------------

# needs_input markers, ordered for the per-pattern weight table below.
_CC_NI_PATTERNS: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"\bNext:\s*(confirm|decide)\b"),                                 0.7),
    (re.compile(r"\bWant me to\b"),                                               0.7),
    (re.compile(r"\bDo you want to\b"),                                           0.7),
    (re.compile(r"\bQuestion:.*\?", re.DOTALL),                                   0.8),
    (re.compile(r"\bopen questions?\b", re.IGNORECASE),                           0.7),
    # Numbered list whose items end in `?` — narrative "open questions" form
    # where the prompt itself is not `^❯ 1\. `.
    (re.compile(r"(?m)^\s+\d+\.\s.*\?\s*$"),                                      0.7),
    (re.compile(r"(?m)^❯\s+1\.\s"),                                               0.8),
    (re.compile(r"\(y/N\)|\[Y/n\]|\bAre you sure\b"),                             0.8),
)

# running markers — unambiguous on single match.
_CC_RUN_PATTERNS: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"\(esc to interrupt\)"),                                         0.9),
    # ✻ active-thinking line, e.g. `(3m 42s · almost done thinking with high…)`
    (re.compile(r"\(\d+[hms].*·.*(almost done )?thinking", re.IGNORECASE),        0.9),
)

# claude_code idle chrome markers. Phase B fixture spread (`__quiet` has no
# completion marker at tail) collapsed the catalogue's strict
# completion-marker conjunct down to a chrome-presence check after
# running/needs_input markers have already been ruled out.
_CC_CHROME = (
    re.compile(r"ctx:\d+%"),
    re.compile(r"⏵⏵ bypass permissions"),
    re.compile(r"(?m)^\s*❯\s*$"),
    re.compile(r"(?m)^\s*❯\s"),
)


# --- codex ---------------------------------------------------------------

_CX_NI_PATTERNS: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"\bQuestion:.*\?", re.DOTALL),                                   0.8),
    (re.compile(r"(?m)^›\s+1\.\s"),                                               0.8),
    (re.compile(r"\(y/N\)|\[Y/n\]|\bAre you sure\b"),                             0.8),
)

_CX_RUN_PATTERNS: tuple[tuple[re.Pattern[str], float], ...] = (
    # `• Working (3s • esc to interrupt)` — the bullet between digits and
    # "esc to interrupt" is U+2022, so we match laxly with `.*`.
    (re.compile(r"•\s*Working\s*\(.*esc to interrupt\)"),                         0.9),
    (re.compile(r"•\s*Thinking\b"),                                               0.9),
)

# codex idle: `─ Worked for 1m 21s` anywhere in the tail window. We drop
# the trailing `─` requirement because the line of horizontal-rule glyphs
# that follows the duration can wrap arbitrarily long in cmux output, and
# qa_lead's Phase E spot-check found the strict-tail-closure form failing
# on real codex idle screens where the Worked-for line is not the literal
# last line (placeholder + chrome lines follow it).
_CX_WORKED_FOR_ANY = re.compile(r"─\s*Worked for \d+[hms]")
_CX_CHROME = (
    re.compile(r"Context \d+% left"),
    re.compile(r"\bgpt-\d"),
    # Autocomplete placeholders shown in the empty prompt rail.
    re.compile(
        r"›\s*(Write tests|Find and fix|Improve documentation|Run /review|Use /skills)"
    ),
)


# --- generic -------------------------------------------------------------

_GEN_NI_PATTERNS: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"\(y/N\)|\[Y/n\]|\bAre you sure\b"),                             0.8),
    (re.compile(r"Press [Ee]nter to (continue|cancel)"),                          0.7),
)

# Agent-chrome detector for the "bare `?` narrative AND no agent chrome"
# fallback rule.
_AGENT_CHROME_ANY = re.compile(
    r"ctx:\d+%|⏵⏵ bypass permissions|Context \d+% left|\bgpt-\d|─ Worked for "
)
_GENERIC_QUESTION_LINE = re.compile(r"(?m)^[^?\n]*\?\s*$")


def _state_window(tail: str) -> str:
    """Clip `tail` to the last ~24 lines within the last ~2 KB byte budget."""
    encoded = tail.encode("utf-8", errors="replace")
    if len(encoded) > _STATE_WINDOW_BYTES:
        encoded = encoded[-_STATE_WINDOW_BYTES:]
    window = encoded.decode("utf-8", errors="replace")
    lines = window.splitlines()
    if len(lines) > _STATE_WINDOW_LINES:
        lines = lines[-_STATE_WINDOW_LINES:]
    return "\n".join(lines)


def _best_weight(
    patterns: tuple[tuple[re.Pattern[str], float], ...], window: str
) -> float:
    """Max weight across matching patterns; 0.0 when none match."""
    best = 0.0
    for pat, weight in patterns:
        if pat.search(window) and weight > best:
            best = weight
    return best


def state_from_scrollback(tail: str, kind: str | None) -> tuple[str, float]:
    """Return ("running"|"needs_input"|"idle"|"unknown", confidence in [0,1]).

    Uses kind-specific markers (claude_code, codex) when known; generic
    confirm-prompt patterns when ``kind is None``. Any other kind value
    (e.g. ``"gemini"`` — punted at v1.2) returns ``("unknown", 0.0)``.

    Precedence inside the function: needs_input > running > idle. Returns
    on first hit. Confidence is max-of-matching-pattern-weights, not summed.
    """
    if not tail or not tail.strip():
        return ("unknown", 0.0)

    window = _state_window(tail)

    if kind == "claude_code":
        w = _best_weight(_CC_NI_PATTERNS, window)
        if w > 0.0:
            return ("needs_input", w)
        w = _best_weight(_CC_RUN_PATTERNS, window)
        if w > 0.0:
            return ("running", w)
        # idle: chrome present AND no running/needs_input signals (caught
        # above). Phase-B fixtures (`__quiet`, `__just_finished`) both fall
        # through to this chrome-only check.
        chrome_hit = any(p.search(window) for p in _CC_CHROME)
        if chrome_hit:
            return ("idle", 0.7)
        return ("unknown", 0.0)

    if kind == "codex":
        w = _best_weight(_CX_NI_PATTERNS, window)
        if w > 0.0:
            return ("needs_input", w)
        w = _best_weight(_CX_RUN_PATTERNS, window)
        if w > 0.0:
            return ("running", w)
        chrome_hit = any(p.search(window) for p in _CX_CHROME)
        # idle: `─ Worked for N` anywhere in the window AND codex chrome
        # present. Worked-for + chrome is the strong-signal conjunct.
        if _CX_WORKED_FOR_ANY.search(window) and chrome_hit:
            return ("idle", 0.7)
        # idle fallback: chrome alone is weak evidence of an idle codex
        # pane (not a running one); prefer best-effort idle over unknown.
        if chrome_hit:
            return ("idle", 0.6)
        return ("unknown", 0.0)

    if kind is None:
        w = _best_weight(_GEN_NI_PATTERNS, window)
        if w > 0.0:
            return ("needs_input", w)
        # Bare `?`-terminated narrative line AND no agent chrome present.
        if _GENERIC_QUESTION_LINE.search(window) and not _AGENT_CHROME_ANY.search(
            window
        ):
            return ("needs_input", 0.5)
        return ("unknown", 0.0)

    # Unrecognized kind (gemini punted in v1.2; future kinds default-safe).
    return ("unknown", 0.0)
