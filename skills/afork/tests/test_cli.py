"""CLI contract: one JSON object on stdout, exit code reflects the outcome.
Runtime is positional-1; agent is an optional positional-2."""

import json

from aforklib.cli import main
from aforklib.errors import EXIT_CODES


def _codex_port(tmp_path, name, body):
    d = tmp_path / ".codex" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.toml").write_text(body)


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
