"""CLI contract: one JSON object on stdout, exit code reflects the outcome.
Runtime is positional-1; agent is an optional positional-2."""

import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from aforklib.cli import main
from aforklib.errors import EXIT_CODES


CLI = Path(__file__).resolve().parents[1] / "afork.py"


def _invoke_afork(tmp_path, *args, path=None):
    launch_root = tmp_path / "launch artifacts"
    launch_root.mkdir()
    env = {**os.environ, "TMPDIR": str(launch_root),
           "FLUX_ROLE_ID": "parent_role"}
    if path is not None:
        env["PATH"] = str(path)
    return subprocess.run(
        [sys.executable, str(CLI), *args, "--cwd", str(tmp_path)],
        env=env, capture_output=True, text=True, timeout=10)


@pytest.mark.parametrize("observed", [False, True])
def test_plain_codex_cli_preserves_launch_tokens(tmp_path, observed):
    model = 'gpt-6 "grill"'
    args = ["codex", "--model", model, "--effort", "xhigh"]
    path = None
    if observed:
        path = tmp_path / "bin"
        path.mkdir()
        lens = path / "lens"
        lens.touch(mode=0o700)
        args += ["--role", "griller", "--observe", "--obs-tag", "stage=spec review",
                 "--obs-tag", "agent=griller"]
        expected = ["env", "AGENTLENS_TAGS=stage=spec review,agent=griller",
                    "FLUX_ROLE_ID=griller", "lens", "run", "--"]
    else:
        expected = ["env", "-u", "FLUX_ROLE_ID"]
    expected += [
        "codex", "--dangerously-bypass-approvals-and-sandbox",
        "-c", 'model="gpt-6 "grill""', "-c", 'model_reasoning_effort="xhigh"',
    ]

    proc = _invoke_afork(tmp_path, *args, path=path)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["command_argv"] == expected
    assert shlex.split(out["command"]) == expected


def _codex_port(tmp_path, name, body):
    d = tmp_path / ".codex" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.toml").write_text(body)


def test_definition_cli_preserves_literal_launcher_and_attempt_contract(tmp_path):
    _codex_port(tmp_path, "reviewer",
                'sandbox_mode = "read-only"\nmodel = "gpt-6-sol"\n'
                'model_reasoning_effort = "high"\n'
                'developer_instructions = "Review this change."\n')
    proc = _invoke_afork(tmp_path, "codex", "reviewer", "--placement", "right")
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)

    launcher = Path(out["workdir"]) / "launch.sh"
    assert " " in str(launcher)
    assert out["command_argv"] == [str(launcher)]
    assert shlex.split(out["command"]) == [str(launcher)]
    sidecar = Path(out["launch_contract"])
    assert sidecar.parent == launcher.parent
    assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600
    contract = json.loads(sidecar.read_text())
    assert contract["attempt_id"] == out["attempt_id"]
    assert (contract["runtime"], contract["model"], contract["effort"]) == (
        "codex", "gpt-6-sol", "high")
    assert contract["exec_marker"]
    instruction = out["agent_instruction"]
    assert f"--launch-contract {shlex.quote(str(sidecar))}" in instruction
    assert "--placement right before the -- separator" in instruction
    assert "each command_argv entry verbatim as a separate argument" in instruction

    # Give the launcher its shell tools without any codex on PATH.
    tools = tmp_path / "launcher tools"
    tools.mkdir()
    for name in ("bash", "cat", "dirname"):
        (tools / name).symlink_to(shutil.which(name))
    failed = subprocess.run(
        out["command_argv"], env={**os.environ, "PATH": str(tools)},
        capture_output=True, text=True, timeout=10)
    assert failed.returncode == 127
    assert contract["exec_marker"] in failed.stdout.splitlines()


def test_cli_refuses_nul_in_resolved_runtime_arguments(tmp_path):
    # TOML can decode an escaped NUL even though a process cannot receive one.
    _codex_port(tmp_path, "reviewer", 'model = "gpt\\u0000model"\n')
    proc = _invoke_afork(tmp_path, "codex", "reviewer")
    out = json.loads(proc.stdout)
    assert proc.returncode == EXIT_CODES["bad_arguments"]
    assert out["ok"] is False
    assert out["code"] == "bad_arguments"
    assert "NUL" in out["human_message"]
    assert not list((tmp_path / "launch artifacts").iterdir())


def test_handoff_preserves_an_empty_adapter_argument(tmp_path, capsys, monkeypatch):
    from aforklib.adapters import CodexAdapter

    monkeypatch.setattr(CodexAdapter, "model_flag", lambda self, model: ["-c", ""])
    assert main(["codex", "--model", "test", "--cwd", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["command_argv"][5:7] == ["-c", ""]
    assert shlex.split(out["command"]) == out["command_argv"]


def test_success_prints_ready_to_fork_and_exits_zero(tmp_path, capsys):
    _codex_port(tmp_path, "reviewer",
                'sandbox_mode = "read-only"\ndeveloper_instructions = "x"\n')
    rc = main(["codex", "reviewer", "--cwd", str(tmp_path),
               "--title", "reviewer_agent"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["action"] == "ready_to_fork"
    assert out["title"] == "reviewer_agent"
    assert "--type agent" in out["agent_instruction"]


def test_plain_mode_runtime_only(tmp_path, capsys):
    # runtime-first parsing with no agent positional -> plain agent.
    rc = main(["codex", "--cwd", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["agent"] is None
    assert out["posture"] == "none"
    assert "--dangerously-bypass-approvals-and-sandbox" in out["command"]


def test_model_forwarded(tmp_path, capsys):
    main(["claude", "--cwd", str(tmp_path), "--model", "opus"])
    out = json.loads(capsys.readouterr().out)
    assert "--model opus" in out["command"]


def test_combined_model_spec_splits_into_model_and_effort(tmp_path, capsys):
    main(["claude", "--cwd", str(tmp_path), "--model", "fable max"])
    out = json.loads(capsys.readouterr().out)
    assert "--model fable" in out["command"]
    assert "--effort max" in out["command"]


def test_explicit_effort_wins_over_model_spec(tmp_path, capsys):
    main(["claude", "--cwd", str(tmp_path),
          "--model", "fable max", "--effort", "high"])
    out = json.loads(capsys.readouterr().out)
    assert "--model fable" in out["command"]
    assert "--effort high" in out["command"]
    assert "max" not in out["command"]


def test_model_with_nonspec_tail_passes_through(tmp_path, capsys):
    # Only a trailing *effort token* splits; anything else is the model.
    main(["claude", "--cwd", str(tmp_path), "--model", "claude-fable-5"])
    out = json.loads(capsys.readouterr().out)
    assert "--model claude-fable-5" in out["command"]


def test_failclosed_exit_code(tmp_path, capsys):
    # claude read-only is not enforceable this round.
    rc = main(["claude", "--permission", "read-only", "--cwd", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["code"] == "unenforceable"
    assert rc == EXIT_CODES["unenforceable"]


def test_placement_forwarded(tmp_path, capsys):
    _codex_port(tmp_path, "reviewer",
                'sandbox_mode = "read-only"\ndeveloper_instructions = "x"\n')
    main(["codex", "reviewer", "--cwd", str(tmp_path), "--placement", "right"])
    out = json.loads(capsys.readouterr().out)
    assert out["placement"] == "right"
    assert "--placement right" in out["agent_instruction"]
