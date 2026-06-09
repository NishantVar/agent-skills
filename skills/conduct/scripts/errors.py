"""The shared handoff-JSON contract.

Every conduct command — ok or not — prints exactly one JSON object on stdout
in the envelope shape p2p/afork/tfork use:

  { "ok": ..., "code": ..., "human_message": ..., "agent_instruction": ...,
    "action_required": ..., "handoff_skill": ..., "rerun_argv": [...],
    "retryable": ... }  plus per-code extras.

The helpers here are the ONLY places that construct an ``ok:false`` envelope,
so the shape stays stable. conduct never shells out to another skill; cross-skill
needs are expressed as a handoff with ``handoff_skill`` set and an
``agent_instruction`` the calling agent follows (it, not conduct, invokes the
other skill).
"""

from __future__ import annotations

from typing import Any, Optional

# Non-zero exit code per failure code, mirroring afork's taxonomy.
EXIT_CODES = {
    "bad_arguments": 2,
    "not_in_cmux": 3,
    "target_unknown": 4,
    "owned_by_other": 5,
    "not_owner": 6,
    "runtime_unknown": 7,
    "verb_unsupported": 8,
    "cmux_failed": 9,
}


def handoff(code: str, human: str, instruction: str, *,
            action: str = "none", retryable: bool = False,
            handoff_skill: Optional[str] = None,
            rerun_argv: Optional[list] = None,
            **extra: Any) -> dict:
    out: dict[str, Any] = {
        "ok": False,
        "code": code,
        "human_message": human,
        "agent_instruction": instruction,
        "action_required": action,
        "handoff_skill": handoff_skill,
        "rerun_argv": rerun_argv or [],
        "retryable": retryable,
    }
    out.update(extra)
    return out


def not_in_cmux() -> dict:
    return handoff(
        "not_in_cmux",
        "conduct could not resolve the caller's own cmux surface UUID, so it "
        "cannot establish an owner identity.",
        "Terminal — do not retry as-is. The calling process cannot fix its own "
        "environment. Run conduct from inside a cmux pane (the wrapper sets "
        "$CMUX_SURFACE_ID for child processes), or export "
        "CMUX_SURFACE_ID=<surface-uuid> before launching the agent.",
        action="none",
        retryable=False,
    )


def target_unknown(agent_ref: str, rerun_argv: Optional[list] = None) -> dict:
    return handoff(
        "target_unknown",
        f"No live cmux surface matched {agent_ref!r}.",
        "Do not retry verbatim. The surface:N alias may have reindexed or the "
        "pane may be gone. Re-resolve the target (cmux tree) and rerun with a "
        "live surface ref or its UUID. Prefer the UUID for durability.",
        action="pick_target",
        retryable=True,
        rerun_argv=rerun_argv or [],
        agent=agent_ref,
    )


def owned_by_other(target_uuid: str, owner_uuid: str,
                   rerun_argv: Optional[list] = None) -> dict:
    """Fail-closed: a live surface is already owned by a different caller.
    No steal — ownership is exclusive (spec §3.2)."""
    return handoff(
        "owned_by_other",
        f"Surface {target_uuid} is already owned by {owner_uuid}. Ownership is "
        "exclusive and conduct will not steal it.",
        "Do NOT retry to force a takeover. If the current owner is gone its "
        "claim self-expires (orphan-reclaim) and a later touch succeeds. For a "
        "deliberate transfer, have the current owner run `conduct release "
        "--agent <ref>` first, then claim.",
        action="abort",
        retryable=False,
        rerun_argv=rerun_argv or [],
        target=target_uuid,
        owner=owner_uuid,
    )


def not_owner(target_uuid: str, owner_uuid: Optional[str],
              rerun_argv: Optional[list] = None) -> dict:
    """A control/release verb was issued against a surface the caller does not
    own and cannot first-touch (it is live-owned by someone else)."""
    who = f" (owned by {owner_uuid})" if owner_uuid else ""
    return handoff(
        "not_owner",
        f"You do not own surface {target_uuid}{who}, so this operation is "
        "refused.",
        "Reads and lifecycle verbs are scoped to your owned set. First-touch a "
        "surface via `conduct status --agent <ref>` to claim it (only when it "
        "is unowned or orphaned), or operate on a surface you already own.",
        action="abort",
        retryable=False,
        rerun_argv=rerun_argv or [],
        target=target_uuid,
        owner=owner_uuid,
    )


def runtime_unknown(target_uuid: str, observed: Optional[str],
                    rerun_argv: Optional[list] = None) -> dict:
    """Fail-closed lifecycle refusal: conduct cannot identify the target's
    runtime, so it will not inject anything (spec §5.2)."""
    seen = f" Observed foreground process(es): {observed}." if observed else ""
    return handoff(
        "runtime_unknown",
        f"Could not identify a supported coding-agent runtime "
        f"(claude/codex/pi) on surface {target_uuid}.{seen} conduct refuses to "
        "inject keystrokes blindly.",
        "Do NOT retry to force injection. Verify the pane is actually running a "
        "supported agent (not a shell, editor, or REPL). Blind injection into a "
        "non-agent surface is harmful; this is a deliberate fail-closed refusal.",
        action="abort",
        retryable=False,
        rerun_argv=rerun_argv or [],
        target=target_uuid,
        observed=observed,
    )


def verb_unsupported(verb: str, runtime: str, target_uuid: str,
                     rerun_argv: Optional[list] = None) -> dict:
    """The target's runtime has no keystroke mapping for this verb."""
    return handoff(
        "verb_unsupported",
        f"The {runtime!r} runtime on surface {target_uuid} has no supported "
        f"keystroke sequence for verb {verb!r}.",
        "Do NOT improvise a keystroke. conduct only injects verbs it can map to "
        "a known sequence for the detected runtime. Use a verb that runtime "
        "supports, or handle this control action manually.",
        action="abort",
        retryable=False,
        rerun_argv=rerun_argv or [],
        verb=verb,
        runtime=runtime,
        target=target_uuid,
    )


def cmux_failed(detail: str, rerun_argv: Optional[list] = None) -> dict:
    return handoff(
        "cmux_failed",
        f"A cmux call failed: {detail}",
        "Inspect cmux state (is the daemon up? is the surface still live?) and "
        "rerun the same command.",
        action="none",
        retryable=True,
        rerun_argv=rerun_argv or [],
    )


def bad_arguments(detail: str) -> dict:
    return handoff(
        "bad_arguments",
        f"Invalid arguments: {detail}.",
        "Do not retry verbatim. Fix the invocation and call again.",
        action="abort",
        retryable=False,
    )
