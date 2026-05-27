"""CLI dispatch tests: --help smoke, --config after subcommand, themes-payload."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cmux_observability import cli, runstate
from cmux_observability.model import Snapshot


MIN_CONFIG = """
[summarizer]
enabled = true
themes_enabled = true
"""


def _write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(MIN_CONFIG)
    return cfg


def _empty_snapshot() -> Snapshot:
    return Snapshot(
        schema_version=1,
        captured_at=datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc),
        host="localhost",
        cmux_version=None,
        workspaces=[],
        agents=[],
    )


def test_help_smoke_via_main(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "collect" in out
    assert "record-summaries" in out
    assert "themes-payload" in out
    assert "record-themes" in out
    assert "finalize" in out


def test_config_post_subcommand_position_parses(tmp_path: Path) -> None:
    """`collect --config <path>` (option after subcommand) must parse cleanly.

    Argparse only accepts options on the subcommand parser if they are
    registered on the subparser itself.
    """
    cfg = _write_config(tmp_path)
    parser = cli.build_parser()
    args = parser.parse_args(["collect", "--config", str(cfg)])
    assert args.cmd == "collect"
    assert args.config == str(cfg)


def test_themes_payload_uses_existing_runstate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """themes-payload reads runstate and emits a JSON envelope.

    Guards against the `load_config`/`_load_config` name mismatch in the
    plan snippet — a wrong name would surface here as NameError.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    cfg = _write_config(tmp_path)
    snap = _empty_snapshot()
    run_id = runstate.new_run_id()
    runstate.write(run_id, snap, screen_hashes={}, redactions_by_surface={})

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main([
            "themes-payload", "--run-id", run_id, "--config", str(cfg),
        ])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["ok"] is True
    # themes_payload envelope has either `payload` or `omit`+`reason`.
    assert "payload" in out or "omit" in out


def test_collect_passes_workspace_ref_to_read_screen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live-smoke regression: `collect` must pass each agent's
    workspace_ref to `read_screen` so cmux 0.64.10 can resolve the
    surface (otherwise `Surface is not a terminal`). Produces
    non-empty `pending_summaries` and zero read_screen failures."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    # Build a fixture-driven snapshot via the real parse path.
    fixture_dir = Path(__file__).parent / "fixtures"
    from cmux_observability.collector.cmux import parse_top, parse_tree

    tree = parse_tree((fixture_dir / "cmux_tree_with_tagged_ws.txt").read_text())
    top = parse_top((fixture_dir / "cmux_top_with_tags.txt").read_text())

    monkeypatch.setattr(
        "cmux_observability.cli.fetch_tree", lambda: tree
    )
    monkeypatch.setattr(
        "cmux_observability.cli.fetch_top", lambda: top
    )
    monkeypatch.setattr(
        "cmux_observability.cli.cmux_version", lambda: "0.64.10"
    )
    # discover_repos may try real filesystem; force empty.
    monkeypatch.setattr(
        "cmux_observability.cli.discover_repos",
        lambda cfg, force_rescan=False: ([], []),
    )
    monkeypatch.setattr(
        "cmux_observability.cli.productivity",
        lambda repos, cfg: None,
    )

    calls: list[dict] = []

    def fake_read_screen(surface_ref, *, workspace_ref=None, lines=150):
        calls.append({
            "surface_ref": surface_ref,
            "workspace_ref": workspace_ref,
            "lines": lines,
        })
        return f"agent screen content for {surface_ref}\n" * 5

    monkeypatch.setattr(
        "cmux_observability.cli.read_screen", fake_read_screen
    )

    cfg = _write_config(tmp_path)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["collect", "--config", str(cfg)])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["ok"] is True

    # All read_screen calls received a workspace_ref kwarg.
    assert calls, "read_screen was never called"
    for c in calls:
        assert c["workspace_ref"] is not None, c
        assert c["workspace_ref"].startswith("workspace:"), c

    # Tagged-ws fixture has 2 running/needs_input agents -> non-empty pending.
    assert out["pending_summaries"], (
        f"expected non-empty pending_summaries, got {out['pending_summaries']}"
    )

    # No read_screen failures appear.
    failures = out["snapshot_preview"]["failures"]
    rs_failures = [f for f in failures if f["component"] == "read_screen"]
    assert not rs_failures, f"unexpected read_screen failures: {rs_failures}"


def test_collect_heuristic_classifies_untagged_surface_and_flows_into_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wired heuristic classifier:
    - tagged claude surface keeps type_source=cmux_tag, conf=1.0
    - untagged surface whose scrollback hits claude markers becomes a heuristic
      agent (type_source=heuristic, conf>=0.7) and flows into pending_summaries
    - untagged surface with plain-shell tail produces NO agent and is NOT in
      pending_summaries
    """
    from cmux_observability.collector.cmux import TagLine, TopResult
    from cmux_observability.model import Surface, Workspace

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    # Workspace A: tagged claude surface.
    ws_tagged = Workspace(
        ref="workspace:1", title="Tagged WS", window_ref="window:1",
        surfaces=[Surface(
            ref="surface:1", pane_ref="pane:1", workspace_ref="workspace:1",
            kind="terminal", title="claude_code worker", tty="ttys001",
        )],
    )
    # Workspace B: untagged surface whose scrollback hits claude markers.
    ws_heuristic = Workspace(
        ref="workspace:2", title="Heuristic WS", window_ref="window:1",
        surfaces=[Surface(
            ref="surface:2", pane_ref="pane:2", workspace_ref="workspace:2",
            kind="terminal", title="some-tab", tty="ttys002",
        )],
    )
    # Workspace C: untagged plain-shell surface — must NOT become an agent.
    ws_plain = Workspace(
        ref="workspace:3", title="Plain WS", window_ref="window:1",
        surfaces=[Surface(
            ref="surface:3", pane_ref="pane:3", workspace_ref="workspace:3",
            kind="terminal", title="shell", tty="ttys003",
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
        lambda: [ws_tagged, ws_heuristic, ws_plain],
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

    # Two distinct claude markers — confidence >= 0.7.
    claude_tail = (
        "❯ run the tests\n"
        "╭─ ctx:42%\n"
        "⏵⏵ bypass permissions\n"
    )
    plain_tail = (
        "nishant@host project % ls\n"
        "README.md  src/\n"
        "nishant@host project % \n"
    )

    def fake_read_screen(surface_ref, *, workspace_ref=None, lines=150):
        if surface_ref == "surface:1":
            return "tagged agent screen\n" + claude_tail
        if surface_ref == "surface:2":
            return claude_tail
        if surface_ref == "surface:3":
            return plain_tail
        return ""

    monkeypatch.setattr("cmux_observability.cli.read_screen", fake_read_screen)

    cfg = _write_config(tmp_path)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["collect", "--config", str(cfg)])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["ok"] is True

    # Two agents total: one tagged, one heuristic. Plain shell stays out.
    assert out["snapshot_preview"]["agents_total"] == 2

    # Reload snapshot from runstate to inspect Agent fields.
    snap, _h, _r = runstate.read(out["run_id"])
    by_ref = {a.surface_ref: a for a in snap.agents}
    assert set(by_ref) == {"surface:1", "surface:2"}

    tagged = by_ref["surface:1"]
    assert tagged.type == "claude_code"
    assert tagged.type_source == "cmux_tag"
    assert tagged.type_confidence == 1.0

    heuristic = by_ref["surface:2"]
    assert heuristic.type == "claude_code"
    assert heuristic.type_source == "heuristic"
    assert heuristic.type_confidence >= 0.7

    # Both classified surfaces are in pending_summaries; plain shell is NOT.
    pending_refs = {p["surface_ref"] for p in out["pending_summaries"]}
    assert pending_refs == {"surface:1", "surface:2"}, (
        f"expected both classified surfaces in pending, got {pending_refs}"
    )
