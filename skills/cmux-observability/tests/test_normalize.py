"""Tests for the Snapshot normalize step."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cmux_observability.collector.cmux import TagLine, TopResult, parse_tree, parse_top
from cmux_observability.model import Surface, Workspace
from cmux_observability.normalize import normalize


def test_normalize_attaches_tag_type_and_state(fixture_dir: Path):
    """Tree workspace refs match top tag workspaces — must produce tag-derived
    agents in BOTH workspace:12 and workspace:15 with type_source=cmux_tag,
    confidence 1.0, and normalized states."""
    tree = parse_tree((fixture_dir / "cmux_tree_with_tagged_ws.txt").read_text())
    top = parse_top((fixture_dir / "cmux_top_with_tags.txt").read_text())

    snap = normalize(
        workspaces=tree, top=top, host="laptop", cmux_version="1.0",
        now=datetime(2026, 5, 27, tzinfo=timezone.utc),
    )

    assert snap.host == "laptop"
    # Both workspaces' tags produce agents — no spurious title-sniff additions.
    assert len(snap.agents) == 2

    ws12 = [a for a in snap.agents if a.workspace_ref == "workspace:12"]
    assert len(ws12) == 1
    a12 = ws12[0]
    assert a12.surface_ref == "surface:39"
    assert a12.type == "claude_code"
    assert a12.type_source == "cmux_tag"
    assert a12.type_confidence == 1.0
    assert a12.state == "needs_input"
    assert a12.state_source == "cmux_tag"
    assert a12.pid == 87611

    ws15 = [a for a in snap.agents if a.workspace_ref == "workspace:15"]
    assert len(ws15) == 1
    a15 = ws15[0]
    assert a15.surface_ref == "surface:61"
    assert a15.type == "claude_code"
    assert a15.type_source == "cmux_tag"
    assert a15.type_confidence == 1.0
    assert a15.state == "running"
    assert a15.state_source == "cmux_tag"
    assert a15.pid == 90828


def test_normalize_sniff_fallback_marks_low_confidence(fixture_dir: Path):
    """Surfaces with no matching tag fall back to title_sniff; non-agent
    titles stay in workspace drill-down but do NOT enter the agents list."""
    tree = parse_tree((fixture_dir / "cmux_tree_basic.txt").read_text())
    top = parse_top((fixture_dir / "cmux_top_no_tags.txt").read_text())

    snap = normalize(
        workspaces=tree, top=top, host="h", cmux_version=None,
        now=datetime.now(timezone.utc),
    )
    # design_coordinator title is not a known agent type -> not in agents
    # ... but should appear in workspace drill-down via the surfaces.
    assert any(
        s.title == "design_coordinator"
        for w in snap.workspaces for s in w.surfaces
    )
    assert not any(a.type == "design_coordinator" for a in snap.agents)


def test_normalize_title_sniff_assigns_low_confidence():
    """A surface whose title matches a known agent hint becomes a title_sniff
    agent at confidence 0.6 when no cmux tag is present in its workspace."""
    surface = Surface(
        ref="surface:99", pane_ref="pane:99", workspace_ref="workspace:99",
        kind="terminal", title="claude_code helper", tty="ttys099",
        cwd="/tmp", is_agent=False,
    )
    ws = Workspace(
        ref="workspace:99", title="W99", window_ref="window:1",
        surfaces=[surface],
    )
    snap = normalize(
        workspaces=[ws], top=TopResult(),
        host="h", cmux_version=None,
        now=datetime(2026, 5, 27, tzinfo=timezone.utc),
    )
    assert len(snap.agents) == 1
    a = snap.agents[0]
    assert a.surface_ref == "surface:99"
    assert a.type == "claude_code"
    assert a.type_source == "title_sniff"
    assert a.type_confidence == 0.6
    assert a.state == "unknown"
    assert a.state_source == "unknown"


def test_normalize_prefers_exact_tag_kind_match_before_generic_agent_title():
    """When a workspace has two unused surfaces and a cmux tag, the tag must
    pair with the surface whose title exactly contains `tag.kind`, NOT with a
    generic `agent`-titled surface that happens to appear earlier in the
    surface list."""
    s_generic = Surface(
        ref="surface:88a", pane_ref="pane:88a", workspace_ref="workspace:88",
        kind="terminal", title="agent notes", tty="ttys088a",
        cwd="/tmp", is_agent=False,
    )
    s_exact = Surface(
        ref="surface:88b", pane_ref="pane:88b", workspace_ref="workspace:88",
        kind="terminal", title="claude_code worker", tty="ttys088b",
        cwd="/tmp", is_agent=False,
    )
    ws = Workspace(
        ref="workspace:88", title="W88", window_ref="window:1",
        surfaces=[s_generic, s_exact],
    )
    top = TopResult(
        tags_by_workspace={
            "workspace:88": [TagLine(kind="claude_code", state="Running", pid=99999)],
        },
        stats_by_surface={},
    )
    snap = normalize(
        workspaces=[ws], top=top,
        host="h", cmux_version=None,
        now=datetime(2026, 5, 27, tzinfo=timezone.utc),
    )
    assert len(snap.agents) == 1
    a = snap.agents[0]
    assert a.surface_ref == "surface:88b"   # exact match wins, NOT 88a
    assert a.type_source == "cmux_tag"
    assert a.type_confidence == 1.0
    assert a.state == "running"
    assert a.pid == 99999


def test_normalize_tag_precedence_over_title_sniff():
    """When a workspace has BOTH a cmux tag AND a surface whose title would
    title-sniff to the same agent type, the surface is attached via the tag
    (type_source=cmux_tag, confidence 1.0) and is NOT double-counted via
    title_sniff."""
    surface = Surface(
        ref="surface:77", pane_ref="pane:77", workspace_ref="workspace:77",
        kind="terminal", title="claude_code worker", tty="ttys077",
        cwd="/tmp", is_agent=False,
    )
    ws = Workspace(
        ref="workspace:77", title="W77", window_ref="window:1",
        surfaces=[surface],
    )
    top = TopResult(
        tags_by_workspace={
            "workspace:77": [TagLine(kind="claude_code", state="Running", pid=12345)],
        },
        stats_by_surface={},
    )
    snap = normalize(
        workspaces=[ws], top=top,
        host="h", cmux_version=None,
        now=datetime(2026, 5, 27, tzinfo=timezone.utc),
    )
    # Exactly one agent — the tag path consumes surface:77 first, and the
    # title_sniff pass skips it because surface:77 is already in tagged_refs.
    assert len(snap.agents) == 1
    a = snap.agents[0]
    assert a.surface_ref == "surface:77"
    assert a.type == "claude_code"
    assert a.type_source == "cmux_tag"      # NOT title_sniff
    assert a.type_confidence == 1.0          # NOT 0.6
    assert a.state == "running"
    assert a.pid == 12345
