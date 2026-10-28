"""Identity preamble: the composer (deep module) and afork's emitted persona
payload for a definition-backed fork. External behavior only — the composed
string and the on-disk payload — not internal wiring."""

from pathlib import Path

from aforklib import run_afork
from aforklib.persona import compose_persona, render_preamble

POSTURE_CLAUSE = "Their availability is not permission."


# --- Composer unit (deep module, isolated) ---------------------------------

def test_composed_begins_with_preamble():
    out = compose_persona("reviewer", "# Reviewer charter\nbody\n")
    assert out.startswith(render_preamble("reviewer"))


def test_role_name_substituted():
    out = compose_persona("spec-reviewer", "charter")
    assert "You ARE the `spec-reviewer` agent" in out
    assert "{role}" not in out


def test_posture_clause_present():
    out = compose_persona("reviewer", "charter")
    assert POSTURE_CLAUSE in out


def test_charter_body_follows_unchanged():
    charter = '# Role\nLine with "quotes" and #hash and {braces}.\n'
    out = compose_persona("reviewer", charter)
    assert out.endswith(charter)


def test_ordering_preamble_before_charter():
    charter = "UNIQUE_CHARTER_MARKER body"
    out = compose_persona("reviewer", charter)
    assert out.index("Identity & Precedence") < out.index("UNIQUE_CHARTER_MARKER")


# The session's start step now hands a role its reading list, so the persona
# carries no startup-reads note: exactly the preamble, a blank line, the charter.
STARTUP_NOTE_MARKERS = ("Required Startup Reads", "agents/memory/",
                        "role-memory router")


def test_composed_is_exactly_preamble_then_charter():
    charter = "# Reviewer charter\nbody\n"
    out = compose_persona("reviewer-agent", charter)
    assert out == render_preamble("reviewer-agent") + "\n\n" + charter


def test_composed_has_no_startup_reads_note():
    out = compose_persona("reviewer-agent", "charter")
    for marker in STARTUP_NOTE_MARKERS:
        assert marker not in out


# --- Definition-backed fork: emitted persona payload, per runtime ----------

def _codex_port(tmp_path, name, body):
    d = tmp_path / ".codex" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.toml").write_text(body)


def _claude_port(tmp_path, name, body):
    d = tmp_path / ".claude" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(body)


def test_codex_definition_fork_payload_begins_with_preamble(tmp_path):
    _codex_port(tmp_path, "reviewer",
                'sandbox_mode = "read-only"\n'
                'developer_instructions = "Be a careful reviewer."\n')
    out = run_afork("codex", agent="reviewer", cwd=str(tmp_path))

    payload = (Path(out["workdir"]) / "persona.txt").read_text()
    assert payload.startswith(render_preamble("reviewer"))
    assert "You ARE the `reviewer` agent" in payload
    assert POSTURE_CLAUSE in payload
    # Charter body still rides along, after the preamble.
    assert payload.endswith("Be a careful reviewer.")


def test_claude_definition_fork_payload_begins_with_preamble(tmp_path):
    _claude_port(tmp_path, "reviewer-agent", "# Reviewer\nRead-only charter body.\n")
    out = run_afork("claude", agent="reviewer-agent", cwd=str(tmp_path))

    payload = (Path(out["workdir"]) / "persona.txt").read_text()
    assert payload.startswith(render_preamble("reviewer-agent"))
    assert "You ARE the `reviewer-agent` agent" in payload
    # The whole .md body follows the preamble unchanged.
    assert payload.endswith("# Reviewer\nRead-only charter body.\n")


# --- No startup-reads note in the emitted persona payload, per runtime -------

def test_codex_payload_is_exactly_preamble_then_charter(tmp_path):
    _codex_port(tmp_path, "reviewer",
                'developer_instructions = "UNIQUE_CHARTER_MARKER"\n')
    out = run_afork("codex", agent="reviewer", cwd=str(tmp_path))

    payload = (Path(out["workdir"]) / "persona.txt").read_text()
    assert payload == render_preamble("reviewer") + "\n\nUNIQUE_CHARTER_MARKER"


def test_claude_payload_is_exactly_preamble_then_charter(tmp_path):
    _claude_port(tmp_path, "reviewer-agent",
                 "# Reviewer\nUNIQUE_CHARTER_MARKER\n")
    out = run_afork("claude", agent="reviewer-agent", cwd=str(tmp_path))

    payload = (Path(out["workdir"]) / "persona.txt").read_text()
    assert payload == (render_preamble("reviewer-agent")
                       + "\n\n# Reviewer\nUNIQUE_CHARTER_MARKER\n")


# --- Plain-fork negative: no agent -> no launcher, no preamble -------------

def test_plain_fork_has_no_launcher_and_no_preamble(tmp_path):
    out = run_afork("codex", cwd=str(tmp_path))
    assert out["agent"] is None
    # Plain mode: flat argv, no temp launcher/payload. The workdir still
    # exists — it holds the launch-contract sidecar every fork gets.
    assert not (Path(out["workdir"]) / "launch.sh").exists()
    assert not (Path(out["workdir"]) / "persona.txt").exists()
    assert "Identity & Precedence" not in out["command"]
    assert "availability is not permission" not in out["command"]
    for marker in STARTUP_NOTE_MARKERS:
        assert marker not in out["command"]


# --- End-to-end integration: one repo, three fork targets, both runtimes -----

def _integration_repo(tmp_path):
    """Build ONE repo holding every fork shape the startup-reads note used to
    vary on, to prove none of them brings it back:
    - a seated role whose ONLY router uses the seated ``-agent`` alias form;
    - a bootstrap adapter with NO router under either form;
    - a root and a DEEPER agents-tree instruction file, each carrying a unique
      marker, to prove the launch never inlines instruction-file contents."""
    router = (tmp_path / "agents" / "memory"
              / "runtime-integration-engineer-agent" / "AGENTS.md")
    router.parent.mkdir(parents=True)
    router.write_text("# Runtime Integration Engineer\nSEATED_ROUTER_MARKER\n")

    (tmp_path / "agents" / "AGENTS.md").write_text("ROOT_AGENTS_MARKER\n")
    deeper = tmp_path / "agents" / "skills" / "AGENTS.md"
    deeper.parent.mkdir(parents=True)
    deeper.write_text("DEEPER_TREE_MARKER\n")

    _codex_port(tmp_path, "runtime-integration-engineer",
                'developer_instructions = "SEATED_CHARTER_MARKER"\n')
    _claude_port(tmp_path, "runtime-integration-engineer-agent",
                 "# RIE\nSEATED_CHARTER_MARKER\n")
    _codex_port(tmp_path, "bootstrap-adapter",
                'developer_instructions = "BOOTSTRAP_CHARTER_MARKER"\n')
    _claude_port(tmp_path, "bootstrap-adapter-agent",
                 "# Bootstrap\nBOOTSTRAP_CHARTER_MARKER\n")


def _payload(out):
    return (Path(out["workdir"]) / "persona.txt").read_text()


def _assert_integration(tmp_path, runtime, seated_agent, seated_charter,
                        boot_agent, boot_charter):
    # Seated role, router present: still exactly preamble + charter.
    seated = _payload(run_afork(runtime, agent=seated_agent, cwd=str(tmp_path)))
    assert seated == render_preamble(seated_agent) + "\n\n" + seated_charter

    # Bootstrap adapter, no router: launches cleanly, same shape.
    boot_out = run_afork(runtime, agent=boot_agent, cwd=str(tmp_path))
    assert boot_out["workdir"] is not None
    assert _payload(boot_out) == render_preamble(boot_agent) + "\n\n" + boot_charter

    # Plain fork: no persona, no launcher.
    plain = run_afork(runtime, cwd=str(tmp_path))
    assert plain["agent"] is None
    assert not (Path(plain["workdir"]) / "launch.sh").exists()

    for text in (seated, _payload(boot_out), plain["command"]):
        for marker in STARTUP_NOTE_MARKERS + ("ROOT_AGENTS_MARKER",
                                              "DEEPER_TREE_MARKER",
                                              "SEATED_ROUTER_MARKER"):
            assert marker not in text


def test_integration_all_targets_codex(tmp_path):
    _integration_repo(tmp_path)
    _assert_integration(
        tmp_path, "codex",
        seated_agent="runtime-integration-engineer",
        seated_charter="SEATED_CHARTER_MARKER",
        boot_agent="bootstrap-adapter",
        boot_charter="BOOTSTRAP_CHARTER_MARKER")


def test_integration_all_targets_claude(tmp_path):
    _integration_repo(tmp_path)
    _assert_integration(
        tmp_path, "claude",
        seated_agent="runtime-integration-engineer-agent",
        seated_charter="# RIE\nSEATED_CHARTER_MARKER\n",
        boot_agent="bootstrap-adapter-agent",
        boot_charter="# Bootstrap\nBOOTSTRAP_CHARTER_MARKER\n")
