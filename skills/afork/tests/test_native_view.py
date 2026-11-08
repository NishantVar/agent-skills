"""--scoped-view: per-session host controls that hide personal/plugin skills
and competing startup hooks while keeping auth, tools, repo instructions and
the named startup hooks — and never touching the personal configuration.

Every test runs against a fixture HOME; nothing is launched.
"""

import json
import shlex
import tomllib
from pathlib import Path

import pytest

from aforklib.cli import main
from aforklib.errors import EXIT_CODES

FLUX_CLAUDE = "bash ~/.claude/hooks/flux-global-memory.sh"
FLUX_CODEX = "bash ~/.codex/hooks/flux-global-memory-codex.sh"
COMPETING = 'printf "COMPETING-BOOTSTRAP\\n"'
PLUGIN = "fx-boot@fx-market"


def _hooks(flux):
    return {"SessionStart": [
        {"hooks": [{"type": "command", "command": flux, "timeout": 30}]},
        {"hooks": [{"type": "command", "command": COMPETING}]}],
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "bash ctx.sh"}]}]}


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    (h / ".claude").mkdir(parents=True)
    (h / ".claude/settings.json").write_text(json.dumps(
        {"hooks": _hooks(FLUX_CLAUDE), "enabledPlugins": {PLUGIN: True},
         "permissions": {"allow": ["Bash(ls)"]}}))
    (h / ".claude/.credentials.json").write_text("{}")
    codex = h / ".codex"
    (codex / "skills/fx-personal").mkdir(parents=True)
    (codex / "hooks.json").write_text(json.dumps({"hooks": _hooks(FLUX_CODEX)}))
    path = codex / "hooks.json"
    (codex / "config.toml").write_text(
        'model = "personal"\n\n'
        f'[plugins."{PLUGIN}"]\nenabled = true\n\n'
        '[plugins."quiet@x"]\n\n'
        f'[hooks.state."{path}:session_start:0:0"]\ntrusted_hash = "sha256:flux"\n\n'
        f'[hooks.state."{path}:session_start:1:0"]\ntrusted_hash = "sha256:competing"\n\n'
        f'[hooks.state."{path}:user_prompt_submit:0:0"]\ntrusted_hash = "sha256:ctx"\n')
    (codex / "auth.json").write_text('{"auth": 1}')
    (codex / "AGENTS.md").write_text("personal instructions\n")
    real = tmp_path / "skill-src/fx-linked"
    real.mkdir(parents=True)
    (real / "SKILL.md").write_text("---\nname: fx-linked\n---\n")
    agents = h / ".agents/skills"
    (agents / "fx-personal").mkdir(parents=True)
    (agents / "fx-personal/SKILL.md").write_text("---\nname: fx-personal\n---\n")
    (agents / "fx-linked").symlink_to(real)
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ("HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "FLUX_ROLE_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", None)
    return h


def _repo(home):
    return home.parent / "repo"


def _snapshot(home):
    return {str(p): (p.read_bytes() if p.is_file() and not p.is_symlink() else None)
            for p in sorted(home.rglob("*"))}


def _afork(argv, capsys):
    rc = main(argv)
    return rc, json.loads(capsys.readouterr().out)


def _scoped(runtime, home, capsys, *extra):
    hook = FLUX_CLAUDE if runtime == "claude" else FLUX_CODEX
    return _afork([runtime, "--role", "fx-builder", "--cwd", str(_repo(home)),
                   "--scoped-view", "--startup-hook", hook, *extra], capsys)


def _argv(command):
    tokens = shlex.split(command)
    env = {}
    assert tokens[0] == "env"
    i = 1
    while "=" in tokens[i] or tokens[i] == "-u":
        if tokens[i] == "-u":
            i += 2
            continue
        key, value = tokens[i].split("=", 1)
        env[key] = value
        i += 1
    return env, tokens[i:]


def test_claude_scoped_view_flags_and_settings(home, capsys):
    before = _snapshot(home)
    rc, out = _scoped("claude", home, capsys)
    assert rc == 0, out
    env, argv = _argv(out["command"])
    assert env == {"FLUX_ROLE_ID": "fx-builder"}
    assert argv[0] == "claude"
    assert "--disable-slash-commands" in argv and "--bare" not in argv
    assert argv[argv.index("--setting-sources") + 1] == "project,local"
    settings = json.loads(Path(argv[argv.index("--settings") + 1]).read_text())
    assert Path(argv[argv.index("--settings") + 1]).parent == Path(out["workdir"])
    assert settings["enabledPlugins"] == {PLUGIN: False}
    starts = [h["command"] for g in settings["hooks"]["SessionStart"] for h in g["hooks"]]
    assert starts == [FLUX_CLAUDE]
    # The personal hook object is copied whole; other events and settings stay.
    assert settings["hooks"]["SessionStart"][0]["hooks"][0]["timeout"] == 30
    assert settings["hooks"]["UserPromptSubmit"] == _hooks(FLUX_CLAUDE)["UserPromptSubmit"]
    assert settings["permissions"] == {"allow": ["Bash(ls)"]}
    view = out["native_view"]
    assert view["runtime"] == "claude" and view["startup_hooks"] == [FLUX_CLAUDE]
    assert view["lost"] and "plugins_disabled" in view
    assert _snapshot(home) == before


def test_claude_disables_plugins_named_by_project_settings(home, capsys):
    (_repo(home) / ".claude").mkdir()
    (_repo(home) / ".claude/settings.local.json").write_text(
        json.dumps({"enabledPlugins": {"repo@m": True}}))
    rc, out = _scoped("claude", home, capsys)
    assert rc == 0, out
    _, argv = _argv(out["command"])
    settings = json.loads(Path(argv[argv.index("--settings") + 1]).read_text())
    assert settings["enabledPlugins"] == {PLUGIN: False, "repo@m": False}


def test_codex_scoped_home(home, capsys):
    before = _snapshot(home)
    rc, out = _scoped("codex", home, capsys)
    assert rc == 0, out
    env, argv = _argv(out["command"])
    assert argv[0] == "codex"
    codex_home = Path(env["CODEX_HOME"])
    assert codex_home.parent == Path(out["workdir"])
    personal = home / ".codex"
    # Kept by link: auth and personal instructions. Not linked: config, hooks, skills.
    assert (codex_home / "auth.json").resolve() == (personal / "auth.json").resolve()
    assert (codex_home / "AGENTS.md").is_symlink()
    assert not (codex_home / "skills").exists()
    assert not (codex_home / "config.toml").is_symlink()
    config = tomllib.loads((codex_home / "config.toml").read_text())
    assert config["model"] == "personal"
    assert {n: t["enabled"] for n, t in config["plugins"].items()} == {
        PLUGIN: False, "quiet@x": False}
    disabled = {i["path"] for i in config["skills"]["config"] if i["enabled"] is False}
    assert str(home / ".agents/skills/fx-personal/SKILL.md") in disabled
    assert str(home / ".agents/skills/fx-linked/SKILL.md") in disabled
    hooks = json.loads((codex_home / "hooks.json").read_text())["hooks"]
    assert [h["command"] for g in hooks["SessionStart"] for h in g["hooks"]] == [FLUX_CODEX]
    assert hooks["UserPromptSubmit"] == _hooks(FLUX_CODEX)["UserPromptSubmit"]
    # Trust is carried from the personal slot each kept hook came from.
    state = config["hooks"]["state"]
    gen = str(codex_home / "hooks.json")
    assert state[f"{gen}:session_start:0:0"]["trusted_hash"] == "sha256:flux"
    assert state[f"{gen}:user_prompt_submit:0:0"]["trusted_hash"] == "sha256:ctx"
    assert not any(v.get("trusted_hash") == "sha256:competing"
                   for k, v in state.items() if k.startswith(gen))
    assert out["native_view"]["untrusted_hooks"] == []
    assert out["native_view"]["unverified"]
    assert _snapshot(home) == before


def test_codex_launcher_shape_exports_codex_home(home, capsys):
    ports = _repo(home) / ".codex/agents"
    ports.mkdir(parents=True)
    (ports / "builder.toml").write_text('developer_instructions = "charter"\n')
    rc, out = _afork(["codex", "builder", "--cwd", str(_repo(home)), "--scoped-view",
                      "--startup-hook", FLUX_CODEX], capsys)
    assert rc == 0, out
    launcher = Path(shlex.split(out["command"])[0]).read_text()
    assert f"export CODEX_HOME={Path(out['workdir']) / 'codex-home'}" in launcher


def test_codex_config_hooks_fail_closed(home, capsys):
    path = home / ".codex/config.toml"
    path.write_text(path.read_text() + '\n[[hooks.SessionStart]]\ncommand = "x"\n')
    rc, out = _scoped("codex", home, capsys)
    assert rc == EXIT_CODES["scoped_view_unenforceable"]
    assert out["code"] == "scoped_view_unenforceable"


@pytest.mark.parametrize("runtime", ["pi", "antigravity"])
def test_unsupported_runtime_is_named(home, capsys, runtime):
    rc, out = _afork([runtime, "--scoped-view", "--startup-hook", "x",
                      "--cwd", str(_repo(home))], capsys)
    if runtime == "pi":
        assert out["code"] == "scoped_view_unsupported"
        assert rc == EXIT_CODES["scoped_view_unsupported"]
    else:
        assert out["code"] == "runtime_unsupported"


@pytest.mark.parametrize("argv", [["--scoped-view"], ["--startup-hook", "x"]])
def test_flags_need_each_other(home, capsys, argv):
    rc, out = _afork(["claude", "--cwd", str(_repo(home)), *argv], capsys)
    assert rc == EXIT_CODES["bad_arguments"] and out["code"] == "bad_arguments"


def test_unscoped_handoff_is_unchanged(home, capsys):
    rc, out = _afork(["claude", "--cwd", str(_repo(home))], capsys)
    assert rc == 0 and "native_view" not in out
    assert "--disable-slash-commands" not in out["command"]
