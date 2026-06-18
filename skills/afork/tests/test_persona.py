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


# --- Plain-fork negative: no agent -> no launcher, no preamble -------------

def test_plain_fork_has_no_launcher_and_no_preamble(tmp_path):
    out = run_afork("codex", cwd=str(tmp_path))
    assert out["agent"] is None
    # Plain mode: flat argv, no temp launcher/payload dir.
    assert out["workdir"] is None
    assert "Identity & Precedence" not in out["command"]
    assert "availability is not permission" not in out["command"]
