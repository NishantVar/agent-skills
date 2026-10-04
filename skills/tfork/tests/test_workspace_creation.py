"""Fresh creation must never join a workspace selected by title."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from tforklib.cli import parse_args
from tforklib.errors import ForkError, err_bad_arguments
from tforklib.orchestrate import run_fork
from tforklib.terminal import CmuxTerminal
from fake_terminal import FakeTerminal, make_scrollback


def backend(monkeypatch, tmp_path):
    monkeypatch.setattr("tforklib.terminal.Path.home", lambda: tmp_path)
    terminal = CmuxTerminal()
    terminal._window_node = Mock(return_value={"ref": "window:2"})
    return terminal


def test_creation_chooses_lowest_suffix_without_joining(monkeypatch, tmp_path):
    terminal = backend(monkeypatch, tmp_path)
    terminal._list_workspaces = Mock(side_effect=[[("workspace:10", "feature"), ("workspace:11", "feature_2")],
                                                  [("workspace:10", "feature"), ("workspace:11", "feature_2"), ("workspace:20", "feature_3")]])
    terminal._create_workspace = Mock(return_value=("workspace:20", None))
    window, workspace = terminal.create_named_workspace("window:2", "feature", "/repo")
    assert workspace == {"ref": "workspace:20", "title": "feature_3", "created": True}
    terminal._create_workspace.assert_called_once_with("feature_3", "/repo", window="window:2")
    assert not window["created"]


def test_stale_snapshot_renames_only_owned_ref_before_delivery(monkeypatch, tmp_path):
    terminal = backend(monkeypatch, tmp_path)
    terminal._list_workspaces = Mock(side_effect=[[], [("workspace:10", "feature"), ("workspace:99", "feature")],
                                                  [("workspace:10", "feature"), ("workspace:99", "feature_2")]])
    terminal._resolve_workspace_in_window = Mock(side_effect=AssertionError("must not join"))
    terminal._create_workspace = Mock(return_value=("workspace:99", None))
    terminal._rename_workspace = Mock()
    result = terminal.create_named_workspace("window:2", "feature", "/repo")[1]
    assert result == {"ref": "workspace:99", "title": "feature_2", "created": True}
    terminal._rename_workspace.assert_called_once_with("workspace:99", "feature_2", "window:2")


def test_concurrent_creation_serializes_names(monkeypatch, tmp_path):
    terminal = backend(monkeypatch, tmp_path)
    live = []
    terminal._list_workspaces = lambda: list(live)
    def create(title, cwd, window):
        ref = f"workspace:{len(live) + 20}"
        live.append((ref, title))
        return ref, None
    terminal._create_workspace = create
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(lambda _: terminal.create_named_workspace("window:2", "feature", "/repo"), range(2)))
    assert {result[1]["title"] for result in results} == {"feature", "feature_2"}
    assert len({result[1]["ref"] for result in results}) == 2


def test_new_window_names_only_its_seeded_workspace(monkeypatch, tmp_path):
    terminal = backend(monkeypatch, tmp_path)
    terminal._list_workspaces = Mock(side_effect=[[("workspace:10", "feature")], [("workspace:10", "feature"), ("workspace:30", "feature_2")]])
    terminal._resolve_new_window = Mock(return_value=({"ref": "window:3", "created": True}, {"ref": "workspace:30", "title": "feature_2", "created": True}))
    assert terminal.create_named_workspace("new", "feature", "/repo")[1]["title"] == "feature_2"
    terminal._resolve_new_window.assert_called_once_with("feature_2", require_name=True)


def test_front_door_creation_precedes_command_delivery(tmp_path):
    terminal = FakeTerminal(process="zsh", text=make_scrollback("create1", exit_status=0))
    terminal.create_named_workspace = Mock(return_value=({"ref": "window:2", "created": False}, {"ref": "workspace:20", "title": "feature_2", "created": True}))
    result = run_fork(["echo", "hi"], workspace="feature", window="window:2", workspace_mode="create", terminal=terminal, nonce="create1", registry_path=tmp_path / "registry", delay=0)
    assert result["workspace"]["title"] == "feature_2"
    assert result["workspace"]["created"]
    assert parse_args(["--workspace-mode", "create", "--", "echo"]).workspace_mode == "create"
    terminal.create_named_workspace.side_effect = err_bad_arguments("bad")
    terminal.calls.clear()
    with pytest.raises(ForkError):
        run_fork(["echo"], workspace="feature", window="window:2", workspace_mode="create", terminal=terminal)
    assert not any(call[0] == "fork" for call in terminal.calls)


def test_post_creation_spawn_failure_retains_refs_and_outcome(tmp_path):
    from tforklib.errors import err_spawn_failed
    terminal = FakeTerminal(fork_error=err_spawn_failed("paste failed"))
    terminal.create_named_workspace = Mock(return_value=({"ref": "window:2", "created": False}, {"ref": "workspace:20", "title": "feature", "created": True}))
    with pytest.raises(ForkError) as raised:
        run_fork(["agent"], workspace="feature", window="window:2", workspace_mode="create", terminal=terminal, registry_path=tmp_path / "registry")
    result = raised.value.handoff()
    assert result["workspace"] == {"ref": "workspace:20", "title": "feature", "created": True}
    assert result["window"]["ref"] == "window:2"
    assert result["launch_outcome"]["state"] == "prework_failure"


def test_new_window_rename_failure_reports_actual_refs_without_delivery(monkeypatch, tmp_path):
    terminal = backend(monkeypatch, tmp_path)
    terminal._list_workspaces = Mock(return_value=[])
    terminal._new_window = Mock(return_value="window-id")
    terminal._window_node = Mock(return_value={"ref": "window:3", "workspaces": [{"ref": "workspace:30", "title": "Default"}]})
    terminal._rename_workspace = Mock()
    terminal.fork = Mock(side_effect=AssertionError("no command may be delivered"))
    with pytest.raises(ForkError) as raised:
        run_fork(["agent"], workspace="feature", window="new", workspace_mode="create", terminal=terminal)
    result = raised.value.handoff()
    assert result["code"] == "workspace_naming_failed"
    assert result["workspace"] == {"ref": "workspace:30", "title": "Default", "created": True}
    assert result["window"] == {"ref": "window:3", "created": True}
    assert "launch_outcome" not in result
    terminal.fork.assert_not_called()


def test_creation_claim_rejects_cancelled_stale_and_consumed_handoffs(tmp_path):
    import json
    from tforklib.creation_claim import consume_creation_claim
    claim = tmp_path / "claim.json"
    claim.write_text(json.dumps({"dispatch_id": "new-owner", "record": None, "creation_started": False}))
    with pytest.raises(ForkError):
        consume_creation_claim(claim, "cancelled-owner")
    assert not json.loads(claim.read_text())["creation_started"]
    consume_creation_claim(claim, "new-owner")
    assert json.loads(claim.read_text())["creation_started"]
    with pytest.raises(ForkError):
        consume_creation_claim(claim, "new-owner")


def test_simultaneous_spawn_delivers_each_command_to_its_own_surface(monkeypatch):
    import subprocess
    import threading
    terminal = CmuxTerminal()
    buffers = {}
    delivered = {}
    barrier = threading.Barrier(2)
    def run(argv):
        if argv[1] == "set-buffer":
            buffers[argv[3]] = argv[-1]
            barrier.wait(timeout=5)
        elif argv[1] == "paste-buffer":
            delivered[argv[5]] = buffers[argv[3]]
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr("tforklib.terminal._run", run)
    monkeypatch.setattr("tforklib.terminal.time.sleep", lambda _: None)
    with ThreadPoolExecutor(2) as executor:
        list(executor.map(lambda item: terminal._spawn(*item), [("surface:20", "command-first"), ("surface:21", "command-second")]))
    assert delivered == {"surface:20": "command-first", "surface:21": "command-second"}
    assert len(buffers) == 2


def test_simultaneous_create_launches_deliver_commands_to_their_returned_refs(monkeypatch, tmp_path):
    import subprocess
    import threading
    from tforklib.verify import Observation
    terminal = backend(monkeypatch, tmp_path)
    live = []
    terminal._list_workspaces = lambda: list(live)
    def create(title, cwd, window):
        ref = f"workspace:{len(live) + 20}"
        live.append((ref, title))
        return ref, None
    terminal._create_workspace = create
    def fork(command, placement, cwd, nonce, anchor, workspace):
        session = workspace["ref"].replace("workspace:", "surface:")
        terminal._spawn(session, command)
        return session
    terminal.fork = fork
    buffers = {}
    delivered = {}
    barrier = threading.Barrier(2)
    def run(argv):
        if argv[1] == "set-buffer":
            buffers[argv[3]] = argv[-1]
            barrier.wait(timeout=5)
        elif argv[1] == "paste-buffer":
            delivered[argv[5]] = buffers[argv[3]]
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr("tforklib.terminal._run", run)
    monkeypatch.setattr("tforklib.terminal.time.sleep", lambda _: None)
    monkeypatch.setattr("tforklib.orchestrate.observe_fork", lambda *_: Observation(start_sentinel_seen=True, end_sentinel_seen=False, exit_status=None, foreground="agent", pane_text="", readable=True))
    monkeypatch.setattr("tforklib.orchestrate.read_registry", lambda *_: {})
    monkeypatch.setattr("tforklib.orchestrate.write_registry_entry", lambda *_: None)
    def launch(index):
        result = run_fork(["echo", str(index)], workspace="feature", window="window:2", workspace_mode="create", terminal=terminal, cwd=str(tmp_path))
        return index, result
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(launch, range(2)))
    assert {result["workspace"]["title"] for _, result in results} == {"feature", "feature_2"}
    for index, result in results:
        assert delivered[result["session"]] == f"echo {index}"
        assert result["session"] == result["workspace"]["ref"].replace("workspace:", "surface:")
