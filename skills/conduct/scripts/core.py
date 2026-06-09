"""conduct — the cmux control plane.

Status aggregation + runtime-aware lifecycle/interrupt control over the caller's
owned set of agents. conduct never spawns (tfork/afork), never messages
(p2p), and never shells out to another skill — cross-skill needs are returned as
handoff JSON for the calling agent to act on.

This module wires the four pieces together:
  * cmux.py        — the only place that talks to cmux (the portable seam)
  * ownership.py   — UUID-keyed first-touch manifest under an advisory lock
  * adapters.py    — per-runtime verb -> keystroke mapping (fail-closed)
  * errors.py      — the shared handoff envelope

Every public ``run_*`` returns one dict in the envelope shape.
"""

from __future__ import annotations

import time
from typing import Optional, Tuple

import adapters
import cmux
import errors
import ownership

# Lifecycle verbs that inject into / act on a running runtime.
LIFECYCLE_VERBS = ("clear", "compact", "exit", "kill", "interrupt")

# Pause between keystroke steps so the target TUI ingests each one (mirrors
# p2p's transport pacing — without it the input races and gets dropped).
_STEP_PAUSE = 0.3


# ---------------- shared preamble ----------------

def _caller_uuid() -> Optional[str]:
    return cmux.caller_surface_uuid()


def _resolve_and_own(
    agent_ref: str, caller_uuid: str, rerun_argv,
) -> Tuple[Optional[str], dict, Optional[dict]]:
    """Resolve a --agent ref to a live UUID, then run the first-touch
    ownership decision under the lock. Returns (target_uuid, record, error).

    On success ``error`` is None and (target_uuid, record) are both populated.
    On failure ``error`` is a ready handoff dict (target_unknown or
    owned_by_other), ``record`` is ``{}``, and the caller returns the error
    directly. ``record`` is never None so callers can ``.get`` it safely.
    """
    t = cmux.tree()
    idx = cmux.surface_index(t)
    target_uuid = cmux.resolve_to_uuid(agent_ref, t)
    if target_uuid is None:
        return None, {}, errors.target_unknown(agent_ref, rerun_argv)

    live = set(idx.keys())
    with ownership.manifest_lock():
        manifest = ownership.load()
        res = ownership.resolve_ownership(target_uuid, caller_uuid, live,
                                          manifest)
        if not res.ok:
            # owned_by_other always carries the conflicting owner UUID.
            owner = res.owner or "<unknown>"
            return target_uuid, {}, errors.owned_by_other(
                target_uuid, owner, rerun_argv)
        ownership.save(manifest)
    return target_uuid, idx.get(target_uuid) or {}, None


def _context_and_state(record: dict, runtime: Optional[str]):
    """Per-runtime context% + coarse state, from a SINGLE screen read.

    Returns (context_pct, state). context_pct is the percent of context USED
    (claude `ctx:NN%`; codex `Context NN% left` converted to used); state is a
    coarse "busy" when the runtime shows an interrupt affordance, else None.
    Both are None for a runtime with no adapter."""
    adapter = adapters.get_adapter(runtime)
    if adapter is None:
        return None, None
    screen = cmux.read_screen(record.get("surface_ref", ""),
                              record.get("workspace_ref") or None)
    return adapter.context_pct(screen), adapter.state(screen)


def _agent_view(target_uuid: str, record: dict, proc_map: dict) -> dict:
    """The per-agent status row: context% + runtime type + state + title +
    current workspace, all derived live."""
    runtime = adapters.runtime_from_processes(proc_map.get(target_uuid, []))
    context_pct, state = _context_and_state(record, runtime)
    return {
        "uuid": target_uuid,
        "surface_ref": record.get("surface_ref", ""),
        "title": record.get("title", ""),
        "type": runtime,  # claude / codex / pi / None
        "surface_type": record.get("type", ""),  # terminal / browser
        "state": state,  # "busy" when an interrupt affordance is shown, else null
        "workspace_ref": record.get("workspace_ref", ""),
        "workspace_title": record.get("workspace_title", ""),
        "context_pct": context_pct,
    }


# ---------------- status ----------------

def run_status(agent_ref: Optional[str] = None, all_owned: bool = False,
               rerun_argv=None) -> dict:
    caller = _caller_uuid()
    if caller is None:
        return errors.not_in_cmux()

    t = cmux.tree()
    idx = cmux.surface_index(t)
    proc_map = cmux.runtime_processes()
    live = set(idx.keys())

    if all_owned:
        # Owned-set only (spec §4) — never an ungated workspace/all read.
        with ownership.manifest_lock():
            manifest = ownership.load()
            targets = ownership.owned_targets(caller, live, manifest)
        agents = [_agent_view(u, idx.get(u, {}), proc_map) for u in targets]
        return {
            "ok": True,
            "action": "status",
            "scope": "owned_set",
            "owner": caller,
            "count": len(agents),
            "agents": agents,
            "human_message": (
                f"conduct status over your owned set: {len(agents)} agent(s)."),
        }

    # Single agent: touching to read IS the first-touch claim. The CLI
    # guarantees agent_ref is set here (this path is mutually exclusive with
    # --all), so it is never None.
    assert agent_ref is not None
    target_uuid, record, err = _resolve_and_own(agent_ref, caller, rerun_argv)
    if err is not None or target_uuid is None:
        return err if err is not None else errors.target_unknown(
            agent_ref, rerun_argv)
    view = _agent_view(target_uuid, record, proc_map)
    return {
        "ok": True,
        "action": "status",
        "scope": "agent",
        "owner": caller,
        "agent": view,
        "human_message": (
            f"conduct status for {view['surface_ref'] or target_uuid} "
            f"(runtime: {view['type']}, context: {view['context_pct']}%)."),
    }


# ---------------- claim / release ----------------

def run_claim(agent_ref: str, rerun_argv=None) -> dict:
    caller = _caller_uuid()
    if caller is None:
        return errors.not_in_cmux()
    target_uuid, record, err = _resolve_and_own(agent_ref, caller, rerun_argv)
    if err is not None or target_uuid is None:
        return err if err is not None else errors.target_unknown(
            agent_ref, rerun_argv)
    return {
        "ok": True,
        "action": "claim",
        "owner": caller,
        "target": target_uuid,
        "surface_ref": record.get("surface_ref", ""),
        "title": record.get("title", ""),
        "human_message": (
            f"You own {record.get('surface_ref') or target_uuid}."),
    }


def run_release(agent_ref: str, rerun_argv=None) -> dict:
    caller = _caller_uuid()
    if caller is None:
        return errors.not_in_cmux()
    t = cmux.tree()
    idx = cmux.surface_index(t)
    target_uuid = cmux.resolve_to_uuid(agent_ref, t)
    if target_uuid is None:
        return errors.target_unknown(agent_ref, rerun_argv)
    live = set(idx.keys())
    with ownership.manifest_lock():
        manifest = ownership.load()
        res = ownership.release(target_uuid, caller, live, manifest)
        if res.status == "owned_by_other":
            return errors.owned_by_other(
                target_uuid, res.owner or "<unknown>", rerun_argv)
        ownership.save(manifest)
    return {
        "ok": True,
        "action": "release",
        "owner": caller,
        "target": target_uuid,
        "released": res.status == "released",
        "human_message": (
            f"Released claim on {target_uuid}." if res.status == "released"
            else f"No claim of yours existed on {target_uuid}."),
    }


# ---------------- lifecycle (runtime-aware, fail-closed) ----------------

def _dispatch_sequence(record: dict, sequence) -> None:
    """Inject one atomic keystroke sequence into a surface. Raises CmuxError on
    any failed step (a half-delivered sequence must surface loudly)."""
    surface_ref = record.get("surface_ref", "")
    workspace_ref = record.get("workspace_ref") or None
    for kind, value in sequence:
        if kind == "text":
            cmux.send_text(surface_ref, workspace_ref, value)
        elif kind == "key":
            cmux.send_key(surface_ref, workspace_ref, value)
        elif kind == "close":
            cmux.close_surface(surface_ref, workspace_ref)
        time.sleep(_STEP_PAUSE)


def _lifecycle_one(verb: str, target_uuid: str, record: dict,
                   proc_map: dict, rerun_argv) -> dict:
    """Apply one lifecycle verb to one already-owned target. Returns a per-
    target result dict (ok or a refuse handoff)."""
    runtime = adapters.runtime_from_processes(proc_map.get(target_uuid, []))
    adapter = adapters.get_adapter(runtime)
    if adapter is None or runtime is None:
        return errors.runtime_unknown(
            target_uuid, ", ".join(proc_map.get(target_uuid, [])) or None,
            rerun_argv)
    if not adapter.supports(verb):
        return errors.verb_unsupported(verb, runtime, target_uuid, rerun_argv)
    try:
        _dispatch_sequence(record, adapter.sequence(verb))
    except cmux.CmuxError as exc:
        return errors.cmux_failed(str(exc), rerun_argv)
    return {
        "ok": True,
        "action": verb,
        "target": target_uuid,
        "surface_ref": record.get("surface_ref", ""),
        "runtime": runtime,
        "human_message": (
            f"Injected {verb!r} into {record.get('surface_ref') or target_uuid} "
            f"({runtime})."),
    }


def run_lifecycle(verb: str, agent_ref: Optional[str] = None,
                  all_owned: bool = False, rerun_argv=None) -> dict:
    if verb not in LIFECYCLE_VERBS:
        return errors.bad_arguments(f"unknown lifecycle verb {verb!r}")
    caller = _caller_uuid()
    if caller is None:
        return errors.not_in_cmux()

    t = cmux.tree()
    idx = cmux.surface_index(t)
    proc_map = cmux.runtime_processes()
    live = set(idx.keys())

    if all_owned:
        # Broadcast over the OWNED SET ONLY (spec §4) — never ungated.
        with ownership.manifest_lock():
            manifest = ownership.load()
            targets = ownership.owned_targets(caller, live, manifest)
        results = []
        for u in targets:
            results.append(
                _lifecycle_one(verb, u, idx.get(u, {}), proc_map, rerun_argv))
        applied = sum(1 for r in results if r.get("ok"))
        return {
            "ok": True,
            "action": verb,
            "scope": "owned_set",
            "owner": caller,
            "count": len(targets),
            "applied": applied,
            "results": results,
            "human_message": (
                f"Broadcast {verb!r} over owned set: {applied}/{len(targets)} "
                "applied (refusals are per-target, fail-closed)."),
        }

    # Single owned target. Control requires ownership; first-touch a live-
    # unowned/orphaned surface, refuse a surface owned by someone else. The CLI
    # guarantees agent_ref is set on this (non---all) path.
    assert agent_ref is not None
    target_uuid, record, err = _resolve_and_own(agent_ref, caller, rerun_argv)
    if err is not None:
        # _resolve_and_own returns owned_by_other; reshape to not_owner for
        # the control path so the message names the right policy.
        if err.get("code") == "owned_by_other" and target_uuid is not None:
            return errors.not_owner(target_uuid, err.get("owner"), rerun_argv)
        return err
    if target_uuid is None:
        return errors.target_unknown(agent_ref, rerun_argv)
    return _lifecycle_one(verb, target_uuid, record, proc_map, rerun_argv)
