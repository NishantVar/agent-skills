"""Agent-definition port resolution.

Ports live relative to the *target* working directory, never the skill repo:

  * codex  -> <cwd>/.codex/agents/<name>.toml
  * claude -> <cwd>/.claude/agents/<name>.md

The motivating repo was /Users/nishantvarshney/genesis/flux, whose
.codex/agents and .claude/agents hold the definitions; the skill repo has
none. afork always resolves against --cwd so it works for any caller repo.
"""

from pathlib import Path

from .errors import err_bad_arguments, err_port_not_found


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
