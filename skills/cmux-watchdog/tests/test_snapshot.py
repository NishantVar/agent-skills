"""Tests for the `snapshot` subcommand + its read-only / daemon-independent
boundary (touches no journal/digest/cursor/index state, needs no producer)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import capture as cap  # noqa: E402
import watchdog as w  # noqa: E402


FIXTURES = Path(__file__).parent / "fixtures"
SCROLLBACK = FIXTURES / "scrollback"


def _fake_cmux(tree_file: str, top_file: str, screen_text: str):
    tree = (FIXTURES / tree_file).read_text()
    top = (FIXTURES / top_file).read_text()

    def fake_run(*args):
        if args[0] == "tree":
            return tree
        if args[0] == "top":
            return top
        if args[0] == "version":
            return "cmux 0.64.10\n"
        if args[0] == "read-screen":
            return screen_text
        return ""

    return fake_run


def test_snapshot_emits_versioned_envelope(monkeypatch, capsys):
    screen = (SCROLLBACK / "claude_code.txt").read_text()
    monkeypatch.setattr(
        w, "_run_cmux",
        _fake_cmux("cmux_tree_with_tagged_ws.txt", "cmux_top_with_tags.txt", screen),
    )
    rc = w.main(["snapshot", "--workspace", "all"])
    assert rc == 0
    env = json.loads(capsys.readouterr().out)

    assert env["capture_schema_version"] == cap.CAPTURE_SCHEMA_VERSION
    assert env["scope"] == "all"
    assert env["host"]
    assert env["cmux_version"] == "cmux 0.64.10"
    cap.validate_envelope(env)  # must not raise

    # Two tagged claude_code agents (running + needs_input) → both read+captured.
    agent_refs = {a["surface_ref"] for a in env["agents"]}
    assert agent_refs == {"surface:39", "surface:61"}
    capture_refs = {c["surface_ref"] for c in env["captures"]}
    assert capture_refs == agent_refs
    # Browser/non-agent rebuild data is present: workspaces carry their surfaces.
    ws_refs = {w_["ref"] for w_ in env["workspaces"]}
    assert ws_refs == {"workspace:12", "workspace:15"}


def test_snapshot_workspace_filter(monkeypatch, capsys):
    screen = (SCROLLBACK / "claude_code.txt").read_text()
    monkeypatch.setattr(
        w, "_run_cmux",
        _fake_cmux("cmux_tree_with_tagged_ws.txt", "cmux_top_with_tags.txt", screen),
    )
    rc = w.main(["snapshot", "--workspace", "workspace:12"])
    assert rc == 0
    env = json.loads(capsys.readouterr().out)
    assert env["scope"] == "workspace:12"
    assert {w_["ref"] for w_ in env["workspaces"]} == {"workspace:12"}
    assert {a["surface_ref"] for a in env["agents"]} == {"surface:39"}


def test_snapshot_default_scope_is_all(monkeypatch, capsys):
    screen = (SCROLLBACK / "claude_code.txt").read_text()
    monkeypatch.setattr(
        w, "_run_cmux",
        _fake_cmux("cmux_tree_with_tagged_ws.txt", "cmux_top_with_tags.txt", screen),
    )
    rc = w.main(["snapshot"])
    assert rc == 0
    env = json.loads(capsys.readouterr().out)
    assert env["scope"] == "all"
    assert {w_["ref"] for w_ in env["workspaces"]} == {"workspace:12", "workspace:15"}


def test_snapshot_redacts_scrollback(monkeypatch, capsys):
    secret = "sk-ABCDEFGHIJKLMNOPQRSTUVWX"
    screen = f"working on it\ntoken {secret}\n"
    monkeypatch.setattr(
        w, "_run_cmux",
        _fake_cmux("cmux_tree_with_tagged_ws.txt", "cmux_top_with_tags.txt", screen),
    )
    rc = w.main(["snapshot"])
    assert rc == 0
    env = json.loads(capsys.readouterr().out)
    blob = json.dumps(env)
    assert secret not in blob
    assert any("SK_TOKEN:1" in c["redactions_applied"] for c in env["captures"])


def test_snapshot_is_read_only_touches_no_journal_state(monkeypatch, capsys, tmp_path):
    """Boundary: snapshot must NOT call any journal/digest/cursor/index mutator
    and must write no state under CMUX_WATCHDOG_HOME."""
    state_home = tmp_path / "wd-home"
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(state_home))

    def forbidden(name):
        def _f(*a, **k):
            raise AssertionError(f"snapshot must not call {name}")
        return _f

    for fn in ("journal_surface", "update_journal_index", "_save_cursors",
               "_save_resolution"):
        monkeypatch.setattr(w, fn, forbidden(fn))

    screen = (SCROLLBACK / "claude_code.txt").read_text()
    monkeypatch.setattr(
        w, "_run_cmux",
        _fake_cmux("cmux_tree_with_tagged_ws.txt", "cmux_top_with_tags.txt", screen),
    )
    rc = w.main(["snapshot"])
    assert rc == 0
    capsys.readouterr()
    # No state directory created at all.
    assert not state_home.exists(), (
        f"snapshot wrote state under {state_home}: "
        f"{list(state_home.rglob('*')) if state_home.exists() else []}"
    )


def test_snapshot_degrades_on_tree_failure(monkeypatch, capsys):
    def boom(*args):
        raise w.CmuxError("cmux down")

    monkeypatch.setattr(w, "_run_cmux", boom)
    rc = w.main(["snapshot"])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert "cmux down" in out["error"]
