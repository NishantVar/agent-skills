"""Agent-definition port resolution.

Bare-name ports live relative to the *target* working directory, never the
skill repo:

  * codex  -> <cwd>/.codex/agents/<name>.toml
  * claude -> <cwd>/.claude/agents/<name>.md

The motivating repo was /Users/nishantvarshney/genesis/flux, whose
.codex/agents and .claude/agents hold the definitions; the skill repo has
none. afork always resolves against --cwd so it works for any caller repo.

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


def resolve_port(adapter, agent, cwd):
    """Return (path_str, text) for the agent's definition, or raise
    port_not_found. ``cwd`` is the already-resolved target directory.

    The agent name must name a file *inside* <cwd>/.<runtime>/agents — it is
    rejected if it contains a path separator or NUL, or if the resolved path
    escapes that directory (e.g. ``../../outside``). Ports never resolve
    outside the agents dir."""
    if not agent or "/" in agent or "\\" in agent or "\x00" in agent:
        raise err_bad_arguments(
            f"agent name {agent!r} must be a bare name, not a path")
    base = (Path(cwd) / f".{adapter.runtime}" / "agents").resolve()
    path = (base / adapter.port_filename(agent)).resolve()
    if not path.is_relative_to(base):
        raise err_bad_arguments(
            f"agent name {agent!r} resolves outside {base}")
    if not path.is_file():
        raise err_port_not_found(adapter.runtime, agent, str(path))
    return str(path), path.read_text()
