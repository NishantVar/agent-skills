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
