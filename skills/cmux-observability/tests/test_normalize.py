"""Tests for the Snapshot normalize step.

v1.1: normalize() only creates agents from cmux tags. Untagged surfaces
remain regular Surface entries in their Workspace; agent inference for
untagged surfaces now belongs to the CLI scrollback-heuristic path.
"""

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


def test_normalize_does_not_promote_untagged_surfaces(fixture_dir: Path):
    """No cmux tags = no agents. Untagged surfaces stay in workspace
    drill-down regardless of title; they are never promoted by normalize."""
    tree = parse_tree((fixture_dir / "cmux_tree_basic.txt").read_text())
    top = parse_top((fixture_dir / "cmux_top_no_tags.txt").read_text())

    snap = normalize(
        workspaces=tree, top=top, host="h", cmux_version=None,
        now=datetime.now(timezone.utc),
    )
    assert snap.agents == []
    # Untagged surfaces still appear in workspace drill-down.
    assert any(
        s.title == "design_coordinator"
        for w in snap.workspaces for s in w.surfaces
    )


def test_normalize_does_not_promote_untagged_title_match():
    """A surface whose title looks like a known agent kind (e.g. ``claude_code
    helper``) is NOT promoted by normalize when no cmux tag covers it. The
    surface remains in the workspace's surfaces list with is_agent=False."""
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
    assert snap.agents == []
    [surf_out] = snap.workspaces[0].surfaces
    assert surf_out.ref == "surface:99"
    assert surf_out.is_agent is False


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


def test_normalize_tag_owns_title_looking_surface_without_double_count():
    """When a workspace has a cmux tag AND a single surface whose title would
    once have been title-sniffed, the tag path consumes that surface exactly
    once — confidence 1.0, type_source=cmux_tag, no duplicate from any
    legacy fallback."""
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
    assert len(snap.agents) == 1
    a = snap.agents[0]
    assert a.surface_ref == "surface:77"
    assert a.type == "claude_code"
    assert a.type_source == "cmux_tag"
    assert a.type_confidence == 1.0
    assert a.state == "running"
    assert a.pid == 12345
