"""v1.2 Phase D — cli.py scrollback-driven state wiring.

Exercises ``cli._classify_from_scrollback`` (the pure helper called by
``cmd_collect`` after the heuristic-promotion loop). Uses real Phase B
scrollback fixtures so behaviour reflects the deployed classifier, not
monkeypatched returns.

Precedence under test (highest wins):
  1. ``state_source == "agent_summary"`` — not exercised here (set by step 3).
  2. ``state_source == "scrollback"`` — new; overrides cmux_tag when
     scrollback says ``needs_input`` at confidence >= 0.7, and promotes
     state for agents currently ``state == "unknown"`` at conf >= 0.5.
  3. ``state_source == "cmux_tag"`` — wins for plain running/idle.
  4. ``state_source == "heuristic"`` — fallback ``unknown``.

Failure emission scope (team-lead clarification): the disagreement
``Failure(component="state_classifier", ...)`` is emitted ONLY when the
agent's prior ``state_source == "cmux_tag"``. Heuristic-promoted agents
(state_source=heuristic, state=unknown) flipped to needs_input by
scrollback do NOT emit a Failure — that's promotion, not contradiction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cmux_observability.cli import _classify_from_scrollback
from cmux_observability.errors import Failure
from cmux_observability.model import Agent, Snapshot


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "scrollback"


def _read(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


def _snap_with_agent(agent: Agent) -> Snapshot:
    return Snapshot(
        schema_version=2,
        captured_at=datetime(2026, 5, 28, 12, 0, 0, tzinfo=timezone.utc),
        host="localhost",
        cmux_version=None,
        workspaces=[],
        agents=[agent],
    )


def _agent(
    *, state: str, state_source: str, kind: str = "claude_code",
    surface_ref: str = "sfc:1",
    type_source: str | None = None,
) -> Agent:
    # Default type_source mirrors state_source for the common cells (cmux_tag
    # state ↔ cmux_tag type). Heuristic-promoted agents start with
    # type_source="heuristic" too — pass it explicitly to match real shape.
    if type_source is None:
        type_source = "heuristic" if state_source == "heuristic" else "cmux_tag"
    return Agent(
        surface_ref=surface_ref,
        workspace_ref="ws:1",
        type=kind,
        type_source=type_source,
        type_confidence=1.0,
        state=state,
        state_source=state_source,
        pid=None,
    )


# ---------------------------------------------------------------------------
# 8 cells covering the precedence ladder + disagreement-Failure scope.
# ---------------------------------------------------------------------------


def test_cell1_cmux_running_scrollback_running_no_change() -> None:
    """cmux_tag=running + scrollback=running → no disagreement, no change."""
    agent = _agent(state="running", state_source="cmux_tag")
    snap = _snap_with_agent(agent)
    screens = {agent.surface_ref: _read("claude_code_running__thinking.txt")}
    failures: list[Failure] = []

    _classify_from_scrollback(snap, screens, failures)

    assert agent.state == "running"
    assert agent.state_source == "cmux_tag"
    assert failures == []


def test_cell2_cmux_running_scrollback_needs_input_emits_failure() -> None:
    """cmux_tag=running + scrollback=needs_input >=0.7 → flip + Failure."""
    agent = _agent(state="running", state_source="cmux_tag")
    snap = _snap_with_agent(agent)
    screens = {
        agent.surface_ref: _read("claude_code_needs_input__direct_ask.txt"),
    }
    failures: list[Failure] = []

    _classify_from_scrollback(snap, screens, failures)

    assert agent.state == "needs_input"
    assert agent.state_source == "scrollback"
    assert len(failures) == 1
    f = failures[0]
    assert f.component == "state_classifier"
    assert f.target == agent.surface_ref
    assert "scrollback overrode cmux_tag='running'" in f.message
    assert f.fatal is False


def test_cell3_cmux_idle_scrollback_needs_input_emits_failure() -> None:
    """cmux_tag=idle + scrollback=needs_input >=0.7 → flip + Failure (idle)."""
    agent = _agent(state="idle", state_source="cmux_tag")
    snap = _snap_with_agent(agent)
    screens = {
        agent.surface_ref: _read(
            "claude_code_needs_input__numbered_questions.txt"
        ),
    }
    failures: list[Failure] = []

    _classify_from_scrollback(snap, screens, failures)

    assert agent.state == "needs_input"
    assert agent.state_source == "scrollback"
    assert len(failures) == 1
    assert "scrollback overrode cmux_tag='idle'" in failures[0].message


def test_cell4_cmux_needs_input_wins_no_change() -> None:
    """cmux_tag=needs_input already wins; scrollback=running is ignored."""
    agent = _agent(state="needs_input", state_source="cmux_tag")
    snap = _snap_with_agent(agent)
    screens = {agent.surface_ref: _read("claude_code_running__thinking.txt")}
    failures: list[Failure] = []

    _classify_from_scrollback(snap, screens, failures)

    assert agent.state == "needs_input"
    assert agent.state_source == "cmux_tag"
    assert failures == []


def test_cell5_heuristic_promote_to_needs_input_no_failure() -> None:
    """heuristic+unknown + scrollback=needs_input >=0.7 → promote, NO Failure.

    Promotion from heuristic is not disagreement; the cmux_tag Failure
    log is reserved for genuine contradictions.
    """
    agent = _agent(state="unknown", state_source="heuristic")
    snap = _snap_with_agent(agent)
    screens = {
        agent.surface_ref: _read("claude_code_needs_input__direct_ask.txt"),
    }
    failures: list[Failure] = []

    _classify_from_scrollback(snap, screens, failures)

    assert agent.state == "needs_input"
    assert agent.state_source == "scrollback"
    assert failures == []


def test_cell6_heuristic_promote_to_running_no_failure() -> None:
    """heuristic+unknown + scrollback=running >=0.5 (here 0.9) → promote."""
    agent = _agent(state="unknown", state_source="heuristic")
    snap = _snap_with_agent(agent)
    screens = {agent.surface_ref: _read("claude_code_running__thinking.txt")}
    failures: list[Failure] = []

    _classify_from_scrollback(snap, screens, failures)

    assert agent.state == "running"
    assert agent.state_source == "scrollback"
    assert failures == []


def test_cell7_no_screen_entry_no_change() -> None:
    """Agent without a screens entry is skipped (cmux idle/unknown path)."""
    agent = _agent(state="idle", state_source="cmux_tag")
    snap = _snap_with_agent(agent)
    screens: dict[str, str] = {}
    failures: list[Failure] = []

    _classify_from_scrollback(snap, screens, failures)

    assert agent.state == "idle"
    assert agent.state_source == "cmux_tag"
    assert failures == []


def test_cell8_low_confidence_no_change() -> None:
    """Scrollback returning ``("unknown", 0.0)`` is a no-op.

    A plain shell fixture routes through generic (kind=None) and falls into
    unknown; even if it didn't, conf < 0.5 must not mutate the agent.
    """
    agent = _agent(state="unknown", state_source="heuristic", kind="claude_code")
    snap = _snap_with_agent(agent)
    # plain_shell.txt has no agent chrome and no question markers → unknown.
    screens = {agent.surface_ref: _read("plain_shell.txt")}
    failures: list[Failure] = []

    _classify_from_scrollback(snap, screens, failures)

    assert agent.state == "unknown"
    assert agent.state_source == "heuristic"
    assert failures == []
