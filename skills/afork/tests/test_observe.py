"""Opt-in observability: --observe wraps the built launch command with agentlens
(`lens run`) and carries attribution through AGENTLENS_TAGS.

`lens` is deliberately never assumed present — every test pins shutil.which, so
the suite behaves the same on a machine with agentlens installed and one without.
"""

import json
from pathlib import Path

import pytest

from aforklib import run_afork
from aforklib.cli import main
from aforklib.errors import EXIT_CODES, AforkError


@pytest.fixture
def lens_on_path(monkeypatch):
    monkeypatch.setattr("aforklib.shutil.which",
                        lambda name: "/usr/local/bin/lens" if name == "lens" else None)


@pytest.fixture
def no_lens_on_path(monkeypatch):
    monkeypatch.setattr("aforklib.shutil.which", lambda name: None)


def _codex_port(tmp_path, name, body):
    d = tmp_path / ".codex" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.toml").write_text(body)


# --- Plain agents: flat shlex-joined argv ---

def test_plain_with_tags_wraps_with_env_prefix(tmp_path, lens_on_path):
    out = run_afork("claude", cwd=str(tmp_path), observe=True,
                    obs_tags=["agent=reviewer", "run=42"])

    assert out["command"].startswith(
        "env AGENTLENS_TAGS=agent=reviewer,run=42 lens run -- claude ")
    # The runtime argv is preserved verbatim after the `--` separator.
    assert "--dangerously-skip-permissions" in out["command"]
    assert "--model opus" in out["command"]
    # Still a flat single-line command the calling agent can hand to tfork.
    assert "\n" not in out["command"]


def test_plain_without_tags_omits_env_prefix(tmp_path, lens_on_path):
    out = run_afork("codex", cwd=str(tmp_path), observe=True)

    assert out["command"].startswith("lens run -- codex ")
    assert "AGENTLENS_TAGS" not in out["command"]
    assert out["observed"] is True
    assert out["obs_tags"] is None


def test_tag_order_preserved_and_last_duplicate_wins(tmp_path, lens_on_path):
    out = run_afork("codex", cwd=str(tmp_path), observe=True,
                    obs_tags=["run=1", "agent=rev", "run=2"])

    assert out["command"].startswith("env AGENTLENS_TAGS=run=2,agent=rev lens run -- ")
    assert out["obs_tags"] == {"run": "2", "agent": "rev"}


# --- Custom agents: generated bash launcher ---

def test_launcher_exports_tags_and_execs_through_lens(tmp_path, lens_on_path):
    _codex_port(tmp_path, "reviewer",
                'sandbox_mode = "read-only"\ndeveloper_instructions = "be sharp"\n')

    out = run_afork("codex", "reviewer", cwd=str(tmp_path), observe=True,
                    obs_tags=["agent=reviewer", "stage=review"])

    launcher = (Path(out["workdir"]) / "launch.sh").read_text()
    assert "export AGENTLENS_TAGS=agent=reviewer,stage=review" in launcher
    assert "exec lens run -- codex " in launcher
    # The posture flag and persona injection survive the wrap untouched.
    assert "--sandbox read-only" in launcher
    assert 'developer_instructions="$(cat "$DIR/persona.txt")"' in launcher
    assert out["observed"] is True


def test_launcher_without_tags_execs_through_lens_and_exports_nothing(
        tmp_path, lens_on_path):
    _codex_port(tmp_path, "reviewer",
                'sandbox_mode = "read-only"\ndeveloper_instructions = "x"\n')

    out = run_afork("codex", "reviewer", cwd=str(tmp_path), observe=True)

    launcher = (Path(out["workdir"]) / "launch.sh").read_text()
    assert "AGENTLENS_TAGS" not in launcher
    assert "exec lens run -- codex " in launcher


# --- Fail-open: no `lens` on PATH ---

def test_missing_lens_builds_unwrapped_command_and_warns(tmp_path, no_lens_on_path):
    out = run_afork("claude", cwd=str(tmp_path), observe=True,
                    obs_tags=["agent=reviewer"])

    # Fail-OPEN: the launch is still prepared, just without observability.
    assert out["ok"] is True
    assert out["command"].startswith("claude ")
    assert "lens" not in out["command"]
    assert "AGENTLENS_TAGS" not in out["command"]
    assert out["observed"] is False
    assert out["obs_warning"]
    assert "lens" in out["obs_warning"]
    # The requested attribution is still echoed; `observed` is the authority on
    # whether it was applied.
    assert out["obs_tags"] == {"agent": "reviewer"}


def test_missing_lens_leaves_launcher_unwrapped(tmp_path, no_lens_on_path):
    _codex_port(tmp_path, "reviewer",
                'sandbox_mode = "read-only"\ndeveloper_instructions = "x"\n')

    out = run_afork("codex", "reviewer", cwd=str(tmp_path), observe=True,
                    obs_tags=["agent=reviewer"])

    launcher = (Path(out["workdir"]) / "launch.sh").read_text()
    assert "lens run" not in launcher
    assert "AGENTLENS_TAGS" not in launcher
    assert launcher.count("exec codex ") == 1
    assert out["observed"] is False


# --- Argument errors ---

def test_obs_tag_without_observe_is_bad_arguments(tmp_path):
    with pytest.raises(AforkError) as exc:
        run_afork("codex", cwd=str(tmp_path), obs_tags=["agent=reviewer"])
    assert exc.value.code == "bad_arguments"


def test_malformed_obs_tag_is_bad_arguments(tmp_path, lens_on_path):
    with pytest.raises(AforkError) as exc:
        run_afork("codex", cwd=str(tmp_path), observe=True, obs_tags=["agent"])
    assert exc.value.code == "bad_arguments"


def test_comma_in_obs_tag_is_bad_arguments(tmp_path, lens_on_path):
    # AGENTLENS_TAGS is comma-separated; a comma would silently split one tag.
    with pytest.raises(AforkError) as exc:
        run_afork("codex", cwd=str(tmp_path), observe=True,
                  obs_tags=["agent=rev,run=42"])
    assert exc.value.code == "bad_arguments"


# --- Handoff JSON / CLI contract ---

def test_cli_observe_handoff_fields(tmp_path, capsys, lens_on_path):
    rc = main(["codex", "--cwd", str(tmp_path), "--observe",
               "--obs-tag", "agent=reviewer", "--obs-tag", "run=42"])
    out = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert out["observed"] is True
    assert out["obs_tags"] == {"agent": "reviewer", "run": "42"}
    assert "obs_warning" not in out
    assert out["command"].startswith("env AGENTLENS_TAGS=agent=reviewer,run=42 lens run -- ")


def test_cli_obs_tag_without_observe_exits_bad_arguments(tmp_path, capsys):
    rc = main(["codex", "--cwd", str(tmp_path), "--obs-tag", "agent=reviewer"])
    out = json.loads(capsys.readouterr().out)

    assert out["ok"] is False
    assert out["code"] == "bad_arguments"
    assert rc == EXIT_CODES["bad_arguments"]


def test_no_observe_omits_every_obs_field(tmp_path, capsys, lens_on_path):
    # Existing consumers must not see new keys when --observe is absent — even on
    # a machine where `lens` IS installed.
    main(["codex", "--cwd", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)

    assert "observed" not in out
    assert "obs_tags" not in out
    assert "obs_warning" not in out
    assert out["command"].startswith("codex ")
    assert "lens" not in out["command"]
