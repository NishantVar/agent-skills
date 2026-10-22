"""A create-mode launch that fails before its command could run closes the
workspace it created and gives back the creation claim it consumed.

Anything that might have run — an ambiguous delivery or any success — is never
closed and never released, and a workspace tfork reused is never closed.
"""
import json
import os
import subprocess
from unittest.mock import Mock

import pytest

from tforklib.creation_claim import consume_creation_claim, release_creation_claim
from tforklib.errors import ForkError, err_spawn_failed, err_split_failed
from tforklib.orchestrate import run_fork
from tforklib.outcome import DELIVERY_AMBIGUOUS
from tforklib.terminal import CmuxTerminal
from fake_terminal import FakeTerminal, make_scrollback

OWNER = "dispatch-1"
CREATED = ({"ref": "window:2", "created": False},
           {"ref": "workspace:20", "title": "feature", "created": True})


def intent(path, **overrides):
    value = {"dispatch_id": OWNER, "record": None, "creation_started": False}
    value.update(overrides)
    path.write_text(json.dumps(value))
    return path


def creating(terminal):
    terminal.create_named_workspace = Mock(return_value=CREATED)
    return terminal


def launch(terminal, claim, tmp_path, **kwargs):
    return run_fork(["agent"], workspace="feature", window="window:2",
                    workspace_mode="create", workspace_claim=claim,
                    workspace_claim_id=OWNER, terminal=terminal,
                    registry_path=tmp_path / "registry", delay=0, **kwargs)


def failed_launch(terminal, claim, tmp_path):
    with pytest.raises(ForkError) as raised:
        launch(terminal, claim, tmp_path)
    return raised.value.handoff()


@pytest.mark.parametrize("error", [
    err_spawn_failed("Buffer not found"),
    err_split_failed("cmux new-pane failed"),
], ids=["delivery_absent", "pane_creation_failed"])
def test_undelivered_failure_closes_workspace_and_releases_claim(tmp_path, error):
    claim = intent(tmp_path / "claim.json")
    terminal = creating(FakeTerminal(fork_error=error))
    handoff = failed_launch(terminal, claim, tmp_path)

    assert terminal.closed_workspaces == ["workspace:20"]
    assert ("close_workspace", "workspace:20", "window:2") in terminal.calls
    assert json.loads(claim.read_text()) == {
        "dispatch_id": OWNER, "record": None, "creation_started": False}
    assert handoff["workspace_cleanup"] == {
        "ref": "workspace:20", "title": "feature", "closed": True,
        "claim_released": True, "detail": None}
    assert handoff["launch_outcome"]["state"] == "prework_failure"
    assert handoff["retryable"] is True
    assert "The created pane has been closed" not in handoff["human_message"]
    assert "closed the workspace it created" in handoff["human_message"]
    assert "released its creation claim" in handoff["human_message"]

    # The same invocation can now be retried and creates afresh.
    retry = creating(FakeTerminal(process="agent", text=make_scrollback("n1")))
    result = launch(retry, claim, tmp_path, nonce="n1")
    assert result["ok"] is True
    assert json.loads(claim.read_text())["creation_started"] is True


def test_close_failure_keeps_claim_and_reports_leftover(tmp_path):
    claim = intent(tmp_path / "claim.json")
    terminal = creating(FakeTerminal(fork_error=err_spawn_failed("Buffer not found"),
                                     close_error="workspace busy"))
    handoff = failed_launch(terminal, claim, tmp_path)

    assert json.loads(claim.read_text())["creation_started"] is True
    assert handoff["workspace_cleanup"] == {
        "ref": "workspace:20", "title": "feature", "closed": False,
        "claim_released": False, "detail": "workspace busy"}
    assert handoff["workspace"]["ref"] == "workspace:20"
    assert "'feature' (workspace:20)" in handoff["human_message"]
    assert "left behind" in handoff["human_message"]
    assert "workspace:20" in handoff["agent_instruction"]
    assert handoff["retryable"] is False
    assert handoff["launch_outcome"]["state"] == "prework_failure"
    with pytest.raises(ForkError, match="claim refused"):
        launch(creating(FakeTerminal()), claim, tmp_path)


def test_ambiguous_delivery_neither_closes_nor_releases(tmp_path):
    claim = intent(tmp_path / "claim.json")
    terminal = creating(FakeTerminal(
        fork_error=err_spawn_failed("send-key failed", delivery=DELIVERY_AMBIGUOUS)))
    handoff = failed_launch(terminal, claim, tmp_path)

    assert "close_workspace" not in terminal.methods_called()
    assert json.loads(claim.read_text())["creation_started"] is True
    assert "workspace_cleanup" not in handoff
    assert handoff["launch_outcome"]["state"] == "unknown"


def test_unknown_success_neither_closes_nor_releases(tmp_path):
    claim = intent(tmp_path / "claim.json")
    terminal = creating(FakeTerminal(process="zsh", text=""))
    result = launch(terminal, claim, tmp_path)

    assert result["launch_outcome"]["state"] == "unknown"
    assert "close_workspace" not in terminal.methods_called()
    assert json.loads(claim.read_text())["creation_started"] is True


def test_replaced_claim_is_left_untouched(tmp_path):
    claim = intent(tmp_path / "claim.json")
    replacement = {"dispatch_id": OWNER, "record": None, "creation_started": True}
    terminal = creating(FakeTerminal())

    def fork_after_dispatcher_replaced_claim(*_args, **_kwargs):
        # Identical content, new inode: still not the claim this call consumed.
        staged = tmp_path / "staged.json"
        staged.write_text(json.dumps(replacement))
        os.replace(staged, claim)
        raise err_spawn_failed("Buffer not found")

    terminal.fork = fork_after_dispatcher_replaced_claim
    handoff = failed_launch(terminal, claim, tmp_path)

    assert terminal.closed_workspaces == ["workspace:20"]
    assert json.loads(claim.read_text()) == replacement
    assert handoff["workspace_cleanup"]["closed"] is True
    assert handoff["workspace_cleanup"]["claim_released"] is False
    assert handoff["workspace_cleanup"]["detail"] == "claim was removed or replaced"
    assert handoff["retryable"] is False


@pytest.mark.parametrize("created", [False, True], ids=["reused", "created_in_reuse_mode"])
def test_reused_workspace_is_never_closed(tmp_path, created):
    terminal = FakeTerminal(
        fork_error=err_spawn_failed("Buffer not found"),
        workspace_resolver=lambda value, cwd: {
            "ref": "workspace:7", "title": value, "created": created})
    with pytest.raises(ForkError) as raised:
        run_fork(["agent"], workspace="shared", terminal=terminal,
                 registry_path=tmp_path / "registry")
    assert "close_workspace" not in terminal.methods_called()
    assert "workspace_cleanup" not in raised.value.handoff()


def test_naming_failure_closes_created_workspace_and_releases_claim(tmp_path):
    claim = intent(tmp_path / "claim.json")
    terminal = FakeTerminal()
    terminal.create_named_workspace = Mock(side_effect=ForkError(
        "workspace_naming_failed", "Created workspace could not acquire a unique feature name; no command delivered.",
        "Report the actual created refs for reconciliation; do not retry the runtime launch.", False, None,
        {"workspace": {"ref": "workspace:31", "title": "Default", "created": True},
         "window": {"ref": "window:2", "created": False}}))
    handoff = failed_launch(terminal, claim, tmp_path)

    assert terminal.closed_workspaces == ["workspace:31"]
    assert json.loads(claim.read_text())["creation_started"] is False
    assert handoff["workspace_cleanup"]["claim_released"] is True
    assert "reconciliation" not in handoff["agent_instruction"]
    assert handoff["retryable"] is False
    assert "can be retried" not in handoff["human_message"]
    assert not any(call[0] == "fork" for call in terminal.calls)


def test_release_refuses_anything_but_this_calls_started_claim(tmp_path):
    claim = intent(tmp_path / "claim.json")
    identity = consume_creation_claim(claim, OWNER)
    for content in ({"dispatch_id": "other", "record": None, "creation_started": True},
                    {"dispatch_id": OWNER, "record": {"ref": "workspace:20"}, "creation_started": True},
                    {"dispatch_id": OWNER, "record": None, "creation_started": False},
                    {"dispatch_id": OWNER, "record": None, "creation_started": True, "extra": 1}):
        with open(claim, "r+", encoding="utf-8") as stream:  # same inode
            stream.write(json.dumps(content))
            stream.truncate()
        assert release_creation_claim(claim, OWNER, identity) is not None
        assert json.loads(claim.read_text()) == content
    link = tmp_path / "link.json"
    link.symlink_to(claim)
    assert release_creation_claim(link, OWNER, identity) is not None
    assert release_creation_claim(tmp_path / "gone.json", OWNER, identity) is not None


def test_cmux_close_workspace(monkeypatch):
    calls = []
    outcomes = iter([0, 1, 1, 1])
    trees = iter([
        {"windows": [{"workspaces": [{"ref": "workspace:20"}]}]},  # still there
        {"windows": [{"workspaces": [{"ref": "workspace:21"}]}]},  # already gone
        {},                                                        # unreadable
    ])

    def run(argv):
        calls.append(argv)
        code = next(outcomes)
        return subprocess.CompletedProcess(argv, code, "", "boom" if code else "")

    monkeypatch.setattr("tforklib.terminal._run", run)
    monkeypatch.setattr("tforklib.terminal._cmux_tree", lambda: next(trees))
    terminal = CmuxTerminal()
    assert terminal.close_workspace("workspace:20", "window:2") is None
    assert calls[0] == ["cmux", "close-workspace", "--workspace", "workspace:20",
                        "--window", "window:2"]
    assert terminal.close_workspace("workspace:20") == "boom"
    assert calls[1] == ["cmux", "close-workspace", "--workspace", "workspace:20"]
    assert terminal.close_workspace("workspace:20") is None
    assert terminal.close_workspace("workspace:20") == "boom"
