"""--mcp-server: a stdio MCP server given to one session through launch flags.

claude gets an inline --mcp-config JSON string; codex gets -c mcp_servers.N
overrides. Nothing is written to any configuration, and nothing is launched.
"""

import json
import shlex
import tomllib
from pathlib import Path

import pytest

from aforklib.cli import main
from aforklib.errors import EXIT_CODES

MERMAID = {"name": "mermaid", "command": "npx", "args": ["-y", "claude-mermaid@1.7.0"]}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "FLUX_ROLE_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", None)
    path = tmp_path / "repo"
    path.mkdir()
    return path


def _afork(argv, capsys):
    rc = main(argv)
    return rc, json.loads(capsys.readouterr().out)


def _argv(command):
    tokens = shlex.split(command)
    i = 1
    while "=" in tokens[i] or tokens[i] == "-u":
        i += 2 if tokens[i] == "-u" else 1
    return tokens[i:]


def _launch(runtime, repo, capsys, *specs):
    argv = [runtime, "--role", "fx-builder", "--cwd", str(repo)]
    for spec in specs:
        argv += ["--mcp-server", json.dumps(spec)]
    return _afork(argv, capsys)


def test_claude_gets_inline_mcp_config(repo, capsys):
    rc, out = _launch("claude", repo, capsys, MERMAID)
    assert rc == 0, out
    argv = _argv(out["command"])
    config = json.loads(argv[argv.index("--mcp-config") + 1])
    assert config == {"mcpServers": {"mermaid": {
        "type": "stdio", "command": "npx", "args": ["-y", "claude-mermaid@1.7.0"]}}}
    assert argv.count("--mcp-config") == 1


def test_codex_gets_config_overrides_that_parse_as_toml(repo, capsys):
    rc, out = _launch("codex", repo, capsys, MERMAID)
    assert rc == 0, out
    argv = _argv(out["command"])
    overrides = [argv[i + 1] for i, token in enumerate(argv) if token == "-c"]
    mcp = [o for o in overrides if o.startswith("mcp_servers.")]
    assert mcp == ['mcp_servers.mermaid.command="npx"',
                   'mcp_servers.mermaid.args=["-y", "claude-mermaid@1.7.0"]']
    parsed = {}
    for override in mcp:
        key, value = override.split("=", 1)
        parsed[key] = tomllib.loads(f"v = {value}")["v"]
    assert parsed == {"mcp_servers.mermaid.command": "npx",
                      "mcp_servers.mermaid.args": ["-y", "claude-mermaid@1.7.0"]}


def test_two_servers_and_default_args(repo, capsys):
    rc, out = _launch("claude", repo, capsys, MERMAID, {"name": "b", "command": "srv"})
    assert rc == 0, out
    argv = _argv(out["command"])
    config = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]
    assert list(config) == ["mermaid", "b"] and config["b"]["args"] == []


def test_launcher_shape_carries_the_flags(repo, capsys):
    ports = repo / ".codex/agents"
    ports.mkdir(parents=True)
    (ports / "builder.toml").write_text('developer_instructions = "charter"\n')
    rc, out = _afork(["codex", "builder", "--cwd", str(repo),
                      "--mcp-server", json.dumps(MERMAID)], capsys)
    assert rc == 0, out
    launcher = Path(shlex.split(out["command"])[0]).read_text()
    assert "mcp_servers.mermaid.command=" in launcher


def test_without_the_flag_nothing_is_added(repo, capsys):
    for runtime in ("claude", "codex"):
        rc, out = _afork([runtime, "--cwd", str(repo)], capsys)
        assert rc == 0, out
        assert "mcp" not in out["command"]


@pytest.mark.parametrize("spec", [
    "not json",
    json.dumps(["mermaid"]),
    json.dumps({"name": "a b", "command": "npx"}),
    json.dumps({"name": "m", "command": ""}),
    json.dumps({"name": "m", "command": "npx", "args": "-y"}),
    json.dumps({"name": "m", "command": "npx", "env": {}}),
])
def test_bad_specs_are_bad_arguments(repo, capsys, spec):
    rc, out = _afork(["claude", "--cwd", str(repo), "--mcp-server", spec], capsys)
    assert rc == EXIT_CODES["bad_arguments"] and out["code"] == "bad_arguments"


def test_duplicate_name_is_bad_arguments(repo, capsys):
    rc, out = _launch("claude", repo, capsys, MERMAID, MERMAID)
    assert out["code"] == "bad_arguments"


def test_runtime_without_mcp_flags_is_named(repo, capsys):
    rc, out = _launch("pi", repo, capsys, MERMAID)
    assert rc == EXIT_CODES["bad_arguments"]
    assert "not supported for pi" in out["human_message"]
