"""--workspace front-door behavior driven against a FakeTerminal.

Workspace resolution itself lives on the backend (CmuxTerminal), so the
tests script a workspace_resolver on the FakeTerminal: zero matches
returns created=True, exact match returns created=False, two matches
raises workspace_ambiguous, a bad ref raises workspace_unknown.
"""

import json
import time

import pytest

import tforklib as ft
from fake_terminal import FakeTerminal, make_scrollback

NONCE = "ws123"


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)


@pytest.fixture
def reg(tmp_path):
    return tmp_path / "registry.toml"


def _ok_terminal(resolver):
    """A FakeTerminal that returns a clean-exit observation and uses
    the given workspace_resolver."""
    return FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=0),
                        workspace_resolver=resolver)


def test_workspace_create_new_workspace(reg):
    """--workspace <new-title> → resolver reports created=True; result
    JSON carries workspace.created=True and note mentions (created)."""
    def resolver(value, cwd):
        assert cwd  # the caller's cwd was forwarded
        return {"ref": "workspace:42", "title": value, "created": True}
    term = _ok_terminal(resolver)
    result = ft.run_fork(["echo", "hi"], workspace="exp_new",
                        terminal=term, nonce=NONCE, registry_path=reg)
    assert result["ok"] is True
    assert result["workspace"] == {"ref": "workspace:42",
                                   "title": "exp_new",
                                   "created": True}
    assert "exp_new" in result["note"]
    assert "(created)" in result["note"]
    # Fork was called with no placement direction (fresh pane) and the
    # resolved workspace info.
    fork_call = term.calls[1]  # [0] is resolve_workspace, [1] is fork
    assert fork_call[0] == "fork"
    assert fork_call[2] is None  # placement=None → fresh pane in workspace
    assert fork_call[6] == {"ref": "workspace:42", "title": "exp_new",
                            "created": True}


def test_workspace_reuse_existing(reg):
    """--workspace <existing-title> → resolver reports created=False."""
    def resolver(value, cwd):  # noqa: ARG001
        return {"ref": "workspace:7", "title": value, "created": False}
    term = _ok_terminal(resolver)
    result = ft.run_fork(["echo", "hi"], workspace="exp_existing",
                        terminal=term, nonce=NONCE, registry_path=reg)
    assert result["workspace"]["created"] is False
    assert "exp_existing" in result["note"]
    assert "(reused)" in result["note"]


def test_workspace_plus_placement_splits_workspace_pane(reg):
    """--workspace <name> + --placement right → fork receives placement
    direction so the backend splits the workspace's active pane."""
    def resolver(value, cwd):  # noqa: ARG001
        return {"ref": "workspace:7", "title": value, "created": False}
    term = _ok_terminal(resolver)
    ft.run_fork(["echo", "hi"], workspace="exp1", placement="right",
                terminal=term, nonce=NONCE, registry_path=reg)
    fork_call = term.calls[1]
    assert fork_call[2] == "right"  # placement forwarded
    assert fork_call[6]["ref"] == "workspace:7"


def test_workspace_bad_ref_returns_workspace_unknown(reg):
    """A workspace:N value that doesn't resolve raises workspace_unknown
    (refs are not names, no implicit creation)."""
    def resolver(value, _cwd):
        raise ft.err_workspace_unknown(value)
    term = _ok_terminal(resolver)
    with pytest.raises(ft.ForkError) as exc:
        ft.run_fork(["echo", "hi"], workspace="workspace:99999",
                    terminal=term, nonce=NONCE, registry_path=reg)
    assert exc.value.code == "workspace_unknown"
    assert "workspace:99999" in exc.value.human_message


def test_workspace_ambiguous_title_returns_candidates(reg):
    """Two workspaces titled 'ambig' → workspace_ambiguous with each
    candidate's ref in the human message."""
    def resolver(value, _cwd):
        raise ft.err_workspace_ambiguous(value, [
            {"ref": "workspace:1", "title": value},
            {"ref": "workspace:2", "title": value},
        ])
    term = _ok_terminal(resolver)
    with pytest.raises(ft.ForkError) as exc:
        ft.run_fork(["echo", "hi"], workspace="ambig",
                    terminal=term, nonce=NONCE, registry_path=reg)
    assert exc.value.code == "workspace_ambiguous"
    assert "workspace:1" in exc.value.human_message
    assert "workspace:2" in exc.value.human_message


def test_workspace_and_anchor_returns_conflict(reg):
    """--workspace + --anchor is rejected before the terminal is even
    consulted — the anchor's workspace is implicit, so the two can
    disagree."""
    term = _ok_terminal(lambda *a: None)
    with pytest.raises(ft.ForkError) as exc:
        ft.run_fork(["echo", "hi"], workspace="exp1", anchor="some_tab",
                    terminal=term, nonce=NONCE, registry_path=reg)
    assert exc.value.code == "workspace_anchor_conflict"
    # No fork attempt was made.
    assert term.calls == []


def test_no_workspace_keeps_existing_behavior(reg):
    """Result JSON's `workspace` field is None when --workspace was not
    passed. Plain split semantics are unchanged."""
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=0))
    result = ft.run_fork(["echo", "hi"], placement="right",
                        terminal=term, nonce=NONCE, registry_path=reg)
    assert result["workspace"] is None
    # No workspace clause in the note when no workspace was involved.
    assert "workspace" not in result["note"]


def test_workspace_default_placement_means_fresh_pane(reg):
    """No --placement and --workspace given → fork sees placement=None
    so the backend opens a fresh pane in the workspace, not a split."""
    def resolver(value, _cwd):
        return {"ref": "workspace:9", "title": value, "created": False}
    term = _ok_terminal(resolver)
    ft.run_fork(["echo", "hi"], workspace="exp_x", terminal=term,
                nonce=NONCE, registry_path=reg)
    fork_call = term.calls[1]
    assert fork_call[2] is None  # placement None passes through


def test_workspace_field_in_main_json_output(reg, capsys, monkeypatch):
    """End-to-end: main() prints `workspace: {ref, title, created}` in
    the success JSON object."""
    def resolver(value, _cwd):
        return {"ref": "workspace:55", "title": value, "created": True}
    term = _ok_terminal(resolver)
    # Patch resolve_terminal so the CLI picks up our FakeTerminal.
    monkeypatch.setattr("tforklib.orchestrate.resolve_terminal",
                        lambda: term)
    code = ft.main(["--workspace", "exp_main", "--", "echo", "hi"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["workspace"] == {"ref": "workspace:55",
                                "title": "exp_main",
                                "created": True}


def test_workspace_unknown_main_returns_handoff(reg, capsys, monkeypatch):
    """main() converts a workspace_unknown ForkError into the standard
    handoff JSON object with the correct code."""
    def resolver(value, _cwd):
        raise ft.err_workspace_unknown(value)
    term = _ok_terminal(resolver)
    monkeypatch.setattr("tforklib.orchestrate.resolve_terminal",
                        lambda: term)
    code = ft.main(["--workspace", "workspace:99999", "--", "echo", "hi"])
    assert code != 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["code"] == "workspace_unknown"


# ---- CmuxTerminal._open_surface initial-pane reuse ----

def test_open_surface_reuses_initial_surface_on_created(monkeypatch):
    """When the workspace was just created (workspace.created=True) and
    no placement is given, _open_surface reuses the workspace's initial
    surface instead of calling cmux new-pane. cmux new-workspace seeds
    one pane/surface; spawning another would leave a blank pane."""
    from tforklib import terminal as term_mod
    monkeypatch.setattr(term_mod, "_cmux_tree", lambda: {"windows": [
        {"workspaces": [
            {"ref": "workspace:42", "panes": [
                {"surfaces": [{"ref": "surface:777"}]}
            ]}
        ]}
    ]})
    called = []
    cmx = term_mod.CmuxTerminal()
    monkeypatch.setattr(cmx, "_new_pane_in_workspace",
                        lambda *a, **k: called.append(("new_pane", a, k)))
    seeded = cmx._open_surface(
        placement=None, anchor=None,
        workspace={"ref": "workspace:42", "title": "x", "created": True},
    )
    assert seeded == "surface:777"
    assert called == []
    # The surface→workspace cache is seeded so downstream per-pane calls
    # carry --workspace.
    assert cmx._workspaces["surface:777"] == "workspace:42"


def test_open_surface_calls_new_pane_when_workspace_reused(monkeypatch):
    """A reused workspace already had whatever panes the user opened;
    tfork must open its own fresh pane, not stomp into one of theirs."""
    from tforklib import terminal as term_mod
    monkeypatch.setattr(term_mod, "_cmux_tree", lambda: {"windows": []})
    cmx = term_mod.CmuxTerminal()
    called = []
    monkeypatch.setattr(cmx, "_new_pane_in_workspace",
                        lambda ws_ref, direction:
                            called.append((ws_ref, direction))
                            or "surface:fresh")
    out = cmx._open_surface(
        placement=None, anchor=None,
        workspace={"ref": "workspace:9", "title": "x", "created": False},
    )
    assert out == "surface:fresh"
    assert called == [("workspace:9", None)]


def test_open_surface_skips_reuse_when_created_workspace_has_extra_panes(
        monkeypatch):
    """Defensive: if a TOCTOU race let someone open more panes between
    cmux new-workspace and our reuse lookup, fall back to new-pane —
    reusing an arbitrary one of their panes would be wrong."""
    from tforklib import terminal as term_mod
    monkeypatch.setattr(term_mod, "_cmux_tree", lambda: {"windows": [
        {"workspaces": [
            {"ref": "workspace:5", "panes": [
                {"surfaces": [{"ref": "surface:1"}]},
                {"surfaces": [{"ref": "surface:2"}]},
            ]}
        ]}
    ]})
    cmx = term_mod.CmuxTerminal()
    called = []
    monkeypatch.setattr(cmx, "_new_pane_in_workspace",
                        lambda ws_ref, direction:
                            called.append((ws_ref, direction))
                            or "surface:new")
    out = cmx._open_surface(
        placement=None, anchor=None,
        workspace={"ref": "workspace:5", "title": "x", "created": True},
    )
    assert out == "surface:new"
    assert called == [("workspace:5", None)]
