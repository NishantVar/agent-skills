from pathlib import Path

from cmux_observability.collector.cmux import parse_tree


def test_parse_tree_basic(fixture_dir: Path):
    text = (fixture_dir / "cmux_tree_basic.txt").read_text()
    workspaces = parse_tree(text)
    assert [w.ref for w in workspaces] == ["workspace:2", "workspace:17"]

    meta = workspaces[0]
    assert meta.title == "Meta Eval"
    assert meta.window_ref == "window:1"
    assert [s.ref for s in meta.surfaces] == ["surface:2", "surface:3"]
    s2 = meta.surfaces[0]
    assert s2.kind == "terminal"
    assert s2.title == "design_coordinator"
    assert s2.tty == "ttys005"
    assert s2.pane_ref == "pane:2"
    assert s2.workspace_ref == "workspace:2"


def test_parse_tree_handles_focused_active_here_annotations(fixture_dir: Path):
    text = (fixture_dir / "cmux_tree_renamed.txt").read_text()
    workspaces = parse_tree(text)
    assert len(workspaces) == 1
    surfaces = workspaces[0].surfaces
    assert [s.ref for s in surfaces] == ["surface:67", "surface:68"]
    # title must be cleanly extracted despite ◀ active ◀ here annotations
    assert surfaces[0].title == "observability_designer"


from cmux_observability.collector.cmux import parse_top, TopResult


def test_parse_top_with_tags(fixture_dir):
    text = (fixture_dir / "cmux_top_with_tags.txt").read_text()
    result: TopResult = parse_top(text)

    assert set(result.tags_by_workspace.keys()) == {"workspace:12", "workspace:15"}
    tags12 = result.tags_by_workspace["workspace:12"]
    assert len(tags12) == 1
    assert tags12[0].kind == "claude_code"
    assert tags12[0].state == "Needs input"
    assert tags12[0].pid == 87611

    tags15 = result.tags_by_workspace["workspace:15"]
    assert tags15[0].kind == "claude_code"
    assert tags15[0].state == "Running"
    assert tags15[0].pid == 90828

    s39 = result.stats_by_surface["surface:39"]
    assert s39.cpu_pct == 1.1
    assert s39.mem_bytes == int(980.1 * 1024 * 1024)


def test_parse_top_no_tags_returns_empty_tag_map(fixture_dir):
    text = (fixture_dir / "cmux_top_no_tags.txt").read_text()
    result = parse_top(text)
    assert result.tags_by_workspace == {}
    assert "surface:39" in result.stats_by_surface
