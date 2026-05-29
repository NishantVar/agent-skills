"""--workspace value handling on `send`: title vs ref vs `all`, plus
the workspace_unknown / workspace_ambiguous handoffs and the
peer_unknown payload's workspace passthrough."""

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


# ---------------- peer_unknown payload passthrough ----------------

def test_peer_unknown_carries_workspace_title_for_spawn(
        tmp_registry, fc, monkeypatch, capsys):
    """Spec: title preferred over ref in the peer_unknown payload's
    workspace field for spawn-target stability. Passing
    --workspace <title> surfaces the title, not the resolved ref."""
    _seed_self()
    # Workspace 'Sandbox' exists; nobody in it holds the addressed title.
    fc.add(workspace_ref="workspace:7", workspace_title="Sandbox",
           surface_ref="surface:700", title="someone_else")
    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "ghost", "--workspace", "Sandbox",
    ])
    assert rc == cli.EXIT_HANDOFF
    assert out["ok"] is False
    assert out["code"] == "peer_unknown"
    assert out["workspace"] == "Sandbox"
    # Instruction tells tfork the workspace target.
    assert "--workspace Sandbox" in out["agent_instruction"]


def test_peer_unknown_ref_surfaces_title_when_resolvable(
        tmp_registry, fc, monkeypatch, capsys):
    """When --workspace is a ref but the ref maps to a live workspace
    with a title, the spawn payload prefers the title (per spec
    'Title preferred over ref in the payload for stability')."""
    _seed_self()
    fc.add(workspace_ref="workspace:7", workspace_title="Sandbox",
           surface_ref="surface:700", title="someone_else")
    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "ghost", "--workspace", "workspace:7",
    ])
    assert rc == cli.EXIT_HANDOFF
    assert out["code"] == "peer_unknown"
    assert out["workspace"] == "Sandbox"


def test_peer_unknown_ref_without_title_keeps_ref(
        tmp_registry, fc, monkeypatch, capsys):
    """A workspace_ref pointing at a live workspace with empty title
    falls through to the ref itself."""
    _seed_self()
    fc.add(workspace_ref="workspace:7", workspace_title="",
           surface_ref="surface:700", title="x")
    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "ghost", "--workspace", "workspace:7",
    ])
    assert rc == cli.EXIT_HANDOFF
    assert out["code"] == "peer_unknown"
    assert out["workspace"] == "workspace:7"


def test_peer_unknown_no_workspace_flag_omits_field(
        tmp_registry, fc, monkeypatch, capsys):
    """No --workspace → peer_unknown.workspace is None and the spawn
    instruction has no `--workspace` clause for tfork."""
    _seed_self()
    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "ghost",
    ])
    assert rc == cli.EXIT_HANDOFF
    assert out["code"] == "peer_unknown"
    assert out["workspace"] is None
    assert "--workspace" not in out["agent_instruction"]


def test_peer_unknown_all_workspace_does_not_pin_spawn(
        tmp_registry, fc, monkeypatch, capsys):
    """--workspace all is global scope, not a placement directive.
    peer_unknown.workspace stays None so tfork doesn't pin the new
    peer to a specific workspace."""
    _seed_self()
    rc, out = _run_send(monkeypatch, capsys, [
        "--peer", "ghost", "--workspace", "all",
    ])
    assert rc == cli.EXIT_HANDOFF
    assert out["code"] == "peer_unknown"
    assert out["workspace"] is None
