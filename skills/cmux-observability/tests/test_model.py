from datetime import datetime, timezone

import cmux_observability.model as M
from cmux_observability.errors import Failure
from cmux_observability.model import Agent, Snapshot, Summary, Theme


def test_model_exports_expected_dataclasses():
    for name in (
        "Agent", "Snapshot", "Summary", "Surface", "Theme", "Workspace",
        "Productivity", "HistoryPoint", "HistorySeries", "RepoStats",
    ):
        assert hasattr(M, name)


def test_snapshot_construction_with_minimal_fields():
    snap = Snapshot(
        schema_version=1,
        captured_at=datetime(2026, 5, 27, 14, 30, 0, tzinfo=timezone.utc),
        host="laptop",
        cmux_version="1.2.3",
        workspaces=[],
        agents=[],
        themes=[],
        productivity=None,
        history=None,
        failures=[],
    )
    assert snap.schema_version == 1
    assert snap.workspaces == []


def test_agent_with_optional_summary_and_theme_construction():
    summary = Summary(
        text="working on parser tests",
        state_hint="running",
        needs_input_reason=None,
        confidence=0.9,
        cache_hit=False,
        cached_at=datetime.now(timezone.utc),
        prompt_version=1,
        screen_hash="deadbeef",
        redactions_applied=[],
        redaction_summary="no secrets",
    )
    agent = Agent(
        surface_ref="surface:1",
        workspace_ref="workspace:1",
        type="claude_code",
        type_source="cmux_tag",
        type_confidence=1.0,
        state="running",
        state_source="cmux_tag",
        pid=12345,
        summary=summary,
    )
    assert agent.summary is summary

    theme = Theme(
        label="parser work",
        member_refs=["surface:1"],
        why="agent is writing pytest fixtures for the cmux tree parser",
        confidence=0.7,
    )
    assert theme.label == "parser work"


def test_failure_default_not_fatal():
    f = Failure(component="cmux", target=None, message="binary missing")
    assert f.fatal is False
