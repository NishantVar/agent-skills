"""CLI dispatch + collect-ingest tests.

collect no longer reads cmux: it ingests a watchdog capture envelope (deterministic
mapper, zero cmux calls). These tests feed envelopes via `--input` and assert the
observability-side responsibilities: the snapshot_preview breakdown, pending
summaries (using the envelope's redaction metadata), failure pass-through, schema
validation, and workspace-surface preservation.
"""

from __future__ import annotations

import hashlib
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


# --- envelope construction helpers ----------------------------------------

def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _surface(ref, ws_ref, *, kind="terminal", title="tab", is_agent=False):
    return {
        "ref": ref, "pane_ref": f"pane:{ref.split(':')[-1]}",
        "workspace_ref": ws_ref, "kind": kind, "title": title,
        "tty": None, "cwd": None, "cpu_pct": None, "mem_bytes": None,
        "is_agent": is_agent,
    }


def _agent(ref, ws_ref, *, type="claude_code", type_source="cmux_tag",
           type_confidence=1.0, state="running", state_source="cmux_tag",
           pid=None):
    return {
        "surface_ref": ref, "workspace_ref": ws_ref, "type": type,
        "type_source": type_source, "type_confidence": type_confidence,
        "state": state, "state_source": state_source, "pid": pid,
    }


def _capture(ref, text, *, redactions=None):
    return {
        "surface_ref": ref, "redacted_scrollback": text,
        "screen_hash": _hash(text), "redactions_applied": redactions or [],
    }


def _envelope(*, workspaces, agents, captures, failures=None,
              version=1, cmux_version="0.64.10"):
    return {
        "capture_schema_version": version,
        "captured_at": "2026-05-27T12:00:00+00:00",
        "host": "laptop",
        "cmux_version": cmux_version,
        "scope": "all",
        "workspaces": workspaces,
        "agents": agents,
        "captures": captures,
        "failures": failures or [],
    }


def _run_collect(env: dict, tmp_path: Path, monkeypatch, *,
                 home: Path | None = None) -> dict:
    home = home or (tmp_path / "home")
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    # No real repo discovery in these tests.
    monkeypatch.setattr(
        "cmux_observability.cli.discover_repos",
        lambda cfg, force_rescan=False: ([], []),
    )
    monkeypatch.setattr(
        "cmux_observability.cli.productivity", lambda repos, cfg: None,
    )
    env_path = tmp_path / "envelope.json"
    env_path.write_text(json.dumps(env))
    cfg = _write_config(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["collect", "--input", str(env_path), "--config", str(cfg)])
    assert rc == 0
    return json.loads(buf.getvalue())


# --- dispatch tests --------------------------------------------------------

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
    cfg = _write_config(tmp_path)
    parser = cli.build_parser()
    args = parser.parse_args(["collect", "--config", str(cfg)])
    assert args.cmd == "collect"
    assert args.config == str(cfg)


def test_themes_payload_uses_existing_runstate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    assert "payload" in out or "omit" in out


# --- collect ingest --------------------------------------------------------

def test_collect_ingests_envelope_breakdown_and_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mixed envelope (1 tagged + 1 heuristic + 1 plain) rebuilds 2 agents,
    flows both classified surfaces into pending, and keeps the plain surface in
    the workspace tree."""
    workspaces = [
        {"ref": "workspace:1", "title": "WS1", "window_ref": "window:1",
         "surfaces": [_surface("surface:t1", "workspace:1", title="claude_code", is_agent=True)]},
        {"ref": "workspace:2", "title": "WS2", "window_ref": "window:1",
         "surfaces": [_surface("surface:h1", "workspace:2", is_agent=True)]},
        {"ref": "workspace:3", "title": "WS3", "window_ref": "window:1",
         "surfaces": [_surface("surface:p1", "workspace:3", title="shell")]},
    ]
    agents = [
        _agent("surface:t1", "workspace:1", state="running", state_source="cmux_tag", pid=42),
        _agent("surface:h1", "workspace:2", type="codex", type_source="heuristic",
               type_confidence=0.8, state="unknown", state_source="heuristic"),
    ]
    captures = [
        _capture("surface:t1", "tagged agent screen\nworking…\n"),
        _capture("surface:h1", "codex screen\n› working\n"),
    ]
    env = _envelope(workspaces=workspaces, agents=agents, captures=captures)
    out = _run_collect(env, tmp_path, monkeypatch)

    assert out["ok"] is True
    sp = out["snapshot_preview"]
    assert sp["agents_total"] == 2
    assert sp["agents_tagged"] == 1
    assert sp["agents_heuristic"] == 1

    pending_refs = {p["surface_ref"] for p in out["pending_summaries"]}
    assert pending_refs == {"surface:t1", "surface:h1"}

    snap, _h, _r = runstate.read(out["run_id"])
    ws_surface_refs = {s.ref for w in snap.workspaces for s in w.surfaces}
    assert "surface:p1" in ws_surface_refs          # plain surface preserved
    assert {a.surface_ref for a in snap.agents} == {"surface:t1", "surface:h1"}


def test_collect_passes_through_state_classifier_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A state_classifier failure produced by watchdog rides through in the
    envelope and lands in snapshot_preview.failures unchanged."""
    workspaces = [
        {"ref": "workspace:1", "title": "WS", "window_ref": "window:1",
         "surfaces": [_surface("surface:1", "workspace:1", is_agent=True)]},
    ]
    agents = [_agent("surface:1", "workspace:1", state="needs_input",
                     state_source="scrollback", pid=1)]
    captures = [_capture("surface:1", "Do you want to proceed?\n")]
    failures = [{
        "component": "state_classifier", "target": "surface:1",
        "message": "scrollback overrode cmux_tag='running' → needs_input",
        "fatal": False,
    }]
    env = _envelope(workspaces=workspaces, agents=agents, captures=captures,
                    failures=failures)
    out = _run_collect(env, tmp_path, monkeypatch)

    sc = [f for f in out["snapshot_preview"]["failures"]
          if f["component"] == "state_classifier"]
    assert len(sc) == 1
    assert sc[0]["target"] == "surface:1"
    assert out["pending_summaries"][0]["cmux_state"] == "needs_input"


def test_collect_redaction_metadata_flows_from_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The envelope's screen_hash + redactions_applied are authoritative —
    observability ships them verbatim into pending (never re-redacts/re-hashes)."""
    redacted = "output\ntoken <REDACTED:SK_TOKEN>\n"
    workspaces = [
        {"ref": "workspace:1", "title": "WS", "window_ref": "window:1",
         "surfaces": [_surface("surface:1", "workspace:1", is_agent=True)]},
    ]
    agents = [_agent("surface:1", "workspace:1", state="running")]
    captures = [_capture("surface:1", redacted, redactions=["SK_TOKEN:1"])]
    env = _envelope(workspaces=workspaces, agents=agents, captures=captures)
    out = _run_collect(env, tmp_path, monkeypatch)

    [p] = out["pending_summaries"]
    assert p["screen_hash"] == _hash(redacted)        # envelope hash, verbatim
    assert p["redactions_applied"] == ["SK_TOKEN:1"]
    assert p["scrollback"] == redacted                # shipped as-is, not re-truncated


def test_collect_rejects_unsupported_capture_major(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    env = _envelope(workspaces=[], agents=[], captures=[], version=999)
    env_path = tmp_path / "envelope.json"
    env_path.write_text(json.dumps(env))
    cfg = _write_config(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["collect", "--input", str(env_path), "--config", str(cfg)])
    out = json.loads(buf.getvalue())
    assert out["ok"] is False
    assert "capture_schema_version" in out["error"] or "unsupported" in out["error"]


def test_collect_empty_stdin_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    cfg = _write_config(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["collect", "--config", str(cfg)])
    out = json.loads(buf.getvalue())
    assert out["ok"] is False
