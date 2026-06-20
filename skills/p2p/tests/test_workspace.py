"""workspace_of and surface_index cross-workspace mapping."""

from __future__ import annotations

from p2plib import surface
from fake_cmux import FakeCmux


def test_workspace_of_maps_across_workspaces():
    fc = FakeCmux()
    fc.add(workspace_ref="workspace:A", workspace_title="Alpha",
           surface_ref="surface:1", tty="ttys001", title="alpha-1")
    fc.add(workspace_ref="workspace:B", workspace_title="Beta",
           surface_ref="surface:2", tty="ttys002", title="beta-1")
    fc.add(workspace_ref="workspace:B", workspace_title="Beta",
           surface_ref="surface:3", tty="ttys003", title="beta-2")
    tree = fc.tree()
    assert surface.workspace_of("surface:1", tree) == "workspace:A"
    assert surface.workspace_of("surface:2", tree) == "workspace:B"
    assert surface.workspace_of("surface:3", tree) == "workspace:B"
    assert surface.workspace_of("surface:99", tree) is None


def test_surface_index_carries_workspace_title():
    fc = FakeCmux()
    fc.add(workspace_ref="workspace:42", workspace_title="Fix TFork",
           surface_ref="surface:10", title="lead")
    idx = surface.surface_index(fc.tree())
    assert idx["surface:10"]["workspace_title"] == "Fix TFork"
    assert idx["surface:10"]["title"] == "lead"


# ---------------- resolve_workspace_title locality ----------------

def _ws_tree(specs):
    fc = FakeCmux()
    for i, s in enumerate(specs):
        fc.add(surface_ref=f"surface:{i + 1}", **s)
    return fc.tree()


def test_workspace_title_prefers_own_workspace():
    """Tier 1: the caller's own workspace title matches → use it, even
    when other windows also hold a workspace with that title."""
    tree = _ws_tree([
        {"window_ref": "window:1", "workspace_ref": "ws:1",
         "workspace_title": "HTML"},
        {"window_ref": "window:1", "workspace_ref": "ws:2",
         "workspace_title": "HTML"},
        {"window_ref": "window:2", "workspace_ref": "ws:3",
         "workspace_title": "HTML"},
    ])
    kind, ref = surface.resolve_workspace_title(
        "HTML", tree, caller_workspace_ref="ws:1",
        caller_window_ref="window:1")
    assert kind == "ok"
    assert ref == "ws:1"


def test_workspace_title_caller_window_single():
    """Tier 2: own workspace doesn't match; exactly one match in the
    caller's window resolves there."""
    tree = _ws_tree([
        {"window_ref": "window:1", "workspace_ref": "ws:1",
         "workspace_title": "Self"},
        {"window_ref": "window:1", "workspace_ref": "ws:2",
         "workspace_title": "HTML"},
        {"window_ref": "window:2", "workspace_ref": "ws:3",
         "workspace_title": "HTML"},
    ])
    kind, ref = surface.resolve_workspace_title(
        "HTML", tree, caller_workspace_ref="ws:1",
        caller_window_ref="window:1")
    assert kind == "ok"
    assert ref == "ws:2"


def test_workspace_title_caller_window_ambiguous():
    """Tier 2 with >=2 matches in the caller's window → ambiguous,
    candidates carry the matched workspaces."""
    tree = _ws_tree([
        {"window_ref": "window:1", "workspace_ref": "ws:1",
         "workspace_title": "Self"},
        {"window_ref": "window:1", "workspace_ref": "ws:2",
         "workspace_title": "HTML"},
        {"window_ref": "window:1", "workspace_ref": "ws:3",
         "workspace_title": "HTML"},
    ])
    kind, cands = surface.resolve_workspace_title(
        "HTML", tree, caller_workspace_ref="ws:1",
        caller_window_ref="window:1")
    assert kind == "ambiguous"
    refs = {c["ref"] for c in cands}
    assert refs == {"ws:2", "ws:3"}


def test_workspace_title_other_windows_single():
    """Tier 3: no match in the caller's workspace or window; a single
    match in another window resolves."""
    tree = _ws_tree([
        {"window_ref": "window:1", "workspace_ref": "ws:1",
         "workspace_title": "Self"},
        {"window_ref": "window:2", "workspace_ref": "ws:2",
         "workspace_title": "HTML"},
    ])
    kind, ref = surface.resolve_workspace_title(
        "HTML", tree, caller_workspace_ref="ws:1",
        caller_window_ref="window:1")
    assert kind == "ok"
    assert ref == "ws:2"


def test_workspace_title_other_windows_ambiguous():
    """Tier 3 with >=2 matches across other windows → ambiguous."""
    tree = _ws_tree([
        {"window_ref": "window:1", "workspace_ref": "ws:1",
         "workspace_title": "Self"},
        {"window_ref": "window:2", "workspace_ref": "ws:2",
         "workspace_title": "HTML"},
        {"window_ref": "window:3", "workspace_ref": "ws:3",
         "workspace_title": "HTML"},
    ])
    kind, cands = surface.resolve_workspace_title(
        "HTML", tree, caller_workspace_ref="ws:1",
        caller_window_ref="window:1")
    assert kind == "ambiguous"
    refs = {c["ref"] for c in cands}
    assert refs == {"ws:2", "ws:3"}


def test_workspace_title_unknown_when_absent():
    tree = _ws_tree([
        {"window_ref": "window:1", "workspace_ref": "ws:1",
         "workspace_title": "Self"},
    ])
    kind, val = surface.resolve_workspace_title(
        "HTML", tree, caller_workspace_ref="ws:1",
        caller_window_ref="window:1")
    assert kind == "unknown"
    assert val is None
