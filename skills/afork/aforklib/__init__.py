"""afork — agent-aware fork launcher (front door for ANY coding agent).

Pipeline: pick the runtime adapter -> resolve posture (flag > definition > none)
-> check the adapter can runtime-*enforce* a restricted posture (else fail
closed) -> build the launch command (plain or custom-with-persona) -> return a
``ready_to_fork`` handoff for the tfork skill. afork never forks itself.

The skill is agnostic to runtime flag names; the adapter owns the mapping.
Fail-closed applies ONLY when a *declared restriction* can't be runtime-enforced.
"""

import os

from .adapters import _PLACEHOLDER_RUNTIMES, get_adapter
from .errors import (
    err_bad_arguments,
    err_custom_unsupported,
    err_runtime_unsupported,
    err_unenforceable,
    ready_to_fork,
)
from .launch import build_launch
from .resolve import resolve_agent_definition

# Effort tokens recognized when splitting a combined --model spec like
# "fable max" or "gpt-5.3-codex xhigh" into model + effort. This set only
# decides what splits off; the runtime validates the actual values.
_EFFORT_TOKENS = {"minimal", "low", "medium", "high", "xhigh", "max"}


def _normalize_context_window(context_window):
    """Normalize supported --context-window spellings."""
    if context_window is None:
        return None
    value = str(context_window).strip().lower()
    if value in ("1m", "1000000"):
        return "1m"
    raise err_bad_arguments(
        f"--context-window {context_window!r} must be '1m' or '1000000'")


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


def run_afork(runtime, agent=None, permission=None, model=None, effort=None,
              title=None, cwd=None, placement=None, allow_unenforced=False,
              context_window=None):
    """Resolve, enforce, and return one handoff dict. Raises AforkError on any
    fail-closed or resolution failure."""
    cwd = os.path.abspath(os.path.expanduser(cwd)) if cwd else os.getcwd()

    adapter = get_adapter(runtime)
    if adapter is None:
        reason = ("named in the design brief but has no adapter yet"
                  if runtime in _PLACEHOLDER_RUNTIMES else "unknown runtime")
        raise err_runtime_unsupported(runtime, reason)

    context_window = _normalize_context_window(context_window)
    if context_window and not adapter.supports_context_window:
        raise err_bad_arguments(
            f"--context-window is not supported for runtime {runtime!r}")

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

    # --- Persona: only custom mode carries one. ---
    persona = adapter.persona_body(parsed) if agent is not None else ""

    command, workdir = build_launch(
        adapter, agent_name, posture, model, effort, persona,
        context_window=context_window)
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
    )
