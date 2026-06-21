"""--workspace value handling on `send`: title vs ref vs `all`, plus
the workspace_unknown / workspace_ambiguous handoffs and the
peer_not_found handoff (p2p never spawns)."""

from __future__ import annotations

import json
import time

import pytest

from p2plib import cli, registry
from fake_cmux import FakeCmux


MY_SURFACE = "surface:100"
MY_WS = "workspace:1"


def _seed_self(title="me", ws=MY_WS):
    p = registry.manifest_path(MY_SURFACE)
    p.write_text(json.dumps({
        "title": title, "surface_ref": MY_SURFACE,
        "workspace_ref": ws,
        "started_at": 1, "last_seen": int(time.time()),
    }))


@pytest.fixture
def fc(monkeypatch):
    """Two workspaces by default: workspace:1 (Self, where caller sits)
    and workspace:2 (Other). Tests add more as needed."""
    fc = FakeCmux()
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref=MY_SURFACE, title="me")
    fc.apply(monkeypatch, my_surface_ref=MY_SURFACE)
    return fc


def _run_send(monkeypatch, capsys, argv, body="hello world"):
    """Drive cmd_send with a tmp message file. Returns parsed JSON."""
    msg_path = "/tmp/p2p-test-msg.txt"
    with open(msg_path, "w") as f:
        f.write(body)
    full = ["send", "--message-file", msg_path] + argv
    args = cli.build_parser().parse_args(full)
    rc = cli.cmd_send(args)
    out = json.loads(capsys.readouterr().out)
    return rc, out


# ---------------- title-resolution paths ----------------

def test_workspace_by_title_resolves_to_single_match(
        tmp_registry, fc, monkeypatch, capsys):
    """--workspace <title> with exactly one match scopes title
    resolution to that workspace. Peer in that workspace is reachable."""
    _seed_self()
    fc.add(workspace_ref="workspace:2", workspace_title="Other",
           surface_ref="surface:200", title="reviewer")
    registry.register("reviewer", "surface:200", "workspace:2",
                      live_set={MY_SURFACE, "surface:200"})

    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "reviewer", "--workspace", "Other",
    ])
    assert rc == cli.EXIT_OK
    assert out["ok"] is True
    assert out["surface"] == "surface:200"
    assert out["title"] == "reviewer"


def test_workspace_title_resolves_in_other_window(
        tmp_registry, fc, monkeypatch, capsys):
    """The `$p2p renderer in HTML` story: HTML is a workspace title that
    lives in a different window. With no --window, locality cascades
    past the caller's own workspace/window to find it, then scopes the
    peer-title resolution there."""
    _seed_self()
    fc.add(window_ref="window:2", window_index=2,
           workspace_ref="workspace:20", workspace_title="HTML",
           surface_ref="surface:200", title="renderer")
    registry.register("renderer", "surface:200", "workspace:20",
                      live_set={MY_SURFACE, "surface:200"})
    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "renderer", "--workspace", "HTML",
    ])
    assert rc == cli.EXIT_OK
    assert out["ok"] is True
    assert out["surface"] == "surface:200"
    assert out["title"] == "renderer"


def test_workspace_title_prefers_caller_own_workspace(
        tmp_registry, fc, monkeypatch, capsys):
    """Locality tier 1: when the caller's own workspace title matches the
    requested workspace title, scope there even though another window
    also has a workspace with that title (and a same-named peer)."""
    _seed_self()
    fc.surfaces[0].workspace_title = "HTML"  # caller's own ws is HTML
    # renderer in the caller's own (HTML) workspace
    fc.add(workspace_ref=MY_WS, workspace_title="HTML",
           surface_ref="surface:150", title="renderer")
    registry.register("renderer", "surface:150", MY_WS,
                      live_set={MY_SURFACE, "surface:150"})
    # decoy HTML workspace in another window with its own renderer
    fc.add(window_ref="window:2", window_index=2,
           workspace_ref="workspace:20", workspace_title="HTML",
           surface_ref="surface:200", title="renderer")
    registry.register("renderer", "surface:200", "workspace:20",
                      live_set={MY_SURFACE, "surface:150", "surface:200"})
    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "renderer", "--workspace", "HTML",
    ])
    assert rc == cli.EXIT_OK
    assert out["ok"] is True
    assert out["surface"] == "surface:150"


def test_workspace_title_ambiguous_across_other_windows(
        tmp_registry, fc, monkeypatch, capsys):
    """Two HTML workspaces in different (non-caller) windows → the
    --workspace title is ambiguous; no silent pick, no send."""
    _seed_self()
    fc.add(window_ref="window:2", window_index=2,
           workspace_ref="workspace:20", workspace_title="HTML",
           surface_ref="surface:200", title="renderer")
    fc.add(window_ref="window:3", window_index=3,
           workspace_ref="workspace:30", workspace_title="HTML",
           surface_ref="surface:300", title="renderer")
    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "renderer", "--workspace", "HTML",
    ])
    assert rc == cli.EXIT_HANDOFF
    assert out["ok"] is False
    assert out["code"] == "workspace_ambiguous"
    refs = {c["ref"] for c in out["candidates"]}
    assert refs == {"workspace:20", "workspace:30"}
    assert fc.sent == []


def test_window_by_ref_scopes_title_resolution(
        tmp_registry, fc, monkeypatch, capsys):
    """--window <ref> with no --workspace searches that window's
    workspaces for the addressed tab title."""
    _seed_self()
    fc.add(window_ref="window:2", window_index=2,
           workspace_ref="workspace:20", workspace_title="Remote",
           surface_ref="surface:200", title="reviewer")
    registry.register("reviewer", "surface:200", "workspace:20",
                      live_set={MY_SURFACE, "surface:200"})

    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "reviewer", "--window", "window:2",
    ])
    assert rc == cli.EXIT_OK
    assert out["ok"] is True
    assert out["surface"] == "surface:200"


def test_window_unknown_returns_handoff(
        tmp_registry, fc, monkeypatch, capsys):
    """--window <ref> must name a live cmux window; p2p does not
    silently fall back to the caller's window."""
    _seed_self()
    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "reviewer", "--window", "window:404",
    ])
    assert rc == cli.EXIT_HANDOFF
    assert out["ok"] is False
    assert out["code"] == "window_unknown"
    assert out["requested"] == "window:404"
    assert out["action_required"] == "pick_window"
    assert out["retryable"] is True
    assert fc.sent == []


def test_window_disambiguates_workspace_title(
        tmp_registry, fc, monkeypatch, capsys):
    """Two windows can hold same-titled workspaces. --window scopes the
    --workspace title lookup before peer title resolution."""
    _seed_self()
    fc.add(window_ref="window:1", window_index=1,
           workspace_ref="workspace:2", workspace_title="Review",
           surface_ref="surface:200", title="wrong_reviewer")
    fc.add(window_ref="window:2", window_index=2,
           workspace_ref="workspace:3", workspace_title="Review",
           surface_ref="surface:300", title="reviewer")
    registry.register("reviewer", "surface:300", "workspace:3",
                      live_set={MY_SURFACE, "surface:200", "surface:300"})

    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "reviewer", "--window", "window:2",
        "--workspace", "Review",
    ])
    assert rc == cli.EXIT_OK
    assert out["ok"] is True
    assert out["surface"] == "surface:300"


def test_live_peer_surface_ignores_stale_scope_hints(
        tmp_registry, fc, monkeypatch, capsys):
    """Bootstrap replies may include peer_workspace / peer_window hints
    that have gone stale. A live --peer-surface is the exact pointer, so
    stale scope hints must not block the direct send path."""
    _seed_self()
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="caller")
    registry.register("caller", "surface:200", MY_WS,
                      live_set={MY_SURFACE, "surface:200"})

    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "caller",
        "--peer-surface", "surface:200",
        "--workspace", "missing_workspace",
        "--window", "window:404",
    ])
    assert rc == cli.EXIT_OK
    assert out["ok"] is True
    assert out["resolved_by"] == "explicit_surface"
    assert out["surface"] == "surface:200"
    assert fc.sent[0][0] == "surface:200"


def test_workspace_by_ref_still_resolves(
        tmp_registry, fc, monkeypatch, capsys):
    """--workspace workspace:N (ref form) keeps working — no title
    lookup, scope is the ref directly."""
    _seed_self()
    fc.add(workspace_ref="workspace:2", workspace_title="Other",
           surface_ref="surface:200", title="reviewer")
    registry.register("reviewer", "surface:200", "workspace:2",
                      live_set={MY_SURFACE, "surface:200"})

    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "reviewer", "--workspace", "workspace:2",
    ])
    assert rc == cli.EXIT_OK
    assert out["ok"] is True
    assert out["surface"] == "surface:200"


def test_workspace_all_is_global_scope(
        tmp_registry, fc, monkeypatch, capsys):
    """--workspace all means resolution sees every workspace; a single
    cross-workspace match resolves cleanly."""
    _seed_self()
    fc.add(workspace_ref="workspace:5", workspace_title="Far",
           surface_ref="surface:500", title="loner")
    registry.register("loner", "surface:500", "workspace:5",
                      live_set={MY_SURFACE, "surface:500"})

    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "loner", "--workspace", "all",
    ])
    assert rc == cli.EXIT_OK
    assert out["ok"] is True
    assert out["surface"] == "surface:500"


def test_workspace_unknown_title_returns_handoff(
        tmp_registry, fc, monkeypatch, capsys):
    """--workspace <title> with no matches returns workspace_unknown.
    No silent fallback to caller's workspace, no send attempt."""
    _seed_self()
    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "anyone", "--workspace", "no_such_workspace",
    ])
    assert rc == cli.EXIT_HANDOFF
    assert out["ok"] is False
    assert out["code"] == "workspace_unknown"
    assert out["requested"] == "no_such_workspace"
    assert out["action_required"] == "pick_workspace"
    assert out["retryable"] is True
    assert fc.sent == []


def test_workspace_unknown_ref_returns_handoff(
        tmp_registry, fc, monkeypatch, capsys):
    """workspace:N that doesn't exist is also workspace_unknown — refs
    don't fall back to title lookup."""
    _seed_self()
    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "anyone", "--workspace", "workspace:9999",
    ])
    assert rc == cli.EXIT_HANDOFF
    assert out["ok"] is False
    assert out["code"] == "workspace_unknown"
    assert out["requested"] == "workspace:9999"
    assert fc.sent == []


def test_workspace_ambiguous_title_returns_handoff(
        tmp_registry, fc, monkeypatch, capsys):
    """Two live workspaces titled 'ambig' → workspace_ambiguous with
    both candidates in the JSON."""
    _seed_self()
    fc.add(workspace_ref="workspace:2", workspace_title="ambig",
           surface_ref="surface:200", title="x")
    fc.add(workspace_ref="workspace:3", workspace_title="ambig",
           surface_ref="surface:300", title="y")
    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "anyone", "--workspace", "ambig",
    ])
    assert rc == cli.EXIT_HANDOFF
    assert out["ok"] is False
    assert out["code"] == "workspace_ambiguous"
    refs = {c["ref"] for c in out["candidates"]}
    assert refs == {"workspace:2", "workspace:3"}
    assert out["action_required"] == "pick_candidate"
    assert out["retryable"] is True
    assert fc.sent == []


def test_default_scope_unchanged_without_workspace_flag(
        tmp_registry, fc, monkeypatch, capsys):
    """No --workspace → default scope is caller's workspace. Peer in
    caller's workspace resolves cleanly; peer elsewhere returns
    peer_ambiguous (existing behavior)."""
    _seed_self()
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="local_peer")
    registry.register("local_peer", "surface:200", MY_WS,
                      live_set={MY_SURFACE, "surface:200"})
    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "local_peer",
    ])
    assert rc == cli.EXIT_OK
    assert out["ok"] is True
    assert out["surface"] == "surface:200"


# ---------------- peer_not_found (p2p never spawns) ----------------

def test_peer_not_found_in_title_scoped_workspace_without_siblings(
        tmp_registry, fc, monkeypatch, capsys):
    """--workspace <title> scopes the title match. The target workspace
    has an UNREGISTERED tab (not a p2p agent), so a miss is genuinely
    empty of routable peers → peer_not_found with no candidates and no
    spawn payload. p2p never spawns."""
    _seed_self()
    # Workspace 'Sandbox' exists; its only tab is an unregistered, non-
    # p2p surface — not a routable peer.
    fc.add(workspace_ref="workspace:7", workspace_title="Sandbox",
           surface_ref="surface:700", title="someone_else")
    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "ghost", "--workspace", "Sandbox",
    ])
    assert rc == cli.EXIT_HANDOFF
    assert out["ok"] is False
    assert out["code"] == "peer_not_found"
    assert out["candidates"] == []
    assert "payload_file" not in out
    assert "workspace" not in out
    assert out["action_required"] == "spawn_externally"
    assert fc.sent == []


def test_peer_not_found_lists_registered_sibling_in_scoped_workspace(
        tmp_registry, fc, monkeypatch, capsys):
    """The cross-workspace bug fix: --workspace <W> targets a workspace
    that holds a REGISTERED agent under a different title. A misnamed
    --peer must surface that agent as a candidate, never spawn a
    duplicate."""
    _seed_self()
    fc.add(workspace_ref="workspace:7", workspace_title="Sandbox",
           surface_ref="surface:700", title="agent_real")
    registry.register("agent_real", "surface:700", "workspace:7",
                      live_set={MY_SURFACE, "surface:700"})
    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "html", "--workspace", "Sandbox",
    ])
    assert rc == cli.EXIT_HANDOFF
    assert out["code"] == "peer_not_found"
    assert out["action_required"] == "pick_candidate"
    assert "payload_file" not in out
    refs = {c["ref"] for c in out["candidates"]}
    assert refs == {"surface:700"}
    assert out["candidates"][0]["title"] == "agent_real"
    assert fc.sent == []


def test_peer_not_found_no_workspace_flag(
        tmp_registry, fc, monkeypatch, capsys):
    """No --workspace → default scope is the caller's workspace. With
    no sibling agent there, a miss is peer_not_found, no spawn."""
    _seed_self()
    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "ghost",
    ])
    assert rc == cli.EXIT_HANDOFF
    assert out["code"] == "peer_not_found"
    assert out["candidates"] == []
    assert "payload_file" not in out


def test_peer_not_found_all_workspace(
        tmp_registry, fc, monkeypatch, capsys):
    """--workspace all is global scope. With no registered agent
    anywhere holding the title, a miss is peer_not_found."""
    _seed_self()
    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "ghost", "--workspace", "all",
    ])
    assert rc == cli.EXIT_HANDOFF
    assert out["code"] == "peer_not_found"
    assert out["candidates"] == []
    assert "payload_file" not in out
