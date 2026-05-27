from datetime import datetime, timezone
from pathlib import Path

from cmux_observability.errors import Failure
from cmux_observability.model import (
    Agent,
    Productivity,
    RepoStats,
    Snapshot,
    Summary,
    Surface,
    Theme,
    Workspace,
)
from cmux_observability.render.render import render_snapshot


def _snap_empty() -> Snapshot:
    return Snapshot(
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


def _snap_populated(
    *,
    summary_text: str = "writing pytest fixtures",
    theme_label: str = "testing",
    ws_title: str = "Project A",
) -> Snapshot:
    surface = Surface(
        ref="surface:1",
        pane_ref="pane:1",
        workspace_ref="workspace:1",
        kind="terminal",
        title="claude_code worker",
        tty="ttys001",
        cwd="/home/u/p",
        cpu_pct=12.3,
        mem_bytes=104857600,
        is_agent=True,
    )
    workspace = Workspace(
        ref="workspace:1",
        title=ws_title,
        window_ref="window:1",
        surfaces=[surface],
    )
    summary = Summary(
        text=summary_text,
        state_hint="running",
        needs_input_reason=None,
        confidence=0.9,
        cache_hit=False,
        cached_at=datetime(2026, 5, 27, 14, 29, 0, tzinfo=timezone.utc),
        prompt_version=1,
        screen_hash="dead",
        redactions_applied=["SK_TOKEN:1"],
        redaction_summary="SK_TOKEN:1",
    )
    agent = Agent(
        surface_ref="surface:1",
        workspace_ref="workspace:1",
        type="claude_code",
        type_source="cmux_tag",
        type_confidence=1.0,
        state="running",
        state_source="cmux_tag",
        pid=42,
        summary=summary,
    )
    theme = Theme(
        label=theme_label,
        member_refs=["surface:1"],
        why="agent is writing fixtures",
        confidence=0.85,
    )
    failure = Failure(component="collector", target="cmux", message="tree timeout")
    productivity = Productivity(
        repos=[
            RepoStats(
                path="/home/u/p",
                name="p",
                commits={"today": 3, "week": 7, "30d": 21},
                last_commit_at=datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc),
            )
        ],
        totals={"today": 3, "week": 7, "30d": 21},
    )
    return Snapshot(
        schema_version=1,
        captured_at=datetime(2026, 5, 27, 14, 30, 0, tzinfo=timezone.utc),
        host="laptop",
        cmux_version="1.2.3",
        workspaces=[workspace],
        agents=[agent],
        themes=[theme],
        productivity=productivity,
        history=None,
        failures=[failure],
    )


def test_render_empty_snapshot_is_self_contained_and_modern_doc(tmp_path: Path):
    snap = _snap_empty()
    html_path, json_path = render_snapshot(snap, tmp_path)
    assert html_path.exists() and html_path.suffix == ".html"
    assert json_path.exists() and json_path.suffix == ".json"
    html = html_path.read_text()

    # Document skeleton (instruction #2)
    assert "<!doctype html>" in html.lower()
    assert '<html lang="en"' in html
    assert '<meta name="viewport"' in html
    assert '<meta name="color-scheme" content="light dark">' in html

    # CSS modernization (instruction #2)
    assert "color-scheme: light dark" in html
    assert "@media (prefers-color-scheme: dark)" in html
    assert "@media print" in html

    # Self-contained: reject external resources (instruction #6)
    for needle in (
        "http://",
        "https://",
        "//cdn.",
        '<link rel="stylesheet"',
        '<script src=',
    ):
        assert needle not in html, f"unexpected external resource: {needle!r}"

    # Graceful empty state
    assert "cmux observability" in html.lower()
    assert "No agents detected" in html


def test_render_populated_snapshot_exercises_all_partials(tmp_path: Path):
    snap = _snap_populated()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # _workspace + _agent_row
    assert "workspace:1" in html
    assert "Project A" in html
    assert "surface:1" in html
    assert "claude_code worker" in html
    assert "running" in html
    assert "12.3" in html              # cpu_pct
    assert "100.0 MB" in html          # 104857600 / 1024 / 1024
    assert "writing pytest fixtures" in html
    # _themes
    assert "testing" in html
    assert "agent is writing fixtures" in html
    # _productivity
    assert "Productivity" in html
    assert ">3<" in html or ">3 " in html or ">3\n" in html  # today count rendered
    assert ">7<" in html or ">7 " in html or ">7\n" in html
    # _failures
    assert "tree timeout" in html
    assert "collector" in html
    # inline style attributes are gone (instruction #1)
    assert "<h3 style=" not in html       # no inline styles on headings
    assert "onclick=" not in html         # no inline event handlers
    assert "card-title" in html           # the replacement class is wired in


def test_render_escapes_user_provided_strings(tmp_path: Path):
    snap = _snap_populated(
        summary_text="<script>alert(1)</script>",
        theme_label="<script>alert(1)</script>",
        ws_title="<script>alert(1)</script>",
    )
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Raw <script> from user content must NOT appear
    assert "<script>alert(1)</script>" not in html
    # Escaped form MUST appear (Jinja autoescape produces &lt;script&gt;…)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
