import json
from datetime import datetime, timezone
from pathlib import Path

from cmux_observability.model import (
    Agent,
    Snapshot,
    Summary,
    Surface,
    Theme,
    Workspace,
)
from cmux_observability.persist import append_snapshot, connect, migrate


def _empty_snapshot() -> Snapshot:
    return Snapshot(
        schema_version=1,
        captured_at=datetime(2026, 5, 27, 14, 30, 0, tzinfo=timezone.utc),
        host="h", cmux_version=None,
        workspaces=[], agents=[], themes=[],
        productivity=None, history=None, failures=[],
    )


def test_migrate_creates_tables(tmp_path: Path):
    db = tmp_path / "obs.sqlite"
    with connect(db) as conn:
        migrate(conn)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    names = [r[0] for r in rows]
    assert "snapshots" in names
    assert "agent_observations" in names
    assert "summary_cache" in names


def test_append_snapshot_inserts_row(tmp_path: Path):
    db = tmp_path / "obs.sqlite"
    with connect(db) as conn:
        migrate(conn)
        rid = append_snapshot(conn, _empty_snapshot(), json_path=str(tmp_path / "s.json"))
        (count,) = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()
    assert rid > 0
    assert count == 1


def test_append_snapshot_with_agents_and_themes_persists_aggregates(tmp_path: Path):
    captured_at = datetime(2026, 5, 27, 14, 30, 0, tzinfo=timezone.utc)

    surfaces_ws1 = [
        Surface(
            ref="surface:1",
            pane_ref="pane:1",
            workspace_ref="workspace:1",
            kind="terminal",
            title="claude",
            is_agent=True,
        ),
        Surface(
            ref="surface:2",
            pane_ref="pane:2",
            workspace_ref="workspace:1",
            kind="terminal",
            title="shell",
        ),
    ]
    surfaces_ws2 = [
        Surface(
            ref="surface:3",
            pane_ref="pane:3",
            workspace_ref="workspace:2",
            kind="terminal",
            title="codex",
            is_agent=True,
        ),
    ]
    workspaces = [
        Workspace(ref="workspace:1", title="ws-1", window_ref="window:1", surfaces=surfaces_ws1),
        Workspace(ref="workspace:2", title="ws-2", window_ref="window:2", surfaces=surfaces_ws2),
    ]

    summary_a = Summary(
        text="Working on T8 tests",
        state_hint="running",
        needs_input_reason=None,
        confidence=0.9,
        cache_hit=False,
        cached_at=captured_at,
        prompt_version=1,
        screen_hash="deadbeef",
    )
    agent_a = Agent(
        surface_ref="surface:1",
        workspace_ref="workspace:1",
        type="claude_code",
        type_source="cmux_tag",
        type_confidence=0.95,
        state="running",
        state_source="title_sniff",
        summary=summary_a,
    )
    agent_b = Agent(
        surface_ref="surface:3",
        workspace_ref="workspace:2",
        type="codex",
        type_source="cmux_tag",
        type_confidence=0.95,
        state="needs_input",
        state_source="title_sniff",
        summary=None,
    )

    theme = Theme(
        label="testing",
        member_refs=["surface:1"],
        why="both agents are running tests",
        confidence=0.8,
    )

    snap = Snapshot(
        schema_version=1,
        captured_at=captured_at,
        host="h",
        cmux_version=None,
        workspaces=workspaces,
        agents=[agent_a, agent_b],
        themes=[theme],
        productivity=None,
        history=None,
        failures=[],
    )

    db = tmp_path / "obs.sqlite"
    with connect(db) as conn:
        migrate(conn)
        snapshot_id = append_snapshot(conn, snap, json_path=str(tmp_path / "s.json"))

        row = conn.execute(
            """
            SELECT agents_total, agents_running, agents_needs_input,
                   by_type_json, workspaces_total, surfaces_total, themes_json
            FROM snapshots WHERE id = ?
            """,
            (snapshot_id,),
        ).fetchone()

        obs = conn.execute(
            """
            SELECT surface_ref, type, state, summary_text
            FROM agent_observations WHERE snapshot_id = ?
            ORDER BY surface_ref
            """,
            (snapshot_id,),
        ).fetchall()

    (
        agents_total,
        agents_running,
        agents_needs_input,
        by_type_json,
        workspaces_total,
        surfaces_total,
        themes_json,
    ) = row

    assert agents_total == 2
    assert agents_running == 1
    assert agents_needs_input == 1
    assert json.loads(by_type_json) == {"claude_code": 1, "codex": 1}
    assert workspaces_total == 2
    assert surfaces_total == 3

    themes_decoded = json.loads(themes_json)
    assert isinstance(themes_decoded, list)
    assert len(themes_decoded) >= 1

    assert len(obs) == 2
    by_ref = {r[0]: r for r in obs}

    a_row = by_ref["surface:1"]
    assert a_row[1] == "claude_code"
    assert a_row[2] == "running"
    assert a_row[3] == "Working on T8 tests"

    b_row = by_ref["surface:3"]
    assert b_row[1] == "codex"
    assert b_row[2] == "needs_input"
    assert b_row[3] is None
