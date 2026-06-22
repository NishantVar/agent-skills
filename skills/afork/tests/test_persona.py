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
