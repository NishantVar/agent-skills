"""FLUX_ROLE_ID stamp: every launch for a role carries the role name in the
launched session's environment — the port name for a port launch, the --role
name for a portless one. Its reader is the session's start step, so it must
never ride in the persona.

These tests drive the real CLI and then EXECUTE the returned command against a
stub runtime that records the environment it was started with. A launch that
loses the stamp fails here.
"""

import json
import subprocess
from pathlib import Path

import pytest

from aforklib.cli import main
from aforklib.errors import EXIT_CODES

UNSET = "<unset>"


@pytest.fixture
def stub_bin(tmp_path):
    """A PATH dir whose runtimes write FLUX_ROLE_ID (and AGENTLENS_TAGS) to
    $OUT, and whose `lens` just execs what follows `run --`."""
    d = tmp_path / "bin"
    d.mkdir()
    recorder = ('#!/usr/bin/env bash\n'
                'printf "%s\\n%s\\n" "${FLUX_ROLE_ID-' + UNSET + '}" '
                '"${AGENTLENS_TAGS-' + UNSET + '}" > "$OUT"\n')
    for runtime in ("claude", "codex"):
        (d / runtime).write_text(recorder)
        (d / runtime).chmod(0o755)
    (d / "lens").write_text('#!/usr/bin/env bash\nshift 2\nexec "$@"\n')
    (d / "lens").chmod(0o755)
    return d


def _port(tmp_path, runtime, name):
    d = tmp_path / f".{runtime}" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    if runtime == "codex":
        (d / f"{name}.toml").write_text('developer_instructions = "charter"\n')
    else:
        (d / f"{name}.md").write_text(f"---\nname: {name}\n---\n\ncharter\n")


def _afork(argv, capsys):
    rc = main(argv)
    return rc, json.loads(capsys.readouterr().out)


def _launched_env(out, tmp_path, stub_bin, inherited=None):
    """Run the handoff command as tfork would and return what the runtime saw:
    (FLUX_ROLE_ID, AGENTLENS_TAGS). ``inherited`` is a FLUX_ROLE_ID already in
    the caller's environment."""
    record = tmp_path / "launched-env"
    env = {"PATH": f"{stub_bin}:/usr/bin:/bin", "OUT": str(record)}
    if inherited is not None:
        env["FLUX_ROLE_ID"] = inherited
    result = subprocess.run(out["command"], shell=True, env=env,
                            cwd=str(tmp_path), capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
    role_id, tags = record.read_text().splitlines()
    return role_id, tags


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_port_launch_stamps_port_name(tmp_path, capsys, stub_bin, runtime):
    _port(tmp_path, runtime, "runtime-integration-engineer")
    rc, out = _afork([runtime, "runtime-integration-engineer",
                      "--cwd", str(tmp_path)], capsys)
    assert rc == 0
    role_id, _ = _launched_env(out, tmp_path, stub_bin)
    assert role_id == "runtime-integration-engineer"


def test_bridged_legacy_name_stamps_canonical_port_name(tmp_path, capsys,
                                                        stub_bin):
    _port(tmp_path, "claude", "reviewer")
    rc, out = _afork(["claude", "reviewer-agent", "--cwd", str(tmp_path)],
                     capsys)
    assert rc == 0 and out["agent"] == "reviewer"
    assert _launched_env(out, tmp_path, stub_bin)[0] == "reviewer"


def test_port_launch_under_observe_keeps_stamp(tmp_path, capsys, stub_bin,
                                               monkeypatch):
    monkeypatch.setattr("aforklib.shutil.which",
                        lambda name: str(stub_bin / name))
    _port(tmp_path, "codex", "reviewer")
    rc, out = _afork(["codex", "reviewer", "--cwd", str(tmp_path),
                      "--observe", "--obs-tag", "run=7"], capsys)
    assert rc == 0 and out["observed"] is True
    assert _launched_env(out, tmp_path, stub_bin) == ("reviewer", "run=7")


def test_stamp_is_environment_not_persona(tmp_path, capsys):
    _port(tmp_path, "claude", "reviewer")
    _, out = _afork(["claude", "reviewer", "--cwd", str(tmp_path)], capsys)
    persona = (Path(out["workdir"]) / "persona.txt").read_text()
    assert "FLUX_ROLE_ID" not in persona
    launcher = (Path(out["workdir"]) / "launch.sh").read_text()
    assert "export FLUX_ROLE_ID=reviewer\n" in launcher


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_role_option_stamps_named_role(tmp_path, capsys, stub_bin, runtime):
    rc, out = _afork([runtime, "--role", "flux-conductor",
                      "--cwd", str(tmp_path)], capsys)
    assert rc == 0
    assert out["agent"] is None
    assert out["title"] == "flux-conductor"
    assert _launched_env(out, tmp_path, stub_bin)[0] == "flux-conductor"


def test_role_option_under_observe_carries_both_vars(tmp_path, capsys,
                                                     stub_bin, monkeypatch):
    monkeypatch.setattr("aforklib.shutil.which",
                        lambda name: str(stub_bin / name))
    rc, out = _afork(["claude", "--role", "griller", "--cwd", str(tmp_path),
                      "--observe", "--obs-tag", "agent=griller"], capsys)
    assert rc == 0
    assert out["command"].startswith(
        "env AGENTLENS_TAGS=agent=griller FLUX_ROLE_ID=griller lens run -- ")
    assert _launched_env(out, tmp_path, stub_bin) == ("griller",
                                                      "agent=griller")


def test_plain_launch_without_role_is_unstamped(tmp_path, capsys, stub_bin):
    rc, out = _afork(["claude", "--cwd", str(tmp_path)], capsys)
    assert rc == 0
    assert out["command"].startswith("env -u FLUX_ROLE_ID claude ")
    assert _launched_env(out, tmp_path, stub_bin)[0] == UNSET


# --- A caller that is itself a named session (FLUX_ROLE_ID=reviewer) ---

@pytest.fixture
def observe_flags(request, stub_bin, monkeypatch):
    """Parametrized by observe on/off; returns the extra CLI flags."""
    if not request.param:
        return []
    monkeypatch.setattr("aforklib.shutil.which",
                        lambda name: str(stub_bin / name))
    return ["--observe"]


@pytest.mark.parametrize("observe_flags", [False, True], indirect=True,
                         ids=["unobserved", "observed"])
@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_unnamed_launch_clears_inherited_role(tmp_path, capsys, stub_bin,
                                              runtime, observe_flags):
    rc, out = _afork([runtime, "--cwd", str(tmp_path)] + observe_flags, capsys)
    assert rc == 0
    role_id, _ = _launched_env(out, tmp_path, stub_bin, inherited="reviewer")
    assert role_id == UNSET


def test_unnamed_launcher_shape_clears_inherited_role(tmp_path, stub_bin):
    """An unnamed launch with a persona (direct build_launch caller) still
    unsets the inherited name before exec."""
    from aforklib.adapters import ClaudeAdapter
    from aforklib.launch import build_launch
    command, workdir, _, _ = build_launch(
        ClaudeAdapter(), None, "none", None, None, "persona",
        root=str(tmp_path / "w"))
    assert "unset FLUX_ROLE_ID\n" in (Path(workdir) / "launch.sh").read_text()
    out = {"command": command}
    assert _launched_env(out, tmp_path, stub_bin, inherited="reviewer")[0] == UNSET


@pytest.mark.parametrize("observe_flags", [False, True], indirect=True,
                         ids=["unobserved", "observed"])
@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_port_launch_overrides_inherited_role(tmp_path, capsys, stub_bin,
                                              runtime, observe_flags):
    _port(tmp_path, runtime, "runtime-integration-engineer")
    rc, out = _afork([runtime, "runtime-integration-engineer",
                      "--cwd", str(tmp_path)] + observe_flags, capsys)
    assert rc == 0
    role_id, _ = _launched_env(out, tmp_path, stub_bin, inherited="reviewer")
    assert role_id == "runtime-integration-engineer"


@pytest.mark.parametrize("observe_flags", [False, True], indirect=True,
                         ids=["unobserved", "observed"])
@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_role_option_overrides_inherited_role(tmp_path, capsys, stub_bin,
                                              runtime, observe_flags):
    rc, out = _afork([runtime, "--role", "griller", "--cwd", str(tmp_path)]
                     + observe_flags, capsys)
    assert rc == 0
    role_id, _ = _launched_env(out, tmp_path, stub_bin, inherited="reviewer")
    assert role_id == "griller"


def test_role_option_with_agent_is_bad_arguments(tmp_path, capsys):
    _port(tmp_path, "codex", "reviewer")
    rc, out = _afork(["codex", "reviewer", "--role", "griller",
                      "--cwd", str(tmp_path)], capsys)
    assert rc == EXIT_CODES["bad_arguments"]
    assert out["code"] == "bad_arguments"


@pytest.mark.parametrize("bad", [".hidden", "two words", "a/b", "", "x;y"])
def test_role_option_refuses_names_breaking_the_name_rule(tmp_path, capsys,
                                                          bad):
    rc, out = _afork(["claude", "--role", bad, "--cwd", str(tmp_path)], capsys)
    assert rc == EXIT_CODES["bad_arguments"]
    assert out["code"] == "bad_arguments"
