"""Scrollback-driven state ladder wiring (ported from observability's v1.2
Phase D test_cli_state_wiring.py). Exercises capture.classify_states_from_scrollback
against real Phase B scrollback fixtures.

Precedence under test (highest wins):
  1. state_source == "scrollback" — overrides cmux_tag when scrollback says
     needs_input at confidence >= 0.7, and promotes state for agents currently
     state == "unknown" at conf >= 0.5.
  2. state_source == "cmux_tag" — wins for plain running/idle.
  3. state_source == "heuristic" — fallback unknown.

Failure emission scope: the disagreement state_classifier Failure is emitted
ONLY when the agent's prior state_source == "cmux_tag". Heuristic-promoted
agents flipped to needs_input do NOT emit a Failure — that's promotion, not
contradiction.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import capture as cap  # noqa: E402


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "scrollback"


def _read(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


def _agent(
    *, state: str, state_source: str, kind: str = "claude_code",
    surface_ref: str = "sfc:1", type_source: str | None = None,
) -> cap.CapAgent:
    if type_source is None:
        type_source = "heuristic" if state_source == "heuristic" else "cmux_tag"
    return cap.CapAgent(
        surface_ref=surface_ref, workspace_ref="ws:1", type=kind,
        type_source=type_source, type_confidence=1.0,
        state=state, state_source=state_source, pid=None,
    )


def test_cell1_cmux_running_scrollback_running_no_change():
    agent = _agent(state="running", state_source="cmux_tag")
    screens = {agent.surface_ref: _read("claude_code_running__thinking.txt")}
    failures: list[cap.CapFailure] = []
    cap.classify_states_from_scrollback([agent], screens, failures)
    assert agent.state == "running"
    assert agent.state_source == "cmux_tag"
    assert failures == []


def test_cell2_cmux_running_scrollback_needs_input_emits_failure():
    agent = _agent(state="running", state_source="cmux_tag")
    screens = {agent.surface_ref: _read("claude_code_needs_input__direct_ask.txt")}
    failures: list[cap.CapFailure] = []
    cap.classify_states_from_scrollback([agent], screens, failures)
    assert agent.state == "needs_input"
    assert agent.state_source == "scrollback"
    assert len(failures) == 1
    f = failures[0]
    assert f.component == "state_classifier"
    assert f.target == agent.surface_ref
    assert "scrollback overrode cmux_tag='running'" in f.message
    assert f.fatal is False


def test_cell3_cmux_idle_scrollback_needs_input_emits_failure():
    agent = _agent(state="idle", state_source="cmux_tag")
    screens = {agent.surface_ref: _read("claude_code_needs_input__numbered_questions.txt")}
    failures: list[cap.CapFailure] = []
    cap.classify_states_from_scrollback([agent], screens, failures)
    assert agent.state == "needs_input"
    assert agent.state_source == "scrollback"
    assert len(failures) == 1
    assert "scrollback overrode cmux_tag='idle'" in failures[0].message


def test_cell4_cmux_needs_input_wins_no_change():
    agent = _agent(state="needs_input", state_source="cmux_tag")
    screens = {agent.surface_ref: _read("claude_code_running__thinking.txt")}
    failures: list[cap.CapFailure] = []
    cap.classify_states_from_scrollback([agent], screens, failures)
    assert agent.state == "needs_input"
    assert agent.state_source == "cmux_tag"
    assert failures == []


def test_cell5_heuristic_promote_to_needs_input_no_failure():
    agent = _agent(state="unknown", state_source="heuristic")
    screens = {agent.surface_ref: _read("claude_code_needs_input__direct_ask.txt")}
    failures: list[cap.CapFailure] = []
    cap.classify_states_from_scrollback([agent], screens, failures)
    assert agent.state == "needs_input"
    assert agent.state_source == "scrollback"
    assert failures == []


def test_cell6_heuristic_promote_to_running_no_failure():
    agent = _agent(state="unknown", state_source="heuristic")
    screens = {agent.surface_ref: _read("claude_code_running__thinking.txt")}
    failures: list[cap.CapFailure] = []
    cap.classify_states_from_scrollback([agent], screens, failures)
    assert agent.state == "running"
    assert agent.state_source == "scrollback"
    assert failures == []


def test_cell7_no_screen_entry_no_change():
    agent = _agent(state="idle", state_source="cmux_tag")
    screens: dict[str, str] = {}
    failures: list[cap.CapFailure] = []
    cap.classify_states_from_scrollback([agent], screens, failures)
    assert agent.state == "idle"
    assert agent.state_source == "cmux_tag"
    assert failures == []


def test_cell8_low_confidence_no_change():
    agent = _agent(state="unknown", state_source="heuristic", kind="claude_code")
    screens = {agent.surface_ref: _read("plain_shell.txt")}
    failures: list[cap.CapFailure] = []
    cap.classify_states_from_scrollback([agent], screens, failures)
    assert agent.state == "unknown"
    assert agent.state_source == "heuristic"
    assert failures == []
