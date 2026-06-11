"""Agent-definition port resolution.

A bare agent name is searched in two locations, in precedence order:

  1. the *target* working directory (--cwd): <cwd>/.<runtime>/agents/<name>
  2. the user's home config:                 ~/.<runtime>/agents/<name>

  * codex  -> .codex/agents/<name>.toml
  * claude -> .claude/agents/<name>.md

Project-local definitions win over user-global ones — the same project-over-user
precedence Claude Code uses for its own agents. This means `afork claude reviewer`
picks up a `reviewer` defined globally in ~/.claude/agents/ even when the target
repo has no .claude/agents of its own, while a repo-local definition still
shadows the global one. Neither location is the skill repo.

Callers may also pass an explicit definition path. In that mode the path is
expanded independently of --cwd; --cwd remains only the directory where the
agent runs.
"""

import os
from pathlib import Path

from .errors import err_bad_arguments, err_port_not_found


def _port_extension(adapter):
    return Path(adapter.port_filename("agent")).suffix


def _agent_stem(agent):
    return Path(agent.replace("\\", "/")).stem


def _looks_like_explicit_path(adapter, agent):
    if "/" in agent or "\\" in agent:
        return True
    if Path(os.path.abspath(os.path.expanduser(agent))).is_file():
        return True
    return agent.endswith(_port_extension(adapter))


def resolve_agent_definition(adapter, agent, cwd):
    """Return (path_str, text, agent_name) for an agent definition.

    ``agent`` may be either a bare name resolved under <cwd>/.<runtime>/agents
    or an explicit definition path. Explicit paths are an opt-in escape hatch:
    they are expanded relative to the caller process, never relative to --cwd,
    and their filename stem becomes the agent name used downstream.
    """
    if not agent or "\x00" in agent:
        raise err_bad_arguments(
            f"agent name {agent!r} must be a bare name or definition path")

    if _looks_like_explicit_path(adapter, agent):
        path = Path(os.path.abspath(os.path.expanduser(agent)))
        name = _agent_stem(agent)
        if not path.is_file():
            raise err_port_not_found(adapter.runtime, name, str(path))
        expected = _port_extension(adapter)
        if path.suffix != expected:
            raise err_bad_arguments(
                f"agent definition path {str(path)!r} must end with "
                f"{expected!r} for runtime {adapter.runtime!r}")
        return str(path), path.read_text(), name

    path, text = resolve_port(adapter, agent, cwd)
    return path, text, agent


def _agents_bases(adapter, cwd):
    """Bases searched for a bare agent name, in precedence order: the target
    repo first (<cwd>/.<runtime>/agents), then the user's home config
    (~/.<runtime>/agents). Project-local wins. Identical paths are collapsed
    so the home base is skipped when --cwd already is the home directory."""
    bases = []
    for root in (cwd, os.path.expanduser("~")):
        base = (Path(root) / f".{adapter.runtime}" / "agents").resolve()
        if base not in bases:
            bases.append(base)
    return bases


def resolve_port(adapter, agent, cwd):
    """Return (path_str, text) for the agent's definition, or raise
    port_not_found. ``cwd`` is the already-resolved target directory.

    The agent name must name a file *inside* one of the searched agents dirs —
    it is rejected if it contains a path separator or NUL, or if the resolved
    path escapes that directory (e.g. ``../../outside``). Ports never resolve
    outside an agents dir. The repo-local dir is tried before the home one."""
    if not agent or "/" in agent or "\\" in agent or "\x00" in agent:
        raise err_bad_arguments(
            f"agent name {agent!r} must be a bare name, not a path")
    # The separator guard above makes traversal impossible: the port filename
    # is a single path component, so the file always sits directly inside the
    # resolved agents dir. We deliberately do NOT .resolve() the file itself —
    # home agents are commonly symlinks into other repos, and following them
    # must not be mistaken for an escape out of the agents dir.
    searched = []
    for base in _agents_bases(adapter, cwd):
        path = base / adapter.port_filename(agent)
        searched.append(str(path))
        if path.is_file():
            return str(path), path.read_text()
    raise err_port_not_found(adapter.runtime, agent, searched)
