"""Codex adapter: parsing, the posture -> enforceable mapping, and the launcher
the build step writes."""

import shlex
import stat
from pathlib import Path

from aforklib.adapters import CodexAdapter
from aforklib.launch import build_launch


def test_enforceable_postures():
    a = CodexAdapter()
    assert a.enforceable("none")
    assert a.enforceable("read-only")
    assert a.enforceable("workspace-write")
    assert not a.enforceable("totally-open")


def test_declared_posture_normalizes_sandbox_mode():
    a = CodexAdapter()
    assert a.declared_posture({"sandbox_mode": "read-only"}) == "read-only"
    assert a.declared_posture({"sandbox_mode": "workspace-write"}) == "workspace-write"
    assert a.declared_posture({"sandbox_mode": "danger-full-access"}) == "none"
    assert a.declared_posture({}) is None  # no sandbox -> None (defaults to none upstream)


def test_parse_extracts_fields():
    a = CodexAdapter()
    parsed = a.parse(
        'sandbox_mode = "read-only"\n'
        'model_reasoning_effort = "high"\n'
        'model = "gpt-5"\n'
        'developer_instructions = "be careful"\n',
        "reviewer", "/x/reviewer.toml")
    assert parsed["sandbox_mode"] == "read-only"
    assert a.declared_effort(parsed) == "high"
    assert a.declared_model(parsed) == "gpt-5"
    assert a.persona_body(parsed) == "be careful"


def test_build_launcher_enforces_via_flag_and_payloads_persona(tmp_path):
    a = CodexAdapter()
    persona = 'You are the Reviewer.\n## Boundaries\n"quoted" #hash\n'
    command, workdir = build_launch(
        a, "reviewer", "read-only", None, "high", persona,
        root=str(tmp_path / "w"))

    launcher = Path(workdir) / "launch.sh"
    payload = Path(workdir) / "persona.txt"
    script = launcher.read_text()

    # The command handed to tfork is a short, shell-quoted executable launcher.
    assert command == shlex.join([str(launcher)])
    # Posture is enforced via the FLAG, not prose.
    assert "--sandbox read-only" in script
    # Persona is injected at developer level, read from the payload file.
    assert '-c developer_instructions="$(cat "$DIR/persona.txt")"' in script
    assert 'model_reasoning_effort="high"' in script
    # The raw multiline body lives in the payload verbatim, 0600.
    assert payload.read_text() == persona
    assert stat.S_IMODE(payload.stat().st_mode) == 0o600


def test_build_plain_no_launcher(tmp_path):
    a = CodexAdapter()
    command, workdir = build_launch(a, None, "none", None, "xhigh", "")
    # Plain mode: flat argv, no temp launcher.
    assert workdir is None
    assert command.startswith("codex")
    assert "--dangerously-bypass-approvals-and-sandbox" in command
    assert 'model_reasoning_effort="xhigh"' in command


def test_returned_command_is_shell_safe_with_hostile_temp_root(tmp_path):
    """The command tfork pastes into a shell must not allow breakout when the
    temp root holds spaces/metacharacters."""
    import subprocess

    a = CodexAdapter()
    hostile = tmp_path / "afork ;touch${IFS}AFORK_PWNED;#"
    command, _ = build_launch(
        a, "probe", "read-only", None, None, "x", root=str(hostile))

    # Run the command with codex stubbed so nothing real launches; the only
    # thing that matters is whether the injected `touch` fired.
    marker = tmp_path / "AFORK_PWNED"
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    (stub_bin / "codex").write_text("#!/usr/bin/env bash\nexit 0\n")
    (stub_bin / "codex").chmod(0o755)
    env = {"PATH": f"{stub_bin}:/usr/bin:/bin"}
    subprocess.run(command, shell=True, env=env, cwd=str(tmp_path),
                   capture_output=True)
    assert not marker.exists(), "shell injection via temp root path executed"


def test_launcher_command_survives_tfork_single_argument_invocation(tmp_path):
    """If the handoff command is passed to tfork as one argv token, tfork
    shlex-quotes that token before pasting it. A multi-word `bash <launcher>`
    command becomes a literal filename and exits 127. The launcher is already
    executable, so the handoff command should be just the launcher path."""
    import subprocess

    a = CodexAdapter()
    command, _ = build_launch(
        a, "probe", "read-only", None, None, "x", root=str(tmp_path / "w"))

    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    (stub_bin / "codex").write_text("#!/usr/bin/env bash\nexit 0\n")
    (stub_bin / "codex").chmod(0o755)
    env = {"PATH": f"{stub_bin}:/usr/bin:/bin"}

    tfork_style_command = shlex.join([command])
    result = subprocess.run(tfork_style_command, shell=True, env=env,
                            cwd=str(tmp_path), capture_output=True)
    assert result.returncode == 0, result.stderr.decode()


def test_executed_launcher_neutralizes_hostile_persona_and_params(tmp_path):
    """Run the generated launch.sh end-to-end with a hostile persona body AND
    hostile model/effort strings — the higher-risk surface than the wrapper path.
    Persona is read from a 0600 payload via $(cat) (command-sub output is not
    re-evaluated); model/effort are shlex-quoted into the exec line. So none of
    it should execute: assert no marker file appears and the stub runtime
    received every hostile value verbatim as inert data."""
    import subprocess

    a = CodexAdapter()
    marker = tmp_path / "PERSONA_PWNED"
    hostile_persona = (
        'You are the Reviewer.\n'
        f'"; touch {marker} ;"\n'
        f'$(touch {marker})\n'
        f'`touch {marker}`\n'
        '## end\n'
    )
    hostile_model = f'gpt";touch {marker};"'
    hostile_effort = f'high$(touch {marker})'

    command, workdir = build_launch(
        a, "probe", "read-only", hostile_model, hostile_effort, hostile_persona,
        root=str(tmp_path / "w"))

    # Stub codex: record argv (null-delimited) then exit, so nothing real runs.
    argv_dump = tmp_path / "argv.bin"
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    (stub_bin / "codex").write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\0" "$@" > {shlex.quote(str(argv_dump))}\n'
        "exit 0\n")
    (stub_bin / "codex").chmod(0o755)

    env = {"PATH": f"{stub_bin}:/usr/bin:/bin"}
    subprocess.run(command, shell=True, env=env, cwd=str(tmp_path),
                   capture_output=True)

    # 1. Nothing fired — not from persona, not from model/effort.
    assert not marker.exists(), "hostile persona/param executed via the launcher"

    # 2. The stub ran and received the hostile values verbatim as inert data.
    args = [b.decode() for b in argv_dump.read_bytes().split(b"\x00")[:-1]]
    assert "--sandbox" in args and "read-only" in args
    dev = [x for x in args if x.startswith("developer_instructions=")]
    assert dev, args
    assert f"$(touch {marker})" in dev[0]          # delivered literally, not run
    assert f'"; touch {marker} ;"' in dev[0]
    assert any(x.startswith('model="gpt') and "touch" in x for x in args)
    assert any(x.startswith('model_reasoning_effort="high') and "touch" in x
               for x in args)


def test_persona_styles_render_per_adapter(tmp_path):
    """Persona-injection shape is the adapter's declared style, not a guess from
    the flag spelling. codex=config_cat, claude=flag_cat, pi=flag_path."""
    from aforklib.adapters import ClaudeAdapter, PiAdapter

    persona = "ROLE BODY"
    _, wd = build_launch(CodexAdapter(), "a", "read-only", None, None, persona,
                         root=str(tmp_path / "c"))
    assert ('-c developer_instructions="$(cat "$DIR/persona.txt")"'
            in (Path(wd) / "launch.sh").read_text())

    _, wd = build_launch(ClaudeAdapter(), "a", "none", None, None, persona,
                         root=str(tmp_path / "cl"))
    assert ('--append-system-prompt "$(cat "$DIR/persona.txt")"'
            in (Path(wd) / "launch.sh").read_text())

    # pi: the payload PATH is passed directly — no $(cat), so the old
    # flag.startswith("--") heuristic (which forced $(cat)) is gone.
    _, wd = build_launch(PiAdapter(), "a", "none", None, None, persona,
                         root=str(tmp_path / "pi"))
    script = (Path(wd) / "launch.sh").read_text()
    assert '--append-system-prompt "$DIR/persona.txt"' in script
    assert "$(cat" not in script
