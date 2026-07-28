"""The launch_outcome as it actually reaches a caller: through ``run_fork``,
through the CLI's JSON, and through the failure handoffs.

``test_launch_outcome`` pins the derivation. This pins the plumbing — that the
object is built from the SAME pane snapshot the human-facing note is built
from, that the sidecar path survives the CLI, and that the three failures where
a launch was mechanically attempted carry an outcome while the rest do not.
"""

import json
import time

import pytest

import tforklib as ft
from fake_terminal import FakeTerminal, make_scrollback

NONCE = "abc123"
ATTEMPT = "deadbeefcafe0001"
MARKER = f"__afork_exec_failed_{ATTEMPT}__"


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)


@pytest.fixture
def reg(tmp_path):
    return tmp_path / "registry.toml"


@pytest.fixture
def contract(tmp_path):
    path = tmp_path / "launch-contract.json"
    path.write_text(json.dumps({
        "version": 1,
        "attempt_id": ATTEMPT,
        "runtime": "codex",
        "agent": "reviewer",
        "model": "gpt-5",
        "effort": "high",
        "exec_marker": MARKER,
        "signatures": {
            "model_rejected": [r"(?i)\bunknown model\b"],
            "runtime_launch_error": [r"(?im)^codex:\s"],
        },
    }))
    return str(path)


def test_running_agent_reports_started(reg, contract):
    term = FakeTerminal(process="codex", text=make_scrollback(NONCE))
    result = ft.run_fork(["codex"], terminal=term, nonce=NONCE,
                         registry_path=reg, launch_contract=contract)

    assert result["launch_outcome"]["state"] == "started"
    assert result["launch_outcome"]["evidence_code"] == "agent_started"
    assert result["launch_outcome"]["foreground"] == "codex"


def test_missing_runtime_reports_a_trusted_prework_failure(reg, contract):
    term = FakeTerminal(
        process="zsh",
        text=make_scrollback(NONCE, exit_status=127,
                             body=f"launch.sh: codex: not found\n{MARKER}"))
    result = ft.run_fork(["codex"], terminal=term, nonce=NONCE,
                         registry_path=reg, launch_contract=contract)

    outcome = result["launch_outcome"]
    assert outcome["state"] == "prework_failure"
    assert outcome["reason_code"] == "runtime_unavailable"
    # The human-facing reading is unchanged and still independent.
    assert result["verified"] is False
    assert "exited with status 127" in result["note"]


def test_the_same_fork_without_a_contract_degrades_to_unknown(reg):
    """No --launch-contract: identical pane, no trusted classification."""
    term = FakeTerminal(
        process="zsh",
        text=make_scrollback(NONCE, exit_status=127,
                             body=f"launch.sh: codex: not found\n{MARKER}"))
    result = ft.run_fork(["codex"], terminal=term, nonce=NONCE,
                         registry_path=reg)

    assert result["launch_outcome"]["state"] == "unknown"
    assert result["launch_outcome"]["reason_code"] is None


def test_an_unreadable_contract_path_is_not_fatal(reg, tmp_path):
    term = FakeTerminal(process="codex", text=make_scrollback(NONCE))
    result = ft.run_fork(["codex"], terminal=term, nonce=NONCE,
                         registry_path=reg,
                         launch_contract=str(tmp_path / "gone.json"))

    assert result["ok"] is True
    assert result["launch_outcome"]["state"] == "started"


def test_outcome_and_note_read_one_snapshot(reg, contract):
    """The pane is read exactly once. Two reads could disagree — the agent
    could exit between them — and the two readings would then contradict."""
    term = FakeTerminal(process="codex", text=make_scrollback(NONCE))
    ft.run_fork(["codex"], terminal=term, nonce=NONCE, registry_path=reg,
                launch_contract=contract)

    assert term.methods_called().count("pane_text") == 1
    assert term.methods_called().count("pane_process") == 1


def test_outcome_facts_agree_with_the_reported_fields(reg, contract):
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=3))
    result = ft.run_fork(["thing"], terminal=term, nonce=NONCE,
                         registry_path=reg, launch_contract=contract)

    assert result["launch_outcome"]["exit_status"] == result["exit_status"]
    assert result["launch_outcome"]["foreground"] == result["foreground"]


# --- the CLI ----------------------------------------------------------------

def test_cli_accepts_and_forwards_the_contract_path():
    args = ft.parse_args(["--launch-contract", "/tmp/lc.json", "--", "codex"])
    assert args.launch_contract == "/tmp/lc.json"


def test_cli_contract_flag_is_optional():
    assert ft.parse_args(["--", "codex"]).launch_contract is None


def test_cli_success_json_carries_the_outcome(monkeypatch, capsys, reg,
                                              contract):
    term = FakeTerminal(process="codex", text=make_scrollback(NONCE))
    monkeypatch.setattr(ft.cli, "run_fork",
                        lambda *a, **kw: ft.run_fork(
                            *a, terminal=term, nonce=NONCE,
                            registry_path=reg, **kw))

    assert ft.main(["--launch-contract", contract, "--", "codex"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["launch_outcome"]["state"] == "started"


# --- failure handoffs -------------------------------------------------------

def test_pane_creation_failures_carry_a_trusted_outcome():
    for err in (ft.err_split_failed("cmux exploded"),
                ft.err_window_create_failed("no display")):
        outcome = err.handoff()["launch_outcome"]
        assert outcome["state"] == "prework_failure"
        assert outcome["evidence_code"] == "pane_creation_failed"
        assert outcome["reason_code"] == "launch_failed"


def test_delivery_failures_split_on_whether_anything_could_have_run():
    absent = ft.err_spawn_failed("set-buffer failed").handoff()
    assert absent["launch_outcome"]["state"] == "prework_failure"
    assert absent["retryable"] is True

    ambiguous = ft.err_spawn_failed("send-key failed",
                                    delivery="ambiguous").handoff()
    assert ambiguous["launch_outcome"]["state"] == "unknown"
    assert ambiguous["launch_outcome"]["evidence_code"] == "delivery_ambiguous"
    # A possible side effect is not retryable — blind retry is how you end up
    # with two agents.
    assert ambiguous["retryable"] is False


def test_pre_launch_and_caller_error_handoffs_carry_no_outcome():
    """These never attempted a launch. Reporting them as prework_failure would
    invite a dispatcher to retry on a second runtime that fails identically."""
    for err in (ft.err_no_terminal(),
                ft.err_surface_resolution_failed(),
                ft.err_bad_arguments("no command"),
                ft.err_anchor_not_found("ghost"),
                ft.err_workspace_unknown("nope"),
                ft.err_window_unknown("nope"),
                ft.err_workspace_anchor_conflict(),
                ft.err_window_anchor_conflict()):
        assert "launch_outcome" not in err.handoff(), err.code


# --- the delivery split at its source ---------------------------------------

def _spawn_with_failing(monkeypatch, failing_verb):
    """Drive ``CmuxTerminal._spawn`` with one cmux verb scripted to fail."""
    import subprocess

    from tforklib import terminal as term_mod

    def fake_run(cmd, *a, **k):
        rc = 1 if cmd[1] == failing_verb else 0
        return subprocess.CompletedProcess(cmd, rc, "", "boom" if rc else "")

    monkeypatch.setattr(term_mod, "_run", fake_run)
    monkeypatch.setattr(term_mod, "_workspace_of", lambda _s: None)
    with pytest.raises(ft.ForkError) as exc:
        term_mod.CmuxTerminal()._spawn("surface:9", "echo hi")
    assert exc.value.code == "spawn_failed"
    return exc.value.handoff()["launch_outcome"]


def test_a_failed_paste_is_a_trusted_delivery_failure(monkeypatch):
    """Enter is never sent after a failed paste, so nothing could have run."""
    outcome = _spawn_with_failing(monkeypatch, "paste-buffer")
    assert outcome["state"] == "prework_failure"
    assert outcome["evidence_code"] == "command_delivery_absent"


def test_a_failed_enter_is_ambiguous(monkeypatch):
    """The line was already in the pane; only the Enter reported failure."""
    outcome = _spawn_with_failing(monkeypatch, "send-key")
    assert outcome["state"] == "unknown"
    assert outcome["evidence_code"] == "delivery_ambiguous"
