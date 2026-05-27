"""Unit tests for the heuristic scrollback classifier.

The classifier inspects the last ~2 KB of a surface's read-screen output and
returns ``(agent_kind, confidence)``. See ``classify_from_scrollback`` for the
full contract.
"""

from __future__ import annotations

from pathlib import Path

from cmux_observability.collector.classify import (
    SCROLLBACK_WINDOW_BYTES,
    classify_from_scrollback,
)


# --- claude_code -----------------------------------------------------------

CLAUDE_TAIL_FULL = (
    "⏺ Plan landed.\n"
    "❯ run the tests\n"
    "  ctx:42%  /repo  feat/branch\n"
    "  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
)


def test_classify_claude_code_three_markers_high_confidence() -> None:
    kind, conf = classify_from_scrollback(CLAUDE_TAIL_FULL)
    assert kind == "claude_code"
    assert conf == 0.8


def test_classify_claude_code_single_marker_low_confidence() -> None:
    tail = "some random shell noise\nctx:7%\nmore noise\n"
    kind, conf = classify_from_scrollback(tail)
    assert kind == "claude_code"
    assert conf == 0.5


def test_classify_claude_code_from_fixture(fixture_dir: Path) -> None:
    tail = (fixture_dir / "scrollback" / "claude_code.txt").read_text()
    kind, conf = classify_from_scrollback(tail)
    assert kind == "claude_code"
    assert conf >= 0.7


# --- codex -----------------------------------------------------------------

CODEX_TAIL_FULL = (
    "─ Worked for 1m 40s ───\n"
    "\n"
    "› Write tests for @filename\n"
    "\n"
    "  gpt-5.5 xhigh · Context 58% left · ~/repo\n"
)


def test_classify_codex_three_markers_high_confidence() -> None:
    kind, conf = classify_from_scrollback(CODEX_TAIL_FULL)
    assert kind == "codex"
    assert conf == 0.8


def test_classify_codex_single_marker_low_confidence() -> None:
    tail = "build output ...\n─ Worked for 12s ───\n"
    kind, conf = classify_from_scrollback(tail)
    assert kind == "codex"
    assert conf == 0.5


def test_classify_codex_from_fixture(fixture_dir: Path) -> None:
    tail = (fixture_dir / "scrollback" / "codex.txt").read_text()
    kind, conf = classify_from_scrollback(tail)
    assert kind == "codex"
    assert conf >= 0.7


# --- gemini ----------------------------------------------------------------

GEMINI_TAIL_FULL = (
    "✦ Thinking about your request...\n"
    "  Using gemini-2.5-pro\n"
    "\n"
    "> implement step 1\n"
)


def test_classify_gemini_three_markers_high_confidence() -> None:
    kind, conf = classify_from_scrollback(GEMINI_TAIL_FULL)
    assert kind == "gemini"
    assert conf == 0.8


def test_classify_gemini_single_marker_low_confidence() -> None:
    tail = "log output\nbuilt with gemini-2.5-pro\nlog continues\n"
    kind, conf = classify_from_scrollback(tail)
    assert kind == "gemini"
    assert conf == 0.5


def test_classify_gemini_from_fixture(fixture_dir: Path) -> None:
    tail = (fixture_dir / "scrollback" / "gemini.txt").read_text()
    kind, conf = classify_from_scrollback(tail)
    assert kind == "gemini"
    assert conf >= 0.7


# --- negative + edge cases -------------------------------------------------

def test_classify_empty_tail_returns_none() -> None:
    assert classify_from_scrollback("") == (None, 0.0)


def test_classify_whitespace_only_returns_none() -> None:
    assert classify_from_scrollback("   \n\t\n  ") == (None, 0.0)


def test_classify_plain_shell_returns_none(fixture_dir: Path) -> None:
    tail = (fixture_dir / "scrollback" / "plain_shell.txt").read_text()
    assert classify_from_scrollback(tail) == (None, 0.0)


def test_classify_only_inspects_last_window_bytes() -> None:
    # A "trick" claude marker buried in the first KB must NOT match because the
    # classifier should only scan the trailing SCROLLBACK_WINDOW_BYTES.
    trick = "ctx:99%\n❯ tricked you\n⏵⏵ bypass permissions\n"
    padding = "x" * (SCROLLBACK_WINDOW_BYTES + 1024)
    tail = trick + padding
    assert classify_from_scrollback(tail) == (None, 0.0)


def test_classify_mixed_signals_prefers_claude_over_codex() -> None:
    # Both claude and codex markers present in equal count: tie-break order is
    # documented as claude_code > codex > gemini.
    tail = (
        "ctx:55%\n"
        "❯ hello\n"
        "─ Worked for 2s ──\n"
        "  gpt-5.5 xhigh\n"
    )
    kind, conf = classify_from_scrollback(tail)
    assert kind == "claude_code"
    assert conf >= 0.5


def test_classify_mixed_signals_codex_outranks_gemini_on_tie() -> None:
    # One codex marker vs one gemini marker — tie-break must pick codex.
    tail = (
        "─ Worked for 9s ──\n"
        "  using gemini-2.5-pro\n"
    )
    kind, conf = classify_from_scrollback(tail)
    assert kind == "codex"
    assert conf == 0.5


def test_classify_higher_marker_count_wins_over_tie_break() -> None:
    # Three codex markers beats one claude marker even though claude tie-breaks
    # ahead — counts dominate the decision, tie-break is only for equal counts.
    tail = (
        "ctx:33%\n"
        "› follow up\n"
        "─ Worked for 4s ──\n"
        "  gpt-5.5 xhigh · Context 12% left\n"
    )
    kind, conf = classify_from_scrollback(tail)
    assert kind == "codex"
    assert conf == 0.8
