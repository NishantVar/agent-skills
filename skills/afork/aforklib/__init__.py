"""afork — agent-aware fork launcher (front door for ANY coding agent).

Pipeline: pick the runtime adapter -> resolve posture (flag > definition > none)
-> check the adapter can runtime-*enforce* a restricted posture (else fail
closed) -> build the launch command (plain or custom-with-persona) -> return a
``ready_to_fork`` handoff for the tfork skill. afork never forks itself.

The skill is agnostic to runtime flag names; the adapter owns the mapping.
Fail-closed applies ONLY when a *declared restriction* can't be runtime-enforced.
"""

import os
import shutil

from .adapters import _PLACEHOLDER_RUNTIMES, get_adapter
from .errors import (
    err_bad_arguments,
    err_custom_unsupported,
    err_runtime_unsupported,
    err_unenforceable,
    ready_to_fork,
)
from .launch import build_launch
from .persona import compose_persona
from .resolve import resolve_agent_definition

# Effort tokens recognized when splitting a combined --model spec like
# "fable max" or "gpt-5.3-codex xhigh" into model + effort. This set only
# decides what splits off; the runtime validates the actual values.
_EFFORT_TOKENS = {"minimal", "low", "medium", "high", "xhigh", "max"}


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
              observe=False, obs_tags=None):
    """Resolve, enforce, and return one handoff dict. Raises AforkError on any
    fail-closed or resolution failure."""
    cwd = os.path.abspath(os.path.expanduser(cwd)) if cwd else os.getcwd()

    wrap, tags, obs_warning = _resolve_observability(observe, obs_tags)

    adapter = get_adapter(runtime)
    if adapter is None:
        reason = ("named in the design brief but has no adapter yet"
                  if runtime in _PLACEHOLDER_RUNTIMES else "unknown runtime")
        raise err_runtime_unsupported(runtime, reason)

    # --- Mode: plain (no agent) vs custom (definition-backed). ---
    parsed = {}
    agent_name = None
    if agent is not None:
        if not adapter.has_agent_dir:
            raise err_custom_unsupported(
                runtime,
                f"{runtime} has no agent-definition directory; launch plain "
                f"`afork {runtime}` or inject persona another way.")
        path, text, agent_name = resolve_agent_definition(adapter, agent, cwd)
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
    # its charter with the shared identity+precedence+posture preamble and the
    # cwd-aware startup-read block; plain forks keep the empty-persona path. ---
    if agent is not None:
        persona = compose_persona(agent_name, adapter.persona_body(parsed), cwd)
    else:
        persona = ""

    command, workdir = build_launch(
        adapter, agent_name, posture, model, effort, persona,
        observe=wrap, obs_tags=tags)
    return ready_to_fork(
        runtime=runtime,
        agent=agent_name,
        posture=posture,
        command=command,
        title=title or agent_name or runtime,
        cwd=cwd,
        workdir=workdir,
        enforced=enforced,
        placement=placement,
        observed=wrap if observe else None,
        obs_tags=tags or None,
        obs_warning=obs_warning,
    )
