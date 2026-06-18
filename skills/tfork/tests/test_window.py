"""--window front-door behavior and CmuxTerminal window resolution.

Window resolution itself lives on the backend (CmuxTerminal). The front-door
tests script a window_resolver on the FakeTerminal (mirroring the --workspace
tests); the backend tests drive CmuxTerminal.resolve_window directly with a
monkeypatched cmux tree and helpers.
"""

import json
import time

import pytest

import tforklib as ft
from fake_terminal import FakeTerminal, make_scrollback

NONCE = "win123"


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)


@pytest.fixture
def reg(tmp_path):
    return tmp_path / "registry.toml"


def _ok_terminal(resolver):
    """A FakeTerminal that returns a clean-exit observation and uses the
    given window_resolver."""
    return FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=0),
                        window_resolver=resolver)


# ---- front door (run_fork / main) ----

def test_window_new_forwards_and_reports(reg):
    """--window new → resolve_window is called with 'new'; the resolved
    window/workspace flow into the result and the fork gets the workspace."""
    def resolver(value, workspace, cwd):
        assert value == "new"
        assert workspace is None
        assert cwd  # caller cwd forwarded
        return ({"ref": "window:7", "created": True},
                {"ref": "workspace:7", "title": "", "created": True})
    term = _ok_terminal(resolver)
    result = ft.run_fork(["claude"], window="new", terminal=term,
                         nonce=NONCE, registry_path=reg)
    assert result["ok"] is True
    assert result["window"] == {"ref": "window:7", "created": True}
    assert result["workspace"]["created"] is True
    assert "new window" in result["note"]
    assert "window:7" in result["note"]
    # The fork received the workspace resolved inside the window.
    fork_call = next(c for c in term.calls if c[0] == "fork")
    assert fork_call[6] == {"ref": "workspace:7", "title": "",
                            "created": True}


def test_window_new_with_workspace_title(reg):
    """--window new --workspace reviewers → the title is forwarded to
    resolve_window and reflected in the result."""
    def resolver(value, workspace, cwd):  # noqa: ARG001
        assert workspace == "reviewers"
        return ({"ref": "window:8", "created": True},
                {"ref": "workspace:8", "title": workspace, "created": True})
    term = _ok_terminal(resolver)
    result = ft.run_fork(["claude"], window="new", workspace="reviewers",
                         terminal=term, nonce=NONCE, registry_path=reg)
    assert result["workspace"]["title"] == "reviewers"
    assert "reviewers" in result["note"]


def test_window_existing_ref(reg):
    """--window window:2 → window reported as not created (existing)."""
    def resolver(value, workspace, cwd):  # noqa: ARG001
        assert value == "window:2"
        return ({"ref": "window:2", "created": False},
                {"ref": "workspace:30", "title": "", "created": True})
    term = _ok_terminal(resolver)
    result = ft.run_fork(["claude"], window="window:2", terminal=term,
                         nonce=NONCE, registry_path=reg)
    assert result["window"] == {"ref": "window:2", "created": False}
    assert "existing window" in result["note"]


def test_window_and_anchor_returns_conflict(reg):
    """--window + --anchor is rejected before the terminal is consulted."""
    term = _ok_terminal(lambda *a: None)
    with pytest.raises(ft.ForkError) as exc:
        ft.run_fork(["claude"], window="new", anchor="some_tab",
                    terminal=term, nonce=NONCE, registry_path=reg)
    assert exc.value.code == "window_anchor_conflict"
    assert term.calls == []  # no fork attempt


def test_no_window_leaves_window_field_none(reg):
    """When --window is absent the result's window field is None and the
    plain split path is untouched."""
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=0))
    result = ft.run_fork(["echo", "hi"], placement="right", terminal=term,
                         nonce=NONCE, registry_path=reg)
    assert result["window"] is None
    assert "window" not in result["note"]
    assert "resolve_window" not in term.methods_called()


def test_window_field_in_main_json_output(capsys, monkeypatch):
    """End-to-end: main() prints window: {ref, created} in the success JSON."""
    def resolver(value, workspace, cwd):  # noqa: ARG001
        return ({"ref": "window:9", "created": True},
                {"ref": "workspace:9", "title": "", "created": True})
    term = _ok_terminal(resolver)
    monkeypatch.setattr("tforklib.orchestrate.resolve_terminal",
                        lambda: term)
    code = ft.main(["--window", "new", "--", "claude"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["window"] == {"ref": "window:9", "created": True}


def test_window_unknown_main_returns_handoff(capsys, monkeypatch):
    """main() converts a window_unknown ForkError into the standard handoff."""
    def resolver(value, workspace, cwd):  # noqa: ARG001
        raise ft.err_window_unknown(value)
    term = _ok_terminal(resolver)
    monkeypatch.setattr("tforklib.orchestrate.resolve_terminal",
                        lambda: term)
    code = ft.main(["--window", "window:999", "--", "claude"])
    assert code != 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["code"] == "window_unknown"


# ---- CmuxTerminal.resolve_window (backend) ----

def _new_window_tree(seeded_title="Window 3"):
    return {"windows": [
        {"ref": "window:3", "id": "UUID-1", "index": 1, "workspaces": [
            {"ref": "workspace:9", "title": seeded_title}
        ]}
    ]}


def test_resolve_new_window_reuses_seeded_workspace(monkeypatch):
    """--window new with no title reuses the fresh window's sole seeded
    workspace; no rename is issued."""
    from tforklib import terminal as term_mod
    cmx = term_mod.CmuxTerminal()
    monkeypatch.setattr(cmx, "_new_window", lambda: "UUID-1")
    monkeypatch.setattr(term_mod, "_cmux_tree", _new_window_tree)
    renames = []
    monkeypatch.setattr(cmx, "_rename_workspace",
                        lambda *a: renames.append(a))
    win_info, ws_info = cmx.resolve_window("new", None, "/tmp")
    assert win_info == {"ref": "window:3", "created": True}
    assert ws_info == {"ref": "workspace:9", "title": "Window 3",
                       "created": True}
    assert renames == []


def test_resolve_new_window_renames_when_title_given(monkeypatch):
    """--window new --workspace reviewers renames the seeded workspace
    instead of creating a second one."""
    from tforklib import terminal as term_mod
    cmx = term_mod.CmuxTerminal()
    monkeypatch.setattr(cmx, "_new_window", lambda: "UUID-1")
    monkeypatch.setattr(term_mod, "_cmux_tree", _new_window_tree)
    renames = []
    monkeypatch.setattr(cmx, "_rename_workspace",
                        lambda *a: renames.append(a))
    win_info, ws_info = cmx.resolve_window("new", "reviewers", "/tmp")
    assert ws_info == {"ref": "workspace:9", "title": "reviewers",
                       "created": True}
    assert renames == [("workspace:9", "reviewers", "window:3")]


def test_resolve_new_window_missing_from_tree_raises(monkeypatch):
    """If the freshly-created window never shows up in the tree, fail with
    window_create_failed rather than guessing."""
    from tforklib import terminal as term_mod
    cmx = term_mod.CmuxTerminal()
    monkeypatch.setattr(cmx, "_new_window", lambda: "UUID-GONE")
    monkeypatch.setattr(term_mod, "_cmux_tree", lambda: {"windows": []})
    with pytest.raises(ft.ForkError) as exc:
        cmx.resolve_window("new", None, "/tmp")
    assert exc.value.code == "window_create_failed"


def _existing_window_tree(workspaces):
    """A one-window tree (window:2) holding the given workspaces. Each item is
    ``(ref, title)`` or ``(ref, title, uuid)``."""
    def _ws(item):
        node = {"ref": item[0], "title": item[1]}
        if len(item) > 2 and item[2]:
            node["id"] = item[2]
        return node
    return lambda: {"windows": [
        {"ref": "window:2", "id": "W2", "index": 1,
         "workspaces": [_ws(w) for w in workspaces]}
    ]}


def test_resolve_existing_window_creates_fresh_workspace(monkeypatch):
    """--window <ref> with no title creates a fresh workspace in that
    window (created=True so the seeded surface is reused downstream)."""
    from tforklib import terminal as term_mod
    cmx = term_mod.CmuxTerminal()
    monkeypatch.setattr(term_mod, "_cmux_tree", _existing_window_tree([]))
    created = []
    monkeypatch.setattr(
        cmx, "_create_workspace",
        lambda title, cwd, window=None: (
            created.append((title, cwd, window)) or ("workspace:50", None)))
    win_info, ws_info = cmx.resolve_window("window:2", None, "/tmp")
    assert win_info == {"ref": "window:2", "created": False}
    assert ws_info == {"ref": "workspace:50", "title": "", "created": True}
    assert created == [(None, "/tmp", "window:2")]


def test_resolve_existing_window_normalizes_index_to_ref(monkeypatch):
    """An index input resolves to the canonical window:N ref in the result,
    not the raw token the caller passed."""
    from tforklib import terminal as term_mod
    cmx = term_mod.CmuxTerminal()
    monkeypatch.setattr(term_mod, "_cmux_tree", _existing_window_tree([]))
    monkeypatch.setattr(cmx, "_create_workspace",
                        lambda *a, **k: ("workspace:50", None))
    win_info, _ = cmx.resolve_window("1", None, "/tmp")  # index 1 → window:2
    assert win_info == {"ref": "window:2", "created": False}


def test_resolve_existing_window_unknown_raises(monkeypatch):
    """A window value matching no live window surfaces as window_unknown,
    before any workspace is created."""
    from tforklib import terminal as term_mod
    cmx = term_mod.CmuxTerminal()
    monkeypatch.setattr(term_mod, "_cmux_tree", lambda: {"windows": []})
    created = []
    monkeypatch.setattr(cmx, "_create_workspace",
                        lambda *a, **k: created.append(a) or ("X", None))
    with pytest.raises(ft.ForkError) as exc:
        cmx.resolve_window("window:999", None, "/tmp")
    assert exc.value.code == "window_unknown"
    assert "window:999" in exc.value.human_message
    assert created == []


def test_resolve_existing_window_reuses_matching_workspace(monkeypatch):
    """--window <ref> --workspace reviewers reuses an in-window title match."""
    from tforklib import terminal as term_mod
    cmx = term_mod.CmuxTerminal()
    monkeypatch.setattr(term_mod, "_cmux_tree", _existing_window_tree(
        [("workspace:1", "reviewers"), ("workspace:2", "other")]))
    win_info, ws_info = cmx.resolve_window("window:2", "reviewers", "/tmp")
    assert win_info == {"ref": "window:2", "created": False}
    assert ws_info == {"ref": "workspace:1", "title": "reviewers",
                       "created": False}


def test_resolve_existing_window_ambiguous_workspace(monkeypatch):
    """Two in-window workspaces sharing the title → workspace_ambiguous."""
    from tforklib import terminal as term_mod
    cmx = term_mod.CmuxTerminal()
    monkeypatch.setattr(term_mod, "_cmux_tree", _existing_window_tree(
        [("workspace:1", "dup"), ("workspace:2", "dup")]))
    with pytest.raises(ft.ForkError) as exc:
        cmx.resolve_window("window:2", "dup", "/tmp")
    assert exc.value.code == "workspace_ambiguous"


# ---- --workspace ref vs title in the window path ----

def test_resolve_new_window_rejects_ref_workspace(monkeypatch):
    """--window new --workspace workspace:1 is rejected: a fresh window's
    seeded workspace can only be named, never bound to an existing ref. The
    window is not even created."""
    from tforklib import terminal as term_mod
    cmx = term_mod.CmuxTerminal()
    called = []
    monkeypatch.setattr(cmx, "_new_window",
                        lambda: called.append("new") or "UUID-1")
    with pytest.raises(ft.ForkError) as exc:
        cmx.resolve_window("new", "workspace:1", "/tmp")
    assert exc.value.code == "bad_arguments"
    assert called == []


def test_resolve_workspace_in_window_reuses_ref_present_in_window(monkeypatch):
    """--window window:2 --workspace workspace:1 reuses the ref when it lives
    in that window — never creates a workspace literally named 'workspace:1'."""
    from tforklib import terminal as term_mod
    cmx = term_mod.CmuxTerminal()
    monkeypatch.setattr(term_mod, "_cmux_tree", _existing_window_tree(
        [("workspace:1", "reviewers")]))
    created = []
    monkeypatch.setattr(cmx, "_create_workspace",
                        lambda *a, **k: created.append(a) or ("X", None))
    win_info, ws_info = cmx.resolve_window("window:2", "workspace:1", "/tmp")
    assert ws_info == {"ref": "workspace:1", "title": "reviewers",
                       "created": False}
    assert created == []


def test_resolve_workspace_in_window_reuses_uuid_ref(monkeypatch):
    """A workspace UUID present in the target window is reused (matched
    against the node's id), returning the canonical workspace:N ref — the
    contract says --workspace accepts a UUID, not just workspace:N."""
    from tforklib import terminal as term_mod
    cmx = term_mod.CmuxTerminal()
    uid = "ABCDEF12-3456-7890-ABCD-EF1234567890"
    monkeypatch.setattr(term_mod, "_cmux_tree", _existing_window_tree(
        [("workspace:1", "reviewers", uid)]))
    created = []
    monkeypatch.setattr(cmx, "_create_workspace",
                        lambda *a, **k: created.append(a) or ("X", None))
    win_info, ws_info = cmx.resolve_window("window:2", uid, "/tmp")
    assert ws_info == {"ref": "workspace:1", "title": "reviewers",
                       "created": False}
    assert created == []


def test_resolve_workspace_in_window_ref_miss_raises(monkeypatch):
    """A workspace ref absent from the target window is workspace_unknown,
    not a silent create (refs are not names)."""
    from tforklib import terminal as term_mod
    cmx = term_mod.CmuxTerminal()
    monkeypatch.setattr(term_mod, "_cmux_tree", _existing_window_tree(
        [("workspace:1", "reviewers")]))
    created = []
    monkeypatch.setattr(cmx, "_create_workspace",
                        lambda *a, **k: created.append(a) or ("X", None))
    with pytest.raises(ft.ForkError) as exc:
        cmx.resolve_window("window:2", "workspace:99", "/tmp")
    assert exc.value.code == "workspace_unknown"
    assert created == []
