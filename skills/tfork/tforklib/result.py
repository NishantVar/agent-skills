"""Deriving the versioned ``launch_outcome`` from what tfork actually saw.

This is the runtime-agnostic half of the contract. tfork holds no runtime or
model table: it contributes generic facts — was a pane created, did the command
reach it, did the sentinels fire, what exit status was recorded, what process
holds the foreground — and combines them with the 0600 sidecar afork wrote,
which is the only place runtime-specific knowledge lives.

The whole point of the exercise is that ``prework_failure`` is *hard* to reach.
A dispatcher may launch a second agent only on that state, so every ambiguity
resolves to ``unknown`` instead. Concretely, none of the following can ever be
elevated: a raw exit status, the free-form ``note`` (never parsed — it is not
an input here at all), unrecognized exit output, a missing or contradictory
marker, an unreadable pane, a missing start sentinel, a start with only a shell
or no foreground, and a delivery that may have had side effects.
"""

from .outcome import (
    DELIVERY_ABSENT,
    DELIVERY_AMBIGUOUS,
    DELIVERY_COMPLETE,
    STATE_STARTED,
    is_shell,
    launch_outcome,
    match_signature,
    prework_failure,
    unknown,
)


def _facts(obs):
    """The four observation fields every outcome echoes back."""
    return {
        "start_sentinel_seen": obs.start_sentinel_seen,
        "end_sentinel_seen": obs.end_sentinel_seen,
        "exit_status": obs.exit_status,
        "foreground": obs.foreground,
    }


def derive_launch_outcome(obs, sidecar=None, delivery=DELIVERY_COMPLETE):
    """Return the version-1 ``launch_outcome`` for one observed fork.

    ``obs`` is a ``verify.Observation``; ``sidecar`` is the parsed afork
    launch contract (or None when the caller forked without one); ``delivery``
    is how far the command got into the pane.
    """
    facts = _facts(obs)

    # 1. Delivery, before anything in the pane means anything. A command that
    #    definitely never landed is a trusted launch failure; one that *may*
    #    have landed is not — re-launching after a partial delivery could leave
    #    two agents running, so possible side effects stay unknown.
    if delivery == DELIVERY_ABSENT:
        return prework_failure("command_delivery_absent", **facts)
    if delivery == DELIVERY_AMBIGUOUS:
        return unknown("delivery_ambiguous", **facts)

    # 2. The pane could not be read at all — we have no observation to reason
    #    from, not evidence of failure.
    if not obs.readable:
        return unknown("observation_timeout", **facts)

    # load_sidecar already guarantees a str-or-None marker, but this function
    # is public and takes a dict — a hand-built one never passed through it,
    # and a wrong-typed marker must degrade to "no marker", never raise.
    marker = sidecar.get("exec_marker") if isinstance(sidecar, dict) else None
    marker_seen = isinstance(marker, str) and bool(marker) and marker in obs.pane_text

    # 3. No start sentinel: the wrapper never announced the command. A marker
    #    without a start sentinel contradicts itself (the marker is printed by
    #    a launcher the wrapper was supposed to have started) — either way,
    #    unknown.
    if not obs.start_sentinel_seen:
        return unknown(
            "contradictory_evidence" if marker_seen else "missing_start_sentinel",
            **facts)

    # 4. The command ran to completion and the wrapper recorded its status.
    if obs.end_sentinel_seen:
        return _classify_exit(obs, sidecar, marker_seen, facts)

    # 5. Started and still going. A live non-shell foreground is the only
    #    evidence that the agent itself is running.
    if obs.foreground is None:
        return unknown("missing_foreground", **facts)
    if is_shell(obs.foreground):
        return unknown("shell_foreground", **facts)
    return launch_outcome(STATE_STARTED, "agent_started", **facts)


def _classify_exit(obs, sidecar, marker_seen, facts):
    """The exit branch: an end sentinel fired, so the process is gone.

    Trusted classification is only attempted for a NON-ZERO exit. A process
    that exited 0 did whatever it did successfully; reading a rejection out of
    the output of a successful run would be inventing evidence.
    """
    if obs.exit_status == 0:
        # A clean exit that also printed the exec-failure marker is
        # self-contradictory — the marker is only reachable on a failed exec,
        # which never exits 0. Refuse to trust either reading.
        return unknown(
            "contradictory_evidence" if marker_seen else "unrecognized_exit",
            **facts)

    # The one trusted runtime-level signal: afork's launcher tried the intended
    # runtime exactly once, that real exec failed, and the launcher printed the
    # contract-bound marker. Nothing else can produce it.
    if marker_seen:
        return prework_failure("runtime_exec_failed", **facts)

    # Adapter-owned signatures, carried in the sidecar. tfork does not know
    # what they mean — it only matches them.
    if match_signature(sidecar, "model_rejected", obs.pane_text):
        return prework_failure("model_rejected", **facts)
    if match_signature(sidecar, "runtime_launch_error", obs.pane_text):
        return prework_failure("runtime_launch_error", **facts)

    # A non-zero exit nobody recognized. This is the common case and it stays
    # unknown on purpose: an exit status alone says nothing about whether the
    # agent began work.
    return unknown("unrecognized_exit", **facts)


def pane_creation_failed():
    """The outcome for a fork that never got a pane at all. Built without an
    ``Observation`` because there was nothing to observe."""
    return prework_failure("pane_creation_failed")
