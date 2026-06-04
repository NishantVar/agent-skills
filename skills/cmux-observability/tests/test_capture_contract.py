"""Observability side of the shared golden capture-envelope contract +
the zero-cmux boundary.

The golden file is byte-identical to the one watchdog asserts it produces. Here
we assert observability ingests it (validates, rebuilds the Snapshot, surfaces
the redaction metadata) and that the consume path makes ZERO cmux calls.
"""

from __future__ import annotations

import importlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from cmux_observability import cli, runstate
from cmux_observability.ingest import ingest, validate_capture_envelope


GOLDEN = Path(__file__).parent / "fixtures" / "golden_snapshot.json"
CONFIG = "[summarizer]\nenabled = true\nthemes_enabled = true\n"


def _golden() -> dict:
    return json.loads(GOLDEN.read_text())


def test_validate_golden():
    validate_capture_envelope(_golden())


def test_validate_rejects_bumped_major():
    env = _golden()
    env["capture_schema_version"] = 999
    with pytest.raises(ValueError):
        validate_capture_envelope(env)


def test_ingest_golden_rebuilds_snapshot():
    snap, screens, redaction_meta = ingest(_golden())

    assert snap.host == "golden-host"
    assert snap.cmux_version == "cmux 0.64.10"
    # Browser surface preserved for the dashboard.
    kinds = {s.ref: s.kind for w in snap.workspaces for s in w.surfaces}
    assert kinds.get("surface:2") == "browser"

    by_ref = {a.surface_ref: a for a in snap.agents}
    assert by_ref["surface:1"].type == "claude_code"
    assert by_ref["surface:1"].state == "needs_input"
    assert by_ref["surface:1"].state_source == "scrollback"
    assert by_ref["surface:3"].type == "codex"
    assert by_ref["surface:3"].type_source == "heuristic"

    # state_classifier failure rode through the envelope.
    assert any(f.component == "state_classifier" for f in snap.failures)

    # Screens are the already-redacted scrollback; meta carries hash + redactions.
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWX" not in json.dumps(screens)
    assert redaction_meta["surface:1"]["screen_hash"]
    assert "SK_TOKEN:1" in redaction_meta["surface:1"]["redactions_applied"]


def test_validate_rejects_malformed_surface():
    env = _golden()
    # Drop a required field from the first surface.
    del env["workspaces"][0]["surfaces"][0]["pane_ref"]
    with pytest.raises(ValueError):
        validate_capture_envelope(env)


def test_collect_malformed_surface_returns_clean_error(tmp_path, monkeypatch):
    """A surface missing a required field must yield {ok:false,error:...} from
    collect — never an uncaught traceback."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        "cmux_observability.cli.discover_repos",
        lambda cfg, force_rescan=False: ([], []),
    )
    monkeypatch.setattr(
        "cmux_observability.cli.productivity", lambda repos, cfg: None,
    )
    env = _golden()
    del env["workspaces"][0]["surfaces"][0]["pane_ref"]
    env_path = tmp_path / "bad.json"
    env_path.write_text(json.dumps(env))
    cfg = tmp_path / "config.toml"
    cfg.write_text(CONFIG)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["collect", "--input", str(env_path), "--config", str(cfg)])
    out = json.loads(buf.getvalue())
    assert out["ok"] is False
    assert "invalid capture envelope" in out["error"]


def test_no_cmux_collector_module_present():
    """The cmux reader was removed from observability — importing it must fail,
    and the CLI must not expose cmux fetch symbols."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("cmux_observability.collector.cmux")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("cmux_observability.normalize")
    for sym in ("fetch_tree", "fetch_top", "read_screen", "cmux_version"):
        assert not hasattr(cli, sym), f"cli still exposes {sym}"


def test_collect_makes_zero_cmux_calls(tmp_path, monkeypatch):
    """Running `collect` against the golden envelope must never invoke `cmux`."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        "cmux_observability.cli.discover_repos",
        lambda cfg, force_rescan=False: ([], []),
    )
    monkeypatch.setattr(
        "cmux_observability.cli.productivity", lambda repos, cfg: None,
    )

    import subprocess
    calls: list[list[str]] = []
    real_run = subprocess.run

    def spy_run(args, *a, **k):
        argv = args if isinstance(args, (list, tuple)) else [args]
        calls.append(list(argv))
        assert not (argv and str(argv[0]).endswith("cmux")), (
            f"observability invoked cmux: {argv}"
        )
        return real_run(args, *a, **k)

    monkeypatch.setattr(subprocess, "run", spy_run)

    env_path = tmp_path / "golden.json"
    env_path.write_text(GOLDEN.read_text())
    cfg = tmp_path / "config.toml"
    cfg.write_text(CONFIG)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["collect", "--input", str(env_path), "--config", str(cfg)])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["ok"] is True
    # Sanity: ingest rebuilt the two agents from the golden.
    assert out["snapshot_preview"]["agents_total"] == 2
    assert not any(str(c[0]).endswith("cmux") for c in calls if c)

    snap, _h, _r = runstate.read(out["run_id"])
    assert {a.surface_ref for a in snap.agents} == {"surface:1", "surface:3"}
