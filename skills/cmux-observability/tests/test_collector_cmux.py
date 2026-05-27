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
