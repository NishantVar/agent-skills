"""Port resolution: relative to --cwd, not the skill repo."""

import pytest

from aforklib.adapters import ClaudeAdapter, CodexAdapter
from aforklib.errors import AforkError
from aforklib.resolve import resolve_agent_definition, resolve_port


def _write_port(tmp_path, runtime, name, body):
    d = tmp_path / f".{runtime}" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body)


def test_codex_port_resolves_under_cwd(tmp_path):
    _write_port(tmp_path, "codex", "reviewer.toml",
                'name = "reviewer"\nsandbox_mode = "read-only"\n')
    path, text = resolve_port(CodexAdapter(), "reviewer", str(tmp_path))
    assert path.endswith(".codex/agents/reviewer.toml")
    assert "read-only" in text


def test_bare_agent_definition_resolves_under_cwd(tmp_path):
    _write_port(tmp_path, "codex", "reviewer.toml",
                'name = "reviewer"\nsandbox_mode = "read-only"\n')
    path, text, name = resolve_agent_definition(
        CodexAdapter(), "reviewer", str(tmp_path))
    assert path.endswith(".codex/agents/reviewer.toml")
    assert "read-only" in text
    assert name == "reviewer"


def test_claude_port_uses_md_extension(tmp_path):
    _write_port(tmp_path, "claude", "reviewer-agent.md", "# Reviewer\n")
    path, _ = resolve_port(ClaudeAdapter(), "reviewer-agent", str(tmp_path))
    assert path.endswith(".claude/agents/reviewer-agent.md")


def test_missing_port_raises_port_not_found(tmp_path):
    with pytest.raises(AforkError) as exc:
        resolve_port(CodexAdapter(), "ghost", str(tmp_path))
    assert exc.value.code == "port_not_found"
    assert "ghost.toml" in exc.value.extras["expected_path"]


def test_nonexistent_explicit_path_raises_port_not_found(tmp_path):
    missing = tmp_path / "other-repo" / ".codex" / "agents" / "ghost.toml"
    with pytest.raises(AforkError) as exc:
        resolve_agent_definition(CodexAdapter(), str(missing), str(tmp_path))
    assert exc.value.code == "port_not_found"
    assert exc.value.extras["agent"] == "ghost"
    assert exc.value.extras["expected_path"] == str(missing)
    assert "explicit path" in exc.value.agent_instruction


def test_extension_suffix_selects_explicit_path_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    missing = tmp_path / "ghost.toml"
    with pytest.raises(AforkError) as exc:
        resolve_agent_definition(CodexAdapter(), "ghost.toml",
                                 str(tmp_path / "run-dir"))
    assert exc.value.code == "port_not_found"
    assert exc.value.extras["agent"] == "ghost"
    assert exc.value.extras["expected_path"] == str(missing)


def test_existing_file_without_separator_selects_explicit_path_mode(tmp_path,
                                                                   monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "local-agent.toml"
    path.write_text('sandbox_mode = "read-only"\n')
    run_dir = tmp_path / "run-dir"
    run_dir.mkdir()

    resolved, text, name = resolve_agent_definition(
        CodexAdapter(), "local-agent.toml", str(run_dir))

    assert resolved == str(path)
    assert "read-only" in text
    assert name == "local-agent"


def test_explicit_path_with_wrong_extension_is_bad_arguments(tmp_path):
    path = tmp_path / "other-repo" / ".codex" / "agents" / "reviewer.md"
    path.parent.mkdir(parents=True)
    path.write_text("# reviewer\n")
    with pytest.raises(AforkError) as exc:
        resolve_agent_definition(CodexAdapter(), str(path), str(tmp_path))
    assert exc.value.code == "bad_arguments"


@pytest.mark.parametrize("name", ["../../outside", "../escape", "a/b", "x\\y"])
def test_traversal_agent_names_rejected(tmp_path, name):
    # Even if a tempting target exists outside the agents dir, it must refuse.
    (tmp_path / "outside.toml").write_text('sandbox_mode = "read-only"\n')
    with pytest.raises(AforkError) as exc:
        resolve_port(CodexAdapter(), name, str(tmp_path))
    assert exc.value.code == "bad_arguments"
