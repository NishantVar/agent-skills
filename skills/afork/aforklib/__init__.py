"""afork — agent-aware fork launcher (front door for ANY coding agent).

Pipeline: pick the runtime adapter -> resolve posture (flag > definition > none)
-> check the adapter can runtime-*enforce* a restricted posture (else fail
closed) -> build the launch command (plain or custom-with-persona) -> write the
0600 launch-contract sidecar -> return a ``ready_to_fork`` handoff for the tfork
skill. afork never forks itself.

afork is the side that owns *runtime* knowledge, so the sidecar is where that
knowledge crosses to tfork: which runtime/model were really invoked, the
generated launcher's exec-failure marker, and the adapter's model-rejection and
launch-error signatures. tfork stays runtime-agnostic and only matches what the
sidecar hands it. See ``outcome.py``.

The skill is agnostic to runtime flag names; the adapter owns the mapping.
Fail-closed applies ONLY when a *declared restriction* can't be runtime-enforced.
"""

import json
import os
import re
import shutil

from .adapters import _PLACEHOLDER_RUNTIMES, get_adapter
from .errors import (
    err_bad_arguments,
    err_custom_unsupported,
    err_runtime_unsupported,
    err_unenforceable,
    ready_to_fork,
)
from . import native_view
from .launch import build_launch
from .persona import compose_persona
from .resolve import resolve_agent_definition

# Effort tokens recognized when splitting a combined --model spec like
# "fable max" or "gpt-5.3-codex xhigh" into model + effort. This set only
# decides what splits off; the runtime validates the actual values.
_EFFORT_TOKENS = {"minimal", "low", "medium", "high", "xhigh", "max"}

# The Flux agent-name rule FLUX_ROLE_ID must satisfy: [A-Za-z0-9._-]+, no
# leading dot. The session's start step refuses anything else, so --role
# refuses it here first rather than launching an agent that loses its name.
_ROLE_RE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]*")
_MCP_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")


def _parse_mcp_servers(specs):
    """Each --mcp-server is a JSON object ``{"name", "command", "args"?}``
    naming one stdio MCP server for this session only."""
    servers = []
    for spec in specs or []:
        try:
            value = json.loads(spec)
        except ValueError:
            raise err_bad_arguments(f"--mcp-server {spec!r} is not JSON")
        if not isinstance(value, dict) or set(value) - {"name", "command", "args"}:
            raise err_bad_arguments(
                f"--mcp-server {spec!r} must be an object with name, command "
                "and optional args")
        name, command = value.get("name"), value.get("command")
        args = value.get("args", [])
        if not isinstance(name, str) or not _MCP_NAME_RE.fullmatch(name):
            raise err_bad_arguments(f"--mcp-server name {name!r} must match [A-Za-z0-9_-]+")
        if not isinstance(command, str) or not command:
            raise err_bad_arguments(f"--mcp-server {name!r} needs a non-empty command")
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise err_bad_arguments(f"--mcp-server {name!r} args must be a list of strings")
        if any(s["name"] == name for s in servers):
            raise err_bad_arguments(f"--mcp-server {name!r} is given twice")
        servers.append({"name": name, "command": command, "args": list(args)})
    return servers


def _split_model_spec(model, effort):
    """Split a combined --model spec ("fable max") into (model, effort).
    An explicit --effort wins; the spec's trailing effort token fills in
    only when --effort is unset."""
    if model:
        parts = model.split()
        if len(parts) > 1 and parts[-1].lower() in _EFFORT_TOKENS:
            model = " ".join(parts[:-1])
            effort = effort or parts[-1].lower()
    return model, effort


def _parse_obs_tags(observe, obs_tags):
    """Turn the repeatable --obs-tag values into an ordered {k: v} dict.

    A tag without --observe is a mistake, not a silent no-op: the caller asked
    for attribution it would never get. Commas are rejected because
    AGENTLENS_TAGS is a comma-separated wire format — one would silently split a
    tag in two."""
    raw = list(obs_tags or [])
    if raw and not observe:
        raise err_bad_arguments(
            "--obs-tag requires --observe (tags are only attached when the "
            "launch is wrapped with agentlens)")
    tags = {}
    for item in raw:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise err_bad_arguments(f"--obs-tag {item!r} must be k=v")
        if "," in key or "," in value:
            raise err_bad_arguments(
                f"--obs-tag {item!r} must not contain a comma (AGENTLENS_TAGS "
                "is comma-separated)")
        tags[key] = value
    return tags


def _resolve_observability(observe, obs_tags):
    """Return (wrap, tags, warning). Fail-open: --observe with no `lens` on PATH
    builds the command UNWRAPPED and warns. Observability is not a security
    posture — a missing observer must never block a launch."""
    tags = _parse_obs_tags(observe, obs_tags)
    if not observe:
        return False, None, None
    if shutil.which("lens") is None:
        return False, tags, (
            "--observe was requested but the `lens` binary (agentlens) is not "
            "on PATH; the command was built UNWRAPPED and will run without "
            "observability. Install agentlens to capture this launch.")
    return True, tags, None


def run_afork(runtime, agent=None, permission=None, model=None, effort=None,
              title=None, cwd=None, placement=None, allow_unenforced=False,
              observe=False, obs_tags=None, role=None, scoped_view=False,
              startup_hooks=None, mcp_servers=None):
    """Resolve, enforce, and return one handoff dict. Raises AforkError on any
    fail-closed or resolution failure.

    ``role`` names the role for a launch with no port. A port launch is
    already named by its port, so passing both is a bad_arguments error.

    ``scoped_view`` hides personal/plugin skills and competing startup hooks
    from the launched session for this launch only, keeping ``startup_hooks``
    (the SessionStart hook commands the caller needs) — see ``native_view``.

    ``mcp_servers`` are JSON ``--mcp-server`` specs: stdio MCP servers this
    session gets through launch flags, with no configuration written."""
    cwd = os.path.abspath(os.path.expanduser(cwd)) if cwd else os.getcwd()

    wrap, tags, obs_warning = _resolve_observability(observe, obs_tags)

    if role is not None:
        if agent is not None:
            raise err_bad_arguments(
                "--role names a launch with no agent definition; a port launch "
                "is already named by its port")
        if not _ROLE_RE.fullmatch(role):
            raise err_bad_arguments(
                f"--role {role!r} breaks the agent-name rule "
                "[A-Za-z0-9._-]+, no leading dot")

    startup_hooks = list(startup_hooks or [])
    if startup_hooks and not scoped_view:
        raise err_bad_arguments("--startup-hook requires --scoped-view")
    if scoped_view and not startup_hooks:
        raise err_bad_arguments(
            "--scoped-view needs at least one --startup-hook: a scoped session "
            "runs only the startup hooks it is given")

    adapter = get_adapter(runtime)
    if adapter is None:
        reason = ("named in the design brief but has no adapter yet"
                  if runtime in _PLACEHOLDER_RUNTIMES else "unknown runtime")
        raise err_runtime_unsupported(runtime, reason)

    servers = _parse_mcp_servers(mcp_servers)
    if servers and not hasattr(adapter, "mcp_flags"):
        raise err_bad_arguments(
            f"--mcp-server is not supported for {runtime}; claude and codex take it")

    if scoped_view:
        native_view.check_supported(runtime)

    # --- Mode: plain (no agent) vs custom (definition-backed). ---
    parsed = {}
    agent_name = None
    deprecation_warning = None
    if agent is not None:
        if not adapter.has_agent_dir:
            raise err_custom_unsupported(
                runtime,
                f"{runtime} has no agent-definition directory; launch plain "
                f"`afork {runtime}` or inject persona another way.")
        path, text, agent_name, deprecation_warning = resolve_agent_definition(
            adapter, agent, cwd)
        parsed = adapter.parse(text, agent_name, path)

    # --- Posture precedence: --permission > definition-declared > none. ---
    posture = permission or adapter.declared_posture(parsed) or "none"

    # --- Enforceability: a restricted posture the adapter can't prove fails closed. ---
    enforced = True
    if posture != "none":
        if not adapter.enforceable(posture):
            if not allow_unenforced:
                raise err_unenforceable(
                    runtime, agent_name, posture,
                    reason=(f"the {runtime} adapter has no runtime-enforced "
                            f"{posture!r} mechanism this round."))
            enforced = False

    # --- Resolve model/effort: arg > def-declared > adapter default. ---
    model, effort = _split_model_spec(model, effort)
    model = model or adapter.declared_model(parsed) or adapter.default_model
    effort = effort or adapter.declared_effort(parsed) or adapter.default_effort

    # --- Persona: only custom mode carries one. A definition-backed fork leads
    # its charter with the shared identity+precedence+posture preamble; plain
    # forks keep the empty-persona path. ---
    if agent is not None:
        persona = compose_persona(agent_name, adapter.persona_body(parsed))
    else:
        persona = ""

    view = {}

    def scope(workdir):
        env, argv, view["report"] = native_view.build(
            runtime, workdir, startup_hooks, cwd)
        return env, argv

    launch = build_launch(
        adapter, agent_name, posture, model, effort, persona,
        observe=wrap, obs_tags=tags, role_id=agent_name or role,
        scoped_view=scope if scoped_view else None, mcp_servers=servers)
    return ready_to_fork(
        runtime=runtime,
        agent=agent_name,
        posture=posture,
        command=launch.command,
        title=title or agent_name or role or runtime,
        cwd=cwd,
        workdir=launch.workdir,
        enforced=enforced,
        placement=placement,
        observed=wrap if observe else None,
        obs_tags=tags or None,
        obs_warning=obs_warning,
        launch_contract=launch.launch_contract,
        attempt_id=launch.attempt_id,
        persona=bool(persona),
        deprecation_warning=deprecation_warning,
        native_view=view.get("report"),
    )
