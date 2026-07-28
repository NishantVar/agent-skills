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

One transitional exception exists: the generic legacy Claude ``-agent`` bridge.
See ``_legacy_stem`` below.
"""

import os
from pathlib import Path

from .errors import AforkError, err_bad_arguments, err_port_not_found

# Claude ports historically carried a redundant ``-agent`` suffix that Codex
# ports never had, so the same role needed two different names. The suffix is
# gone; this bridge keeps callers that still pass the old name working for one
# release/upgrade cycle. Removing it is a separate, separately-reviewed cleanup.
LEGACY_CLAUDE_SUFFIX = "-agent"


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


def _legacy_stem(adapter, agent):
    """The suffixless stem a legacy Claude ``<role>-agent`` request bridges to,
    or None when the bridge does not apply.

    Generic by construction: it strips one known suffix, with no per-role name
    map anywhere. Claude only — Codex ports were always suffixless, so giving
    Codex an inverse alias would invent a name that never existed.
    """
    if adapter.runtime != "claude":
        return None
    if not agent.endswith(LEGACY_CLAUDE_SUFFIX):
        return None
    return agent[:-len(LEGACY_CLAUDE_SUFFIX)] or None


def _legacy_warning(requested, canonical):
    return (
        f"Deprecated agent name: {requested!r} did not resolve, so afork fell "
        f"back to the suffixless port {canonical!r}. The '-agent' suffix is no "
        f"longer part of a runtime agent name; this bridge is removed after "
        f"one release/upgrade cycle. Pass {canonical!r} instead.")


def resolve_agent_definition(adapter, agent, cwd):
    """Return (path_str, text, agent_name, deprecation_warning).

    ``agent`` may be either a bare name resolved under <cwd>/.<runtime>/agents
    or an explicit definition path. Explicit paths are an opt-in escape hatch:
    they are expanded relative to the caller process, never relative to --cwd,
    and their filename stem becomes the agent name used downstream.

    Exact-name lookup always runs first, across *both* search bases. Only when
    it misses everywhere does the legacy Claude ``-agent`` bridge retry the
    suffixless stem — so an exact ``<role>-agent`` definition, wherever it
    lives, still wins. When the bridge fires, the returned agent name is the
    suffixless canonical one and the fourth element is a deprecation warning
    (None on every other path).
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
        return str(path), path.read_text(), name, None

    try:
        path, text = resolve_port(adapter, agent, cwd)
    except AforkError as exact_exc:
        stem = None
        if exact_exc.code == "port_not_found":
            stem = _legacy_stem(adapter, agent)
        if stem is None:
            raise
        try:
            path, text = resolve_port(adapter, stem, cwd)
        except AforkError as stem_exc:
            if stem_exc.code != "port_not_found":
                raise
            # Neither name exists. Report every path tried under the name the
            # caller actually asked for, so the bridge is visible in the error
            # rather than silently swallowing half the search.
            raise err_port_not_found(
                adapter.runtime, agent,
                exact_exc.extras["searched"] + stem_exc.extras["searched"],
            ) from None
        return path, text, stem, _legacy_warning(agent, stem)
    return path, text, agent, None


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
