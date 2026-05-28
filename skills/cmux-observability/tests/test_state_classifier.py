"""v1.2 — scrollback-driven state classifier tests.

Parametrized over the 13 fixture files in tests/fixtures/scrollback/ that
qa_lead delivered in Phase B. Each entry pins one fixture filename to its
expected `(kind, state, min_confidence)`. Bands follow the post-Phase-B
calibration ladder:

    running       → 0.9 on single unambiguous match
    needs_input   → 0.7-0.8 per pattern strength (max-of-matching-weights)
    idle          → 0.7 on full conjunct
    unknown       → 0.0 (no match)

Phase C tunes patterns until every cell here is green. Fixture cells with
no file fall back to skip (legacy guard from the scaffold).
"""
from pathlib import Path

import pytest

from cmux_observability.collector.classify import state_from_scrollback

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "scrollback"

# (filename, kind_for_classifier, expected_state, min_confidence)
# kind_for_classifier=None routes through generic patterns.
EXPECTED_FIXTURES: list[tuple[str, str | None, str, float]] = [
    # claude_code — needs_input (weighted markers)
    ("claude_code_needs_input__direct_ask.txt",         "claude_code", "needs_input", 0.7),
    ("claude_code_needs_input__numbered_questions.txt", "claude_code", "needs_input", 0.7),
    # claude_code — running (unambiguous markers)
    ("claude_code_running__thinking.txt",               "claude_code", "running",     0.9),
    # claude_code — idle (full conjunct)
    ("claude_code_idle__quiet.txt",                     "claude_code", "idle",        0.7),
    ("claude_code_idle__just_finished.txt",             "claude_code", "idle",        0.7),
    # codex — needs_input
    ("codex_needs_input__question_block.txt",           "codex",       "needs_input", 0.8),
    # codex — running
    ("codex_running__working.txt",                      "codex",       "running",     0.9),
    # codex — idle (full conjunct)
    ("codex_idle__worked_for.txt",                      "codex",       "idle",        0.7),
    # generic — needs_input
    ("generic_needs_input__y_n_prompt.txt",             None,          "needs_input", 0.8),
    ("generic_needs_input__press_enter.txt",            None,          "needs_input", 0.7),
    # generic — unknown (negative fixtures)
    ("generic_unknown__bash_idle.txt",                  None,          "unknown",     0.0),
    ("generic_unknown__vim.txt",                        None,          "unknown",     0.0),
    ("generic_unknown__tail_f.txt",                     None,          "unknown",     0.0),
]


@pytest.mark.parametrize(
    "fixture_name,kind,expected_state,min_conf",
    EXPECTED_FIXTURES,
    ids=[f[0] for f in EXPECTED_FIXTURES],
)
def test_state_from_scrollback_matches_fixture(
    fixture_name: str, kind: str | None, expected_state: str, min_conf: float
) -> None:
    fp = FIXTURES_DIR / fixture_name
    if not fp.exists():
        pytest.skip(f"fixture missing: {fixture_name} — captured in Phase B")
    tail = fp.read_text(encoding="utf-8", errors="replace")
    actual_state, actual_conf = state_from_scrollback(tail, kind)
    assert actual_state == expected_state, (
        f"{fixture_name}: expected state={expected_state!r} got {actual_state!r} "
        f"(conf={actual_conf})"
    )
    assert actual_conf >= min_conf, (
        f"{fixture_name}: conf {actual_conf} < band {min_conf}"
    )


def test_state_from_scrollback_empty_returns_unknown() -> None:
    assert state_from_scrollback("", None) == ("unknown", 0.0)
    assert state_from_scrollback("   \n\n  ", "claude_code") == ("unknown", 0.0)


def test_state_from_scrollback_signature_returns_tuple() -> None:
    result = state_from_scrollback("anything", None)
    assert isinstance(result, tuple) and len(result) == 2
    assert isinstance(result[0], str)
    assert isinstance(result[1], float)
    assert result[0] in {"running", "needs_input", "idle", "unknown"}
    assert 0.0 <= result[1] <= 1.0
