"""Scoped native view — per-session host controls for ``--scoped-view``.

A scoped launch hides the caller's personal and plugin skills and any competing
skill-bootstrap hook from the launched session, while keeping its required
tools, authentication, repo instructions and the startup hooks the caller names
(``--startup-hook``). Nothing global is changed: every control is either a
launch flag or a file in afork's private workdir.

  * claude -> ``--disable-slash-commands`` (no skill or command listing),
    ``--setting-sources project,local`` (the user settings file is not read)
    and ``--settings <workdir>/settings.json``: a copy of the user settings with
    the SessionStart hooks replaced by the named startup hooks and every plugin
    named in any settings layer set to disabled. ``CLAUDE_CONFIG_DIR`` is left
    alone, so credentials stay where they are.

  * codex -> ``CODEX_HOME=<workdir>/codex-home``: every entry of the personal
    Codex home is linked in except ``config.toml``, ``hooks.json`` and
    ``skills``. The config is a copy with every plugin disabled and every
    personal ``~/.agents/skills`` skill disabled by path; ``hooks.json`` is a
    copy with SessionStart replaced by the named startup hooks. Hook trust is
    carried to the copied hooks by copying the personal ``trusted_hash``.

With ``view_root`` (``--view-root``) the scoped files go in
``<view_root>/<workdir name>/`` instead of the workdir: Codex declines to make
its PATH helper aliases under a CODEX_HOME inside the temp dir, and afork's
workdir is a temp dir. afork never deletes either location.

Any personal setup this cannot represent fails closed with
``scoped_view_unenforceable``; pi and antigravity have no scoped view and fail
with ``scoped_view_unsupported``.
"""

import json
import os
import re
import tempfile
from pathlib import Path

from .errors import err_scoped_view_unenforceable, err_scoped_view_unsupported

# What a scoped session keeps. No control here restricts these; the report
# names them so a caller can see none was dropped.
_KEPT = ["tools", "authentication", "repo instructions", "named startup hooks"]


def _home():
    return Path(os.path.expanduser("~"))


def _read_json(path, runtime):
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise err_scoped_view_unenforceable(runtime, f"cannot read {path}: {exc}")
    if not isinstance(data, dict):
        raise err_scoped_view_unenforceable(runtime, f"{path} is not a JSON object")
    return data


def _under_temp(path):
    """True when ``path`` is inside the temp dir, by spelling or resolved."""
    temp = tempfile.gettempdir()
    for p, t in ((os.path.abspath(path), os.path.abspath(temp)),
                 (os.path.realpath(path), os.path.realpath(temp))):
        if p == t or p.startswith(t.rstrip(os.sep) + os.sep):
            return True
    return False


def _selected_groups(groups, commands):
    """One SessionStart group per named command, in the order named. A command
    the personal setup already has keeps its exact hook object (and its group's
    other fields); a new one is a plain command hook. Returns the groups and,
    per new group index, the (group, hook) index it was copied from."""
    out, origin = [], {}
    for command in commands:
        found = None
        for g, group in enumerate(groups or []):
            for h, hook in enumerate((group or {}).get("hooks") or []):
                if isinstance(hook, dict) and hook.get("command") == command:
                    found = (g, h, group, hook)
                    break
            if found:
                break
        if found:
            g, h, group, hook = found
            copy = {k: v for k, v in group.items() if k != "hooks"}
            copy["hooks"] = [hook]
            origin[len(out)] = (g, h)
            out.append(copy)
        else:
            out.append({"hooks": [{"type": "command", "command": command}]})
    return out, origin


# --- claude -----------------------------------------------------------------

def _claude(workdir, hooks, cwd):
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or _home() / ".claude")
    user = _read_json(config_dir / "settings.json", "claude")
    layers = [user,
              _read_json(Path(cwd) / ".claude/settings.json", "claude"),
              _read_json(Path(cwd) / ".claude/settings.local.json", "claude")]
    settings = json.loads(json.dumps(user))
    settings_hooks = dict(settings.get("hooks") or {})
    settings_hooks["SessionStart"], _ = _selected_groups(
        settings_hooks.get("SessionStart"), hooks)
    settings["hooks"] = settings_hooks
    plugins = {}
    for layer in layers:
        plugins.update({name: False for name in (layer.get("enabledPlugins") or {})})
    settings["enabledPlugins"] = plugins

    path = Path(workdir) / "settings.json"
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    argv = ["--disable-slash-commands", "--setting-sources", "project,local",
            "--settings", str(path)]
    report = {
        "controls": ["--disable-slash-commands",
                     "--setting-sources project,local",
                     f"--settings {path}"],
        "settings": str(path),
        "plugins_disabled": sorted(plugins),
        "kept": _KEPT,
        "lost": ["custom slash commands (--disable-slash-commands hides "
                 "commands as well as skills)",
                 "the user setting source: ~/.claude/CLAUDE.md, ~/.claude/rules, "
                 "and user skills, commands and agents under ~/.claude are not "
                 "read (--setting-sources project,local)",
                 "plugin-supplied skills, commands, agents, hooks and MCP "
                 "servers (every plugin disabled)"],
        "unverified": [],
        "notes": ["project and local settings are read unchanged, including any "
                  "hooks they declare",
                  "user settings keys other than SessionStart and enabledPlugins "
                  "(permissions, other hooks) are carried in the --settings copy",
                  "user-scope MCP servers in ~/.claude.json and auto memory are "
                  "still loaded",
                  f"the settings copy is {path}, mode 0600; afork does not delete it"],
    }
    return {}, argv, report


# --- codex ------------------------------------------------------------------

_PLUGIN_HEADER = re.compile(r"^\s*\[\s*plugins\s*\.")
_TABLE_HEADER = re.compile(r"^\s*\[")
_ENABLED = re.compile(r"^\s*enabled\s*=")


def _disable_plugins(text):
    """Set ``enabled = false`` in every ``[plugins.<name>]`` table of a
    config.toml text. The result is re-parsed and checked by the caller."""
    out, in_plugin, wrote = [], False, True
    for line in text.splitlines():
        if _TABLE_HEADER.match(line):
            if in_plugin and not wrote:
                out.append("enabled = false")
            in_plugin = bool(_PLUGIN_HEADER.match(line)) and not line.lstrip().startswith("[[")
            wrote = not in_plugin
            out.append(line)
            continue
        if in_plugin and _ENABLED.match(line):
            out.append("enabled = false")
            wrote = True
            continue
        out.append(line)
    if in_plugin and not wrote:
        out.append("enabled = false")
    return "\n".join(out) + "\n"


def _snake(event):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()


def _personal_skills():
    """SKILL.md paths under ~/.agents/skills (followed through symlinked skill
    dirs), spelled both as found and resolved when those differ."""
    root = _home() / ".agents" / "skills"
    paths = []
    if not root.is_dir():
        return paths
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        if len(Path(dirpath).relative_to(root).parts) >= 3:
            dirnames[:] = []
        if "SKILL.md" in filenames:
            found = str(Path(dirpath) / "SKILL.md")
            for spelling in (found, os.path.realpath(found)):
                if spelling not in paths:
                    paths.append(spelling)
    return sorted(paths)


def _keys(path):
    """The hook-trust key spellings for a hooks.json path."""
    raw = str(path)
    real = os.path.realpath(raw)
    return [raw] if raw == real else [raw, real]


def _codex(workdir, hooks, cwd):
    import tomllib  # Python 3.11+; only a scoped codex launch needs it.

    personal = Path(os.environ.get("CODEX_HOME") or _home() / ".codex")
    home = Path(workdir) / "codex-home"
    home.mkdir(mode=0o700)
    if personal.is_dir():
        for entry in sorted(personal.iterdir()):
            if entry.name not in ("config.toml", "hooks.json", "skills"):
                (home / entry.name).symlink_to(entry)

    config_path = personal / "config.toml"
    text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    try:
        config = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise err_scoped_view_unenforceable("codex", f"cannot parse {config_path}: {exc}")
    events = sorted(set(config.get("hooks") or {}) - {"state"})
    if events:
        raise err_scoped_view_unenforceable(
            "codex", f"{config_path} declares hooks in config ({', '.join(events)}); "
            "only hooks.json hooks can be scoped")
    state = (config.get("hooks") or {}).get("state") or {}

    # hooks.json: the personal hooks with SessionStart replaced.
    hooks_data = _read_json(personal / "hooks.json", "codex")
    events_in = dict(hooks_data.get("hooks") or {})
    personal_session = events_in.get("SessionStart")
    events_in["SessionStart"], origin = _selected_groups(personal_session, hooks)
    hooks_data["hooks"] = events_in
    gen_hooks = home / "hooks.json"
    gen_hooks.write_text(json.dumps(hooks_data, indent=2) + "\n", encoding="utf-8")

    # Trust: a copied hook keeps the personal trusted_hash of the slot it came from.
    trust, untrusted = {}, []

    def carry(event, src, dst, command):
        for key in _keys(personal / "hooks.json"):
            entry = state.get(f"{key}:{event}:{src[0]}:{src[1]}")
            if isinstance(entry, dict) and entry.get("trusted_hash"):
                for gen_key in _keys(gen_hooks):
                    trust[f"{gen_key}:{event}:{dst[0]}:{dst[1]}"] = entry["trusted_hash"]
                return
        untrusted.append(command)

    for event, groups in events_in.items():
        for g, group in enumerate(groups or []):
            for h, hook in enumerate((group or {}).get("hooks") or []):
                command = (hook or {}).get("command", "")
                if event == "SessionStart":
                    if g in origin:
                        carry("session_start", origin[g], (g, h), command)
                    else:
                        untrusted.append(command)
                else:
                    carry(_snake(event), (g, h), (g, h), command)

    skills = _personal_skills()
    lines = [_disable_plugins(text).rstrip("\n"), "",
             "# Added by afork --scoped-view for this session only."]
    for path in skills:
        lines += ["[[skills.config]]", f"path = {json.dumps(path)}", "enabled = false", ""]
    for key, value in trust.items():
        lines += [f"[hooks.state.{json.dumps(key)}]", f"trusted_hash = {json.dumps(value)}", ""]
    out = "\n".join(lines) + "\n"

    try:
        check = tomllib.loads(out)
    except tomllib.TOMLDecodeError as exc:
        raise err_scoped_view_unenforceable(
            "codex", f"the scoped copy of {config_path} does not parse: {exc}")
    still = [name for name, table in (check.get("plugins") or {}).items()
             if not (isinstance(table, dict) and table.get("enabled") is False)]
    enabled_skills = {str(item.get("path")) for item in (check.get("skills") or {}).get("config") or []
                      if isinstance(item, dict) and item.get("enabled") is not False}
    if still or enabled_skills & set(skills):
        raise err_scoped_view_unenforceable(
            "codex", "the scoped config still enables "
            + ", ".join(sorted(still) + sorted(enabled_skills & set(skills))))

    gen_config = home / "config.toml"
    gen_config.write_text(out, encoding="utf-8")
    os.chmod(gen_config, 0o600)
    report = {
        "controls": [f"CODEX_HOME={home}"],
        "codex_home": str(home),
        "plugins_disabled": sorted((check.get("plugins") or {})),
        "skills_disabled": skills,
        "kept": _KEPT,
        "lost": ["personal user skills under ~/.codex/skills (Codex re-creates "
                 "its bundled system skills in the scoped home)",
                 "plugin-supplied skills, MCP servers, apps and hooks (every "
                 "plugin disabled)",
                 "config changes the session writes, including a trust answer "
                 "for a new project directory (they go to the scoped copy)"],
        "unverified": ["hook trust carried by copying trusted_hash to the scoped "
                       "hooks.json path"],
        "notes": ["project trust levels in the personal config.toml are carried "
                  "in the scoped copy",
                  f"the scoped home is {home}; afork does not delete it"],
        "untrusted_hooks": untrusted,
    }
    if _under_temp(home):
        report["lost"].append(
            "Codex PATH helper aliases such as apply_patch (Codex declines to "
            "create them under a CODEX_HOME inside the temp dir; pass "
            "--view-root outside it to keep them)")
    return {"CODEX_HOME": str(home)}, [], report


_BUILDERS = {"claude": _claude, "codex": _codex}


def check_supported(runtime):
    if runtime not in _BUILDERS:
        raise err_scoped_view_unsupported(runtime)


def build(runtime, workdir, hooks, cwd, view_root=None):
    """Return ``(env, argv, report)`` for a scoped launch of ``runtime``: env
    to set in the launched session, host argv to append, and the
    ``native_view`` report for the handoff. ``view_root`` places the scoped
    files in ``<view_root>/<workdir name>/`` instead of the workdir."""
    check_supported(runtime)
    target = Path(workdir)
    if view_root is not None:
        root = Path(view_root)
        try:
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            target = root / target.name
            target.mkdir(mode=0o700)
        except OSError as exc:
            raise err_scoped_view_unenforceable(
                runtime, f"cannot create the scoped view under {root}: {exc}")
    env, argv, report = _BUILDERS[runtime](target, list(hooks), cwd)
    return env, argv, {"runtime": runtime, "startup_hooks": list(hooks),
                       "view_dir": str(target), **report}
