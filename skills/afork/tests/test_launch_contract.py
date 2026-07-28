"""afork's half of the launch contract: the 0600 sidecar and the exec-once
launcher.

afork is the side that knows what runtime it asked for, so it is the side that
writes down what a failure of that runtime looks like. tfork never learns any
of it — it only matches what afork recorded.
"""

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from aforklib import run_afork
from aforklib.adapters import ClaudeAdapter, CodexAdapter, PiAdapter
from aforklib.launch import build_launch
from aforklib.outcome import SIGNATURE_KINDS, exec_marker, load_sidecar


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


def _claude_port(tmp_path, name, body):
    d = tmp_path / ".claude" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(body)


# --- the sidecar ------------------------------------------------------------

def test_sidecar_is_written_0600_with_the_attempt_facts(tmp_path):
    launch = build_launch(CodexAdapter(), "reviewer", "read-only", "gpt-5",
                          "high", "PERSONA", root=str(tmp_path / "w"))
    path = Path(launch.launch_contract)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    sidecar = json.loads(path.read_text())
    assert sidecar["version"] == 1
    assert sidecar["attempt_id"] == launch.attempt_id
    assert sidecar["runtime"] == "codex"
    assert sidecar["agent"] == "reviewer"
    assert sidecar["model"] == "gpt-5"
    assert sidecar["effort"] == "high"
    assert sidecar["exec_marker"] == exec_marker(launch.attempt_id)


def test_every_adapter_declares_both_signature_kinds(tmp_path):
    """Signature ownership sits with the adapter. tfork holds no runtime table,
    so an adapter that declared nothing would make its runtime unclassifiable."""
    for adapter in (CodexAdapter(), ClaudeAdapter(), PiAdapter()):
        launch = build_launch(adapter, "a", "none", None, None, "P",
                              root=str(tmp_path / adapter.runtime))
        signatures = json.loads(Path(launch.launch_contract).read_text())[
            "signatures"]
        assert set(signatures) == set(SIGNATURE_KINDS)
        for kind in SIGNATURE_KINDS:
            assert signatures[kind], f"{adapter.runtime}/{kind} is empty"


def test_attempt_ids_are_unique_per_launch(tmp_path):
    a = build_launch(CodexAdapter(), "x", "none", None, None, "P",
                     root=str(tmp_path / "a"))
    b = build_launch(CodexAdapter(), "x", "none", None, None, "P",
                     root=str(tmp_path / "b"))
    assert a.attempt_id != b.attempt_id
    assert exec_marker(a.attempt_id) not in Path(b.launch_contract).read_text()


def test_plain_launch_has_a_sidecar_but_no_exec_marker(tmp_path):
    """No generated launcher means nothing can ever print the marker. Recording
    a marker anyway would let unrelated pane text be read as a trusted exec
    failure; null is the honest value."""
    launch = build_launch(CodexAdapter(), None, "none", None, "xhigh", "",
                          root=str(tmp_path / "w"))
    sidecar = json.loads(Path(launch.launch_contract).read_text())
    assert sidecar["exec_marker"] is None
    # ...but the model/launch signatures are still there, so a plain fork can
    # still be classified when the runtime rejects the model.
    assert sidecar["signatures"]["model_rejected"]


def test_sidecar_round_trips_through_load(tmp_path):
    launch = build_launch(ClaudeAdapter(), "r", "none", "opus", None, "P",
                          root=str(tmp_path / "w"))
    assert load_sidecar(launch.launch_contract)["attempt_id"] == launch.attempt_id


def test_every_adapter_writes_a_shape_the_reader_accepts(tmp_path):
    """The reader rejects a malformed version-1 file outright. An adapter that
    wrote one would produce a fork that silently never classifies — the sidecar
    would be there, and ignored."""
    for adapter in (CodexAdapter(), ClaudeAdapter(), PiAdapter()):
        for agent in ("a", None):          # custom (has a marker) and plain
            launch = build_launch(adapter, agent, "none", None, None, "P",
                                  root=str(tmp_path / adapter.runtime
                                           / str(agent)))
            assert load_sidecar(launch.launch_contract) is not None, (
                f"{adapter.runtime}/{agent} wrote a sidecar the reader rejects")


# --- the handoff ------------------------------------------------------------

def test_handoff_carries_the_contract_path_and_attempt_id(tmp_path):
    _claude_port(tmp_path, "reviewer", "# Reviewer\nbody\n")
    out = run_afork("claude", agent="reviewer", cwd=str(tmp_path))

    assert Path(out["launch_contract"]).exists()
    assert out["attempt_id"]
    # The path is in the ready-made tfork invocation the instruction dictates,
    # not only in the object — an agent that pastes those args verbatim must
    # not silently lose it.
    assert (f"--launch-contract {out['launch_contract']}"
            in out["agent_instruction"])


def test_agent_instruction_says_what_dropping_the_flag_costs(tmp_path):
    _claude_port(tmp_path, "reviewer", "# Reviewer\nbody\n")
    out = run_afork("claude", agent="reviewer", cwd=str(tmp_path))
    assert "--launch-contract" in out["agent_instruction"]
    assert "unknown" in out["agent_instruction"]


# --- the exec-once launcher -------------------------------------------------

def _run(command, tmp_path, path_dir):
    return subprocess.run(command, shell=True, capture_output=True, text=True,
                          cwd=str(tmp_path),
                          env={"PATH": f"{path_dir}:/usr/bin:/bin"})


def test_launcher_prints_the_marker_only_when_the_real_exec_fails(tmp_path):
    """The contract's one trusted runtime signal. An empty PATH dir means the
    runtime binary genuinely does not exist, so the exec fails and the line
    after it — unreachable in every other case — runs."""
    launch = build_launch(CodexAdapter(), "probe", "read-only", None, None,
                          "PERSONA", root=str(tmp_path / "w"))
    empty_bin = tmp_path / "empty"
    empty_bin.mkdir()

    proc = _run(launch.command, tmp_path, empty_bin)

    assert exec_marker(launch.attempt_id) in proc.stdout
    assert proc.returncode != 0


def test_launcher_execs_the_runtime_exactly_once(tmp_path):
    """No retry, no second runtime, no fallback inside the launcher. Whatever
    afork intended is what runs, and if it starts, the marker is unreachable
    because exec replaced the shell."""
    launch = build_launch(CodexAdapter(), "probe", "read-only", None, None,
                          "PERSONA", root=str(tmp_path / "w"))
    counter = tmp_path / "runs"
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    (stub_bin / "codex").write_text(
        "#!/usr/bin/env bash\n"
        f'echo x >> {counter}\n'
        "exit 0\n")
    (stub_bin / "codex").chmod(0o755)

    proc = _run(launch.command, tmp_path, stub_bin)

    assert counter.read_text().count("x") == 1
    assert exec_marker(launch.attempt_id) not in proc.stdout


def test_a_runtime_that_starts_then_fails_does_not_print_the_marker(tmp_path):
    """The marker means "the runtime never started", not "the runtime exited
    non-zero". Conflating the two would let an agent that crashed after doing
    real work be relaunched elsewhere."""
    launch = build_launch(CodexAdapter(), "probe", "read-only", None, None,
                          "PERSONA", root=str(tmp_path / "w"))
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    (stub_bin / "codex").write_text(
        "#!/usr/bin/env bash\necho 'boom' >&2\nexit 42\n")
    (stub_bin / "codex").chmod(0o755)

    proc = _run(launch.command, tmp_path, stub_bin)

    assert proc.returncode == 42
    assert exec_marker(launch.attempt_id) not in proc.stdout


def test_launcher_is_0700_and_the_persona_payload_0600(tmp_path):
    launch = build_launch(CodexAdapter(), "probe", "read-only", None, None,
                          "PERSONA", root=str(tmp_path / "w"))
    workdir = Path(launch.workdir)
    assert stat.S_IMODE((workdir / "launch.sh").stat().st_mode) == 0o700
    assert stat.S_IMODE((workdir / "persona.txt").stat().st_mode) == 0o600
    assert os.access(workdir / "launch.sh", os.X_OK)


# --- the shared module must not drift ---------------------------------------

def test_outcome_module_is_byte_identical_to_tforks():
    """afork and tfork ship as independent skill directories, so neither can
    import the other. The contract is duplicated on purpose — this test (and
    its twin in the tfork suite) is what keeps the duplicate honest."""
    mine = Path(__file__).resolve().parents[1] / "aforklib" / "outcome.py"
    theirs = (Path(__file__).resolve().parents[2] / "tfork" / "tforklib"
              / "outcome.py")
    if not theirs.exists():
        pytest.skip("tfork skill not checked out beside afork")
    assert mine.read_bytes() == theirs.read_bytes(), (
        "aforklib/outcome.py and tforklib/outcome.py have diverged — the two "
        "halves of the launch contract no longer agree")
