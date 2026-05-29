"""End-to-end classifier integration: tagged + heuristic (2 kinds) + plain shell
flowing through a single `collect` run.

Regression-guard test: T1-T4 already implement this pipeline. This test pins
the aligned-fixture happy path across multiple kinds (claude_code + codex)
and multiple surfaces in one envelope.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from cmux_observability import cli, runstate

from .test_cli import _write_config


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "scrollback"


def test_collect_end_to_end_tagged_plus_heuristic_kinds_plus_plain_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cmux_observability.collector.cmux import TagLine, TopResult
    from cmux_observability.model import Surface, Workspace

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    # A: tagged claude_code surface.
    ws_a = Workspace(
        ref="workspace:1", title="Tagged WS", window_ref="window:1",
        surfaces=[Surface(
            ref="surface:A", pane_ref="pane:1", workspace_ref="workspace:1",
            kind="terminal", title="claude_code worker", tty="ttys001",
        )],
    )
    # B: untagged, scrollback matches claude_code via heuristic.
    ws_b = Workspace(
        ref="workspace:2", title="Heuristic Claude WS", window_ref="window:1",
        surfaces=[Surface(
            ref="surface:B", pane_ref="pane:2", workspace_ref="workspace:2",
            kind="terminal", title="some-tab", tty="ttys002",
        )],
    )
    # C: untagged, scrollback matches codex via heuristic.
    ws_c = Workspace(
        ref="workspace:3", title="Heuristic Codex WS", window_ref="window:1",
        surfaces=[Surface(
            ref="surface:C", pane_ref="pane:3", workspace_ref="workspace:3",
            kind="terminal", title="another-tab", tty="ttys003",
        )],
    )
    # D: untagged plain shell — must NOT be classified.
    ws_d = Workspace(
        ref="workspace:4", title="Plain WS", window_ref="window:1",
        surfaces=[Surface(
            ref="surface:D", pane_ref="pane:4", workspace_ref="workspace:4",
            kind="terminal", title="shell", tty="ttys004",
        )],
    )

    top = TopResult(
        tags_by_workspace={
            "workspace:1": [TagLine(kind="claude_code", state="Running", pid=4242)],
        },
        stats_by_surface={},
    )

    monkeypatch.setattr(
        "cmux_observability.cli.fetch_tree",
        lambda: [ws_a, ws_b, ws_c, ws_d],
    )
    monkeypatch.setattr("cmux_observability.cli.fetch_top", lambda: top)
    monkeypatch.setattr("cmux_observability.cli.cmux_version", lambda: "0.64.10")
    monkeypatch.setattr(
        "cmux_observability.cli.discover_repos",
        lambda cfg, force_rescan=False: ([], []),
    )
    monkeypatch.setattr(
        "cmux_observability.cli.productivity", lambda repos, cfg: None,
    )

    claude_scrollback = (FIXTURE_DIR / "claude_code.txt").read_text()
    codex_scrollback = (FIXTURE_DIR / "codex.txt").read_text()
    plain_scrollback = (FIXTURE_DIR / "plain_shell.txt").read_text()

    def fake_read_screen(surface_ref, *, workspace_ref=None, lines=150):
        if surface_ref == "surface:A":
            return "tagged agent screen\n" + claude_scrollback
        if surface_ref == "surface:B":
            return claude_scrollback
        if surface_ref == "surface:C":
            return codex_scrollback
        if surface_ref == "surface:D":
            return plain_scrollback
        return ""

    monkeypatch.setattr("cmux_observability.cli.read_screen", fake_read_screen)

    cfg = _write_config(tmp_path)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["collect", "--config", str(cfg)])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["ok"] is True

    sp = out["snapshot_preview"]
    assert sp["agents_total"] == 3
    assert sp["agents_tagged"] == 1
    assert sp["agents_heuristic"] == 2

    pending_refs = {p["surface_ref"] for p in out["pending_summaries"]}
    assert pending_refs == {"surface:A", "surface:B", "surface:C"}
    assert "surface:D" not in pending_refs

    snap, _h, _r = runstate.read(out["run_id"])

    # D's surface must still appear in snap.workspaces (T2-followup invariant).
    workspace_surface_refs = {
        s.ref for ws in snap.workspaces for s in ws.surfaces
    }
    assert "surface:D" in workspace_surface_refs

    by_ref = {a.surface_ref: a for a in snap.agents}
    assert set(by_ref) == {"surface:A", "surface:B", "surface:C"}

    a = by_ref["surface:A"]
    assert a.type == "claude_code"
    assert a.type_source == "cmux_tag"
    assert a.type_confidence == 1.0

    b = by_ref["surface:B"]
    assert b.type == "claude_code"
    assert b.type_source == "heuristic"
    assert b.type_confidence >= 0.7

    c = by_ref["surface:C"]
    assert c.type == "codex"
    assert c.type_source == "heuristic"
    assert c.type_confidence >= 0.7
