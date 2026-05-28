"""v1.2 — scrollback-driven state classifier tests.

Parametrized over fixture files in tests/fixtures/scrollback/. Each fixture
filename encodes the expected classification: <kind>_<state>__<note>.txt.
Tests are skipped (not failed) when their fixture cell is absent — Phase B
populates fixtures, then this matrix goes red until Phase C tunes patterns
to green.
"""
from pathlib import Path

import pytest

from cmux_observability.collector.classify import state_from_scrollback

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "scrollback"

# (kind, expected_state, min_confidence) — kind="generic" means generic prompts
EXPECTED_CELLS = [
    ("claude_code", "needs_input", 0.6),
    ("claude_code", "running", 0.5),
    ("claude_code", "idle", 0.5),
    ("codex", "needs_input", 0.6),
    ("codex", "running", 0.5),
    ("gemini", "needs_input", 0.5),  # gemini live count unknown; relaxed bound
    ("generic", "needs_input", 0.5),
    ("generic", "unknown", 0.0),  # plain shell idle, vim, less, tail-f
]


def _fixture_files(kind: str, state: str) -> list[Path]:
    pattern = f"{kind}_{state}__*.txt"
    return sorted(FIXTURES_DIR.glob(pattern))


@pytest.mark.parametrize(
    "kind,expected_state,min_conf",
    EXPECTED_CELLS,
)
def test_state_from_scrollback_matches_fixture(kind, expected_state, min_conf):
    files = _fixture_files(kind, expected_state)
    if not files:
        pytest.skip(
            f"no fixture yet for ({kind}, {expected_state}) — captured in Phase B"
        )
    for fp in files:
        tail = fp.read_text(encoding="utf-8", errors="replace")
        passed_kind = None if kind == "generic" else kind
        actual_state, actual_conf = state_from_scrollback(tail, passed_kind)
        assert actual_state == expected_state, (
            f"{fp.name}: expected state={expected_state!r} got {actual_state!r} "
            f"(conf={actual_conf})"
        )
        assert actual_conf >= min_conf, (
            f"{fp.name}: conf {actual_conf} < band {min_conf}"
        )


def test_state_from_scrollback_empty_returns_unknown():
    assert state_from_scrollback("", None) == ("unknown", 0.0)
    assert state_from_scrollback("   \n\n  ", "claude_code") == ("unknown", 0.0)


def test_state_from_scrollback_signature_returns_tuple():
    result = state_from_scrollback("anything", None)
    assert isinstance(result, tuple) and len(result) == 2
    assert isinstance(result[0], str)
    assert isinstance(result[1], float)
    assert result[0] in {"running", "needs_input", "idle", "unknown"}
    assert 0.0 <= result[1] <= 1.0
