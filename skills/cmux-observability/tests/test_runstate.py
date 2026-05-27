"""Runstate JSON roundtrip + lazy HOME resolution."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from cmux_observability import runstate
from cmux_observability.errors import Failure
from cmux_observability.model import (
    Agent,
    HistoryPoint,
    HistorySeries,
    Productivity,
    RepoStats,
    Snapshot,
    Summary,
    Surface,
    Theme,
    Workspace,
)


def _make_snapshot() -> Snapshot:
    now = datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc)
    surface = Surface(
        ref="surface-1",
        pane_ref="pane-1",
        workspace_ref="ws-1",
        kind="terminal",
        title="claude",
        is_agent=True,
    )
    workspace = Workspace(
        ref="ws-1", title="proj", window_ref="win-1", surfaces=[surface],
    )
    summary = Summary(
        text="working on tests",
        state_hint="running",
        needs_input_reason=None,
        confidence=0.9,
        cache_hit=False,
        cached_at=now,
        prompt_version=1,
        screen_hash="deadbeef",
        redactions_applied=["api_key"],
        redaction_summary="1 redaction",
    )
    agent = Agent(
        surface_ref="surface-1",
        workspace_ref="ws-1",
        type="claude_code",
        type_source="cmux_tag",
        type_confidence=0.95,
        state="running",
        state_source="cmux_tag",
        pid=1234,
        summary=summary,
    )
    theme = Theme(
        label="auth-refactor",
        member_refs=["surface-1"],
        why="both agents touching auth/",
        confidence=0.8,
    )
    productivity = Productivity(
        repos=[
            RepoStats(
                path="/tmp/repo",
                name="repo",
                commits={"today": 1, "week": 3, "30d": 5},
                last_commit_at=now,
            )
        ],
        totals={"today": 1, "week": 3, "30d": 5},
    )
    history = HistorySeries(
        points=[
            HistoryPoint(
                captured_at=now,
                agents_total=1,
                agents_running=1,
                agents_needs_input=0,
                by_type={"claude_code": 1},
            )
        ]
    )
    failure = Failure(
        component="read_screen", target="surface-1",
        message="degraded", fatal=False,
    )
    return Snapshot(
        schema_version=1,
        captured_at=now,
        host="localhost",
        cmux_version="0.42",
        workspaces=[workspace],
        agents=[agent],
        themes=[theme],
        productivity=productivity,
        history=history,
        failures=[failure],
    )


def test_runstate_roundtrip_under_fake_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """write → read → discard against a $HOME-derived state dir.

    Lazy HOME resolution: monkeypatching $HOME AFTER importing the module
    must still route writes under tmp_path, not the operator's real
    ~/.local/state.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    snap = _make_snapshot()
    run_id = runstate.new_run_id()
    runstate.write(
        run_id, snap,
        screen_hashes={"surface-1": "deadbeef"},
        redactions_by_surface={"surface-1": ["api_key"]},
    )

    # State file must land under our fake HOME, not the operator's real one.
    state_file = runstate.state_path(run_id)
    assert str(state_file).startswith(str(home)), (
        f"state path {state_file} escaped fake HOME {home}"
    )
    assert state_file.exists()

    restored, screen_hashes, redactions = runstate.read(run_id)
    assert screen_hashes == {"surface-1": "deadbeef"}
    assert redactions == {"surface-1": ["api_key"]}

    # Datetimes must rehydrate as datetime objects, not isoformat strings.
    assert isinstance(restored.captured_at, datetime)
    assert restored.agents and restored.agents[0].summary is not None
    assert isinstance(restored.agents[0].summary.cached_at, datetime)
    assert restored.productivity and restored.productivity.repos
    assert isinstance(restored.productivity.repos[0].last_commit_at, datetime)
    assert restored.history and restored.history.points
    assert isinstance(restored.history.points[0].captured_at, datetime)

    # Other fields survive faithfully.
    assert restored.themes and restored.themes[0].label == "auth-refactor"
    assert restored.failures and restored.failures[0].component == "read_screen"
    assert restored.workspaces[0].surfaces[0].ref == "surface-1"

    runstate.discard(run_id)
    assert not state_file.exists()
