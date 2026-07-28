"""The generic legacy Claude naming bridge.

Exact-name lookup always runs first. Only when it misses, and only for Claude,
does a requested name ending in ``-agent`` fall back to its suffixless stem.
The bridge is a rule, not a table: no role is named anywhere in the code, so a
role added tomorrow is bridged with no edit here.
"""

import pytest

from aforklib import run_afork
from aforklib.adapters import ClaudeAdapter, CodexAdapter
from aforklib.errors import AforkError
from aforklib.resolve import resolve_agent_definition


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Port lookup searches the cwd base AND the home base. Without this the
    developer's own ~/.claude/agents would satisfy lookups these tests need to
    miss, and the bridge assertions would pass or fail by accident."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


def _port(tmp_path, runtime, name, body):
    d = tmp_path / f".{runtime}" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body)


def test_legacy_name_falls_back_to_suffixless_stem(tmp_path):
    _port(tmp_path, "claude", "reviewer.md", "# Reviewer\nbody\n")

    path, text, name, warning = resolve_agent_definition(
        ClaudeAdapter(), "reviewer-agent", str(tmp_path))

    # The canonical name is the suffixless one — the port that actually exists.
    assert name == "reviewer"
    assert path.endswith(".claude/agents/reviewer.md")
    assert "Reviewer" in text
    assert warning is not None
    assert "reviewer-agent" in warning and "reviewer" in warning


def test_exact_suffixed_definition_beats_the_bridge(tmp_path):
    """A repo that genuinely defines ``reviewer-agent.md`` keeps it. The bridge
    only ever runs on an exact-lookup miss, so it cannot shadow a real port."""
    _port(tmp_path, "claude", "reviewer-agent.md", "# Suffixed\nEXACT\n")
    _port(tmp_path, "claude", "reviewer.md", "# Stem\nSTEM\n")

    path, text, name, warning = resolve_agent_definition(
        ClaudeAdapter(), "reviewer-agent", str(tmp_path))

    assert name == "reviewer-agent"
    assert path.endswith(".claude/agents/reviewer-agent.md")
    assert "EXACT" in text
    assert warning is None


def test_bridge_is_generic_not_a_per_role_map(tmp_path):
    """Two roles nobody wrote a mapping for, bridged by the same rule."""
    _port(tmp_path, "claude", "widget-polisher.md", "# Polisher\n")
    _port(tmp_path, "claude", "zzz.md", "# Zzz\n")

    for requested, canonical in (("widget-polisher-agent", "widget-polisher"),
                                 ("zzz-agent", "zzz")):
        _, _, name, warning = resolve_agent_definition(
            ClaudeAdapter(), requested, str(tmp_path))
        assert name == canonical
        assert warning is not None


def test_codex_gets_no_inverse_alias(tmp_path):
    """The bridge is Claude-only and one-directional. Codex neither strips the
    suffix nor adds one."""
    _port(tmp_path, "codex", "reviewer.toml", 'sandbox_mode = "read-only"\n')

    with pytest.raises(AforkError) as exc:
        resolve_agent_definition(CodexAdapter(), "reviewer-agent",
                                 str(tmp_path))
    assert exc.value.code == "port_not_found"

    # ...and the reverse direction is equally absent.
    _port(tmp_path, "codex", "auditor-agent.toml", 'sandbox_mode = "read-only"\n')
    with pytest.raises(AforkError) as exc:
        resolve_agent_definition(CodexAdapter(), "auditor", str(tmp_path))
    assert exc.value.code == "port_not_found"


def test_bridge_does_not_fire_for_a_name_without_the_suffix(tmp_path):
    _port(tmp_path, "claude", "reviewer.md", "# Reviewer\n")

    with pytest.raises(AforkError) as exc:
        resolve_agent_definition(ClaudeAdapter(), "auditor", str(tmp_path))
    assert exc.value.code == "port_not_found"


def test_bare_suffix_is_not_a_stem(tmp_path):
    """``-agent`` strips to the empty string, which is not a name. No bridge."""
    _port(tmp_path, "claude", "reviewer.md", "# Reviewer\n")

    with pytest.raises(AforkError) as exc:
        resolve_agent_definition(ClaudeAdapter(), "-agent", str(tmp_path))
    assert exc.value.code == "port_not_found"


def test_both_misses_report_every_path_searched(tmp_path):
    """When the bridge also misses, the error accounts for both lookups —
    otherwise the user is told only half of where afork looked."""
    with pytest.raises(AforkError) as exc:
        resolve_agent_definition(ClaudeAdapter(), "ghost-agent", str(tmp_path))

    assert exc.value.code == "port_not_found"
    searched = exc.value.extras["searched"]
    assert any("ghost-agent.md" in s for s in searched)
    assert any(s.endswith("ghost.md") for s in searched)


def test_deprecation_warning_reaches_the_handoff(tmp_path):
    _port(tmp_path, "claude", "reviewer.md", "# Reviewer\nbody\n")
    out = run_afork("claude", agent="reviewer-agent", cwd=str(tmp_path))

    assert out["ok"] is True
    # The handoff reports the CANONICAL name, so whatever the caller stores or
    # forwards is the name that will keep resolving after the bridge is gone.
    assert out["agent"] == "reviewer"
    assert "reviewer-agent" in out["deprecation_warning"]
    # ...and the note carries it too, so a human reading the fork sees it.
    assert "reviewer-agent" in out["note"]


def test_no_deprecation_key_on_a_clean_resolve(tmp_path):
    _port(tmp_path, "claude", "reviewer.md", "# Reviewer\nbody\n")
    out = run_afork("claude", agent="reviewer", cwd=str(tmp_path))

    assert out["agent"] == "reviewer"
    assert "deprecation_warning" not in out
