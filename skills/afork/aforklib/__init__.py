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
    err_custom_unsupported,
    err_runtime_unsupported,
    err_unenforceable,
    ready_to_fork,
)
from .launch import build_launch
from .resolve import resolve_port


def run_afork(runtime, agent=None, permission=None, model=None, effort=None,
              title=None, cwd=None, placement=None, allow_unenforced=False):
    """Resolve, enforce, and return one handoff dict. Raises AforkError on any
    fail-closed or resolution failure."""
    cwd = os.path.abspath(os.path.expanduser(cwd)) if cwd else os.getcwd()

    adapter = get_adapter(runtime)
    if adapter is None:
        reason = ("named in the design brief but has no adapter yet"
                  if runtime in _PLACEHOLDER_RUNTIMES else "unknown runtime")
        raise err_runtime_unsupported(runtime, reason)

    # --- Mode: plain (no agent) vs custom (definition-backed). ---
    parsed = {}
    if agent is not None:
        if not adapter.has_agent_dir:
            raise err_custom_unsupported(
                runtime,
                f"{runtime} has no agent-definition directory; launch plain "
                f"`afork {runtime}` or inject persona another way.")
        path, text = resolve_port(adapter, agent, cwd)
        parsed = adapter.parse(text, agent, path)

    # --- Posture precedence: --permission > definition-declared > none. ---
    posture = permission or adapter.declared_posture(parsed) or "none"

    # --- Enforceability: a restricted posture the adapter can't prove fails closed. ---
    enforced = True
    if posture != "none":
        if not adapter.enforceable(posture):
            if not allow_unenforced:
                raise err_unenforceable(
                    runtime, agent, posture,
                    reason=(f"the {runtime} adapter has no runtime-enforced "
                            f"{posture!r} mechanism this round."))
            enforced = False

    # --- Resolve model/effort: arg > def-declared > adapter default. ---
    model = model or adapter.declared_model(parsed) or adapter.default_model
    effort = effort or adapter.declared_effort(parsed) or adapter.default_effort

    # --- Persona: only custom mode carries one. ---
    persona = adapter.persona_body(parsed) if agent is not None else ""

    command, workdir = build_launch(
        adapter, agent, posture, model, effort, persona)
    return ready_to_fork(
        runtime=runtime,
        agent=agent,
        posture=posture,
        command=command,
        title=title or agent or runtime,
        cwd=cwd,
        workdir=workdir,
        enforced=enforced,
        placement=placement,
    )
