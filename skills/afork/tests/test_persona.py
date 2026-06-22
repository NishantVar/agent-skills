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


def test_ordering_preamble_then_startup_reads_then_charter():
    charter = "UNIQUE_CHARTER_MARKER body"
    out = compose_persona("reviewer", charter)
    i_preamble = out.index("Identity & Precedence")
    i_startup = out.index("Required Startup Reads")
    i_charter = out.index("UNIQUE_CHARTER_MARKER")
    assert i_preamble < i_startup < i_charter


def test_startup_reads_block_role_templated():
    out = compose_persona("reviewer-agent", "charter")
    assert "agents/memory/reviewer-agent/AGENTS.md" in out
    assert "{role}" not in out


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


# --- Required Startup Reads block in the emitted persona payload, per runtime --

def test_codex_payload_carries_startup_reads_in_order(tmp_path):
    _codex_port(tmp_path, "reviewer",
                'developer_instructions = "UNIQUE_CHARTER_MARKER"\n')
    out = run_afork("codex", agent="reviewer", cwd=str(tmp_path))

    payload = (Path(out["workdir"]) / "persona.txt").read_text()
    assert "Required Startup Reads" in payload
    assert "agents/memory/reviewer/AGENTS.md" in payload
    # Identity preamble, then startup reads, then the charter body — in order.
    assert (payload.index("Identity & Precedence")
            < payload.index("Required Startup Reads")
            < payload.index("UNIQUE_CHARTER_MARKER"))


def test_codex_payload_uses_agent_suffix_role_memory_alias(tmp_path):
    _codex_port(tmp_path, "runtime-integration-engineer",
                'developer_instructions = "UNIQUE_CHARTER_MARKER"\n')
    router = (tmp_path / "agents" / "memory"
              / "runtime-integration-engineer-agent" / "AGENTS.md")
    router.parent.mkdir(parents=True)
    router.write_text("# Runtime Integration Engineer\n")

    out = run_afork("codex", agent="runtime-integration-engineer",
                    cwd=str(tmp_path))

    payload = (Path(out["workdir"]) / "persona.txt").read_text()
    assert "agents/memory/runtime-integration-engineer-agent/AGENTS.md" in payload


def test_claude_payload_carries_startup_reads_in_order(tmp_path):
    _claude_port(tmp_path, "reviewer-agent",
                 "# Reviewer\nUNIQUE_CHARTER_MARKER\n")
    out = run_afork("claude", agent="reviewer-agent", cwd=str(tmp_path))

    payload = (Path(out["workdir"]) / "persona.txt").read_text()
    assert "Required Startup Reads" in payload
    assert "agents/memory/reviewer-agent/AGENTS.md" in payload
    assert (payload.index("Identity & Precedence")
            < payload.index("Required Startup Reads")
            < payload.index("UNIQUE_CHARTER_MARKER"))


# --- Missing seated router: launch still succeeds (no launch failure) -------

def test_launch_without_seated_router_succeeds(tmp_path):
    # A bootstrap/lifecycle adapter with no seated role memory must launch
    # cleanly; the block reports the missing router rather than failing.
    _claude_port(tmp_path, "bootstrap-adapter-agent", "# Adapter\nbody\n")
    out = run_afork("claude", agent="bootstrap-adapter-agent", cwd=str(tmp_path))

    # Launch produced a real launcher/payload — no exception, no fail-closed.
    assert out["workdir"] is not None
    payload = (Path(out["workdir"]) / "persona.txt").read_text()
    assert "agents/memory/bootstrap-adapter-agent/AGENTS.md" in payload
    assert "report the missing role router" in payload


# --- Plain-fork negative: no agent -> no launcher, no preamble -------------

def test_plain_fork_has_no_launcher_and_no_preamble(tmp_path):
    out = run_afork("codex", cwd=str(tmp_path))
    assert out["agent"] is None
    # Plain mode: flat argv, no temp launcher/payload dir.
    assert out["workdir"] is None
    assert "Identity & Precedence" not in out["command"]
    assert "availability is not permission" not in out["command"]
    # A plain fork is a general runtime session: no role startup-read block and
    # no role-memory instruction.
    assert "Required Startup Reads" not in out["command"]
    assert "role-memory router" not in out["command"]


# --- End-to-end integration: one repo, three fork targets, both runtimes -----

def _integration_repo(tmp_path):
    """Build ONE repo holding all the startup-read fork shapes at once:
    - a seated role whose ONLY router uses the seated ``-agent`` alias form
      (Codex launches the short stem -> alias resolves; Claude launches the full
      id -> same-name resolves; both must point at this one router);
    - a bootstrap adapter with NO router under either form;
    - a root and a DEEPER agents-tree instruction file, each carrying a unique
      marker, to prove the launch never inlines/crawls instruction-file contents;
    - ports for both runtimes carrying NO startup-read text (so a present block
      proves inheritance, not per-port boilerplate)."""
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


def _assert_integration(tmp_path, runtime, seated_agent, boot_agent,
                        seated_port_file):
    seated = _payload(run_afork(runtime, agent=seated_agent, cwd=str(tmp_path)))
    # Seated role -> its (alias or same-name) router, never reported missing.
    assert "agents/memory/runtime-integration-engineer-agent/AGENTS.md" in seated
    assert "report the missing role router" not in seated
    # Ordering regression: preamble < startup-read block < charter body.
    assert (seated.index("Identity & Precedence")
            < seated.index("Required Startup Reads")
            < seated.index("SEATED_CHARTER_MARKER"))

    # Bootstrap adapter (no router): launches cleanly, reports the missing router.
    boot_out = run_afork(runtime, agent=boot_agent, cwd=str(tmp_path))
    assert boot_out["workdir"] is not None
    assert "report the missing role router" in _payload(boot_out)

    # Plain fork: no startup-read block, no launcher.
    plain = run_afork(runtime, cwd=str(tmp_path))
    assert plain["agent"] is None
    assert plain["workdir"] is None
    assert "Required Startup Reads" not in plain["command"]

    # No per-port churn: the block is inherited, not pasted into the port body.
    assert "Required Startup Reads" not in seated_port_file.read_text()

    # No deeper-tree crawl: the block NAMES paths and states the rule, but no
    # instruction-file contents (root, deeper, or router) are inlined at launch.
    assert "do not crawl every" in seated
    assert "ROOT_AGENTS_MARKER" not in seated
    assert "DEEPER_TREE_MARKER" not in seated
    assert "SEATED_ROUTER_MARKER" not in seated


def test_integration_all_targets_codex(tmp_path):
    _integration_repo(tmp_path)
    _assert_integration(
        tmp_path, "codex",
        seated_agent="runtime-integration-engineer",
        boot_agent="bootstrap-adapter",
        seated_port_file=(tmp_path / ".codex" / "agents"
                          / "runtime-integration-engineer.toml"))


def test_integration_all_targets_claude(tmp_path):
    _integration_repo(tmp_path)
    _assert_integration(
        tmp_path, "claude",
        seated_agent="runtime-integration-engineer-agent",
        boot_agent="bootstrap-adapter-agent",
        seated_port_file=(tmp_path / ".claude" / "agents"
                          / "runtime-integration-engineer-agent.md"))
