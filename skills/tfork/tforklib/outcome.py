"""The versioned launch-outcome contract — shared, byte-identical, by afork
and tfork.

THIS FILE IS A SHARED CONTRACT. An identical copy lives at
``skills/afork/aforklib/outcome.py`` and ``skills/tfork/tforklib/outcome.py``.
The two skills install independently (each is its own symlinked skill dir), so
neither may import the other's package — the contract is duplicated instead,
and ``tests/test_outcome_contract.py`` in *both* suites asserts the copies are
identical. Edit one, copy it to the other, or the suites fail.

What the contract is for
------------------------

A dispatcher launches an agent exactly once through ``afork`` -> ``tfork``. It
then needs to know one thing: *did the agent begin work?* Only three answers are
honest:

  ``started``           the agent is running,
  ``prework_failure``   the launch mechanically failed before the agent began,
  ``unknown``           we cannot account for what happened.

``prework_failure`` is the only state that permits a policy fallback (one
explicit retry on a different runtime/model), so it is deliberately hard to
reach: it requires a *trusted* evidence code, and every trusted code maps to
exactly one reason. Everything ambiguous — a raw exit status, unrecognized
output, a free-form note, a timeout, a missing sentinel — lands in ``unknown``
and can never be elevated. Guessing here would launch a second live agent
beside one that may already be running.

Division of labour
------------------

``afork`` owns runtime knowledge. It writes a 0600 launch-contract *sidecar*
into its private workdir naming the attempt, the generated launcher's
exec-failure marker (when it generated one), and the runtime adapter's
model-rejection / launch-error signatures.

``tfork`` owns nothing runtime-specific. It observes generic facts — pane
created, command delivered, start/end sentinels, exit status, foreground
process — and combines them with the sidecar to derive the outcome. Without a
sidecar it still returns a valid outcome; it just cannot reach the trusted
runtime evidence codes, so ambiguous exits stay ``unknown``.
"""

import json
import os
import re
from pathlib import Path

# --- launch_outcome ---------------------------------------------------------

CONTRACT_VERSION = 1

STATE_STARTED = "started"
STATE_PREWORK_FAILURE = "prework_failure"
STATE_UNKNOWN = "unknown"
STATES = (STATE_STARTED, STATE_PREWORK_FAILURE, STATE_UNKNOWN)

REASON_RUNTIME_UNAVAILABLE = "runtime_unavailable"
REASON_MODEL_UNAVAILABLE = "model_unavailable"
REASON_LAUNCH_FAILED = "launch_failed"
REASON_CODES = (REASON_RUNTIME_UNAVAILABLE, REASON_MODEL_UNAVAILABLE,
                REASON_LAUNCH_FAILED)

EVIDENCE_CODES = (
    "agent_started",
    "runtime_exec_failed",
    "model_rejected",
    "runtime_launch_error",
    "pane_creation_failed",
    "command_delivery_absent",
    "unrecognized_exit",
    "missing_start_sentinel",
    "observation_timeout",
    "shell_foreground",
    "missing_foreground",
    "delivery_ambiguous",
    "contradictory_evidence",
)

# The ONLY evidence codes that may carry a reason, and the single reason each
# one maps to. A code absent from this table can never produce a
# prework_failure, no matter what else was observed.
TRUSTED_EVIDENCE = {
    "runtime_exec_failed": REASON_RUNTIME_UNAVAILABLE,
    "model_rejected": REASON_MODEL_UNAVAILABLE,
    "runtime_launch_error": REASON_LAUNCH_FAILED,
    "pane_creation_failed": REASON_LAUNCH_FAILED,
    "command_delivery_absent": REASON_LAUNCH_FAILED,
}

# Everything that is *only* ever ambiguous. Membership here is the guarantee
# that raw exits, notes, timeouts and missing observations stay unknown.
UNTRUSTED_EVIDENCE = tuple(
    code for code in EVIDENCE_CODES
    if code != "agent_started" and code not in TRUSTED_EVIDENCE)

# The exact eight fields of a version-1 launch_outcome, in order. Nothing else
# is ever added: a consumer reading this object gets the whole contract.
OUTCOME_FIELDS = ("version", "state", "reason_code", "evidence_code",
                  "start_sentinel_seen", "end_sentinel_seen", "exit_status",
                  "foreground")

# Process names that count as "just a shell" — the pane shows no live
# command/agent doing useful work.
SHELL_NAMES = {"sh", "bash", "zsh", "fish", "dash", "tcsh", "csh", "ksh"}


def is_shell(process):
    """True when ``process`` is a plain shell, not an agent or command."""
    return Path((process or "").lstrip("-")).name in SHELL_NAMES


class OutcomeContractError(ValueError):
    """A launch_outcome was constructed outside the contract. This is a bug in
    the caller, not a runtime condition — the contract fails loudly rather than
    emitting an object a dispatcher would act on."""


def launch_outcome(state, evidence_code, *, reason_code=None,
                   start_sentinel_seen=False, end_sentinel_seen=False,
                   exit_status=None, foreground=None):
    """Build and validate one version-1 ``launch_outcome`` dict.

    Every invariant the dispatcher relies on is enforced here rather than at
    each call site, so there is exactly one place that decides what ``started``
    and ``prework_failure`` mean.
    """
    if state not in STATES:
        raise OutcomeContractError(f"state {state!r} is not one of {STATES}")
    if evidence_code not in EVIDENCE_CODES:
        raise OutcomeContractError(
            f"evidence_code {evidence_code!r} is not in the stable enum")
    if reason_code is not None and reason_code not in REASON_CODES:
        raise OutcomeContractError(
            f"reason_code {reason_code!r} is not one of {REASON_CODES}")

    if state == STATE_STARTED:
        # The agent is live. Every field has to agree: the wrapper announced
        # the command, never announced its end, recorded no exit, and a real
        # non-shell process holds the foreground.
        if evidence_code != "agent_started":
            raise OutcomeContractError(
                "started requires evidence_code 'agent_started'")
        if reason_code is not None:
            raise OutcomeContractError("started requires a null reason_code")
        if not start_sentinel_seen or end_sentinel_seen:
            raise OutcomeContractError(
                "started requires the start sentinel and no end sentinel")
        if exit_status is not None:
            raise OutcomeContractError("started requires a null exit_status")
        if not foreground or is_shell(foreground):
            raise OutcomeContractError(
                "started requires a live non-shell foreground process")
    elif state == STATE_PREWORK_FAILURE:
        # The only fallback-permitting state, so it takes a trusted code and
        # the one reason that code maps to — never a caller-chosen pairing.
        expected = TRUSTED_EVIDENCE.get(evidence_code)
        if expected is None:
            raise OutcomeContractError(
                f"evidence_code {evidence_code!r} is not trusted; it can never "
                "produce a prework_failure")
        if reason_code != expected:
            raise OutcomeContractError(
                f"evidence_code {evidence_code!r} maps to reason "
                f"{expected!r}, got {reason_code!r}")
    else:  # STATE_UNKNOWN
        if reason_code is not None:
            raise OutcomeContractError("unknown always has a null reason_code")
        if evidence_code not in UNTRUSTED_EVIDENCE:
            raise OutcomeContractError(
                f"evidence_code {evidence_code!r} is trusted and must not be "
                "reported as unknown")

    return {
        "version": CONTRACT_VERSION,
        "state": state,
        "reason_code": reason_code,
        "evidence_code": evidence_code,
        "start_sentinel_seen": bool(start_sentinel_seen),
        "end_sentinel_seen": bool(end_sentinel_seen),
        "exit_status": exit_status,
        "foreground": foreground,
    }


def prework_failure(evidence_code, **facts):
    """``launch_outcome`` for a trusted code, with its mapped reason filled in
    from the table so no call site can pair them by hand."""
    reason = TRUSTED_EVIDENCE.get(evidence_code)
    if reason is None:
        raise OutcomeContractError(
            f"evidence_code {evidence_code!r} is not trusted")
    return launch_outcome(STATE_PREWORK_FAILURE, evidence_code,
                          reason_code=reason, **facts)


def unknown(evidence_code, **facts):
    """``launch_outcome`` for an ambiguous observation. Reason is always null."""
    return launch_outcome(STATE_UNKNOWN, evidence_code, **facts)


# --- the afork launch-contract sidecar --------------------------------------

SIDECAR_VERSION = 1
SIDECAR_NAME = "launch-contract.json"

# The signature kinds an adapter may declare, and the evidence code each one
# produces. Adding a kind here is a contract change; adding a *pattern* to a
# kind is an ordinary adapter update.
SIGNATURE_KINDS = ("model_rejected", "runtime_launch_error")


def exec_marker(attempt_id):
    """The contract-bound marker a generated launcher prints — and only prints
    — after the one real ``exec`` of the intended runtime has failed."""
    return f"__afork_exec_failed_{attempt_id}__"


def build_sidecar(attempt_id, runtime, agent, model, effort, signatures,
                  has_launcher):
    """The sidecar afork writes beside its launcher.

    ``has_launcher`` is False for a plain flat-argv launch: there is no
    generated launcher, so no exec-failure marker can ever be emitted and
    ``exec_marker`` is null. tfork then simply cannot reach
    ``runtime_exec_failed`` for that attempt, which is the honest answer.
    """
    return {
        "version": SIDECAR_VERSION,
        "attempt_id": attempt_id,
        "runtime": runtime,
        "agent": agent,
        "model": model,
        "effort": effort,
        "exec_marker": exec_marker(attempt_id) if has_launcher else None,
        "signatures": {
            kind: list((signatures or {}).get(kind) or ())
            for kind in SIGNATURE_KINDS
        },
    }


def write_sidecar(workdir, sidecar):
    """Write ``sidecar`` 0600 into ``workdir`` and return its path.

    0600 because the sidecar names the exact runtime/model of a launch and the
    marker tfork trusts; a world-readable copy would let anything on the box
    forge a runtime_exec_failed by echoing the marker into the pane.
    """
    path = Path(workdir) / SIDECAR_NAME
    path.write_text(json.dumps(sidecar, indent=2) + "\n")
    os.chmod(path, 0o600)
    return str(path)


def _is_well_formed(data):
    """True when a version-1 sidecar has the shapes its readers assume.

    Announcing version 1 is a claim, not proof. The readers index
    ``signatures`` as a mapping and test ``exec_marker`` with ``in`` against
    pane text, so a wrong-typed value there would raise mid-fork — after the
    pane already exists — and cost the caller the launch_outcome it is
    entitled to for an attempted launch.
    """
    marker = data.get("exec_marker")
    if marker is not None and not isinstance(marker, str):
        return False
    signatures = data.get("signatures")
    if signatures is None:
        return True
    if not isinstance(signatures, dict):
        return False
    for patterns in signatures.values():
        # str is iterable, so an un-listed pattern would iterate character by
        # character and single characters match almost anything — a false
        # TRUSTED classification, which is worse than the crash.
        if not isinstance(patterns, (list, tuple)):
            return False
        if not all(isinstance(p, str) for p in patterns):
            return False
    return True


def load_sidecar(path):
    """Read a sidecar, or return None when it is absent, unreadable, not JSON,
    not a version this contract understands, or malformed for that version.

    Never raises: a missing or unusable sidecar means tfork falls back to
    generic facts only. Failing the whole fork over it would turn a
    classification aid into a launch blocker.

    A version-1 file with wrong-typed fields is rejected whole rather than
    read in part. Trusting the half that happens to be well-formed is how a
    corrupt file ends up licensing a retry.
    """
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != SIDECAR_VERSION:
        return None
    if not _is_well_formed(data):
        return None
    return data


def match_signature(sidecar, kind, text):
    """True when any of the adapter's ``kind`` patterns matches ``text``.

    Patterns are adapter-owned regexes carried in the sidecar. A pattern that
    does not compile is skipped rather than raising — a bad pattern must
    degrade to "not recognized" (and therefore ``unknown``), never to a crash
    or to a false trusted classification.

    The type guards repeat ``_is_well_formed``'s on purpose: this is public and
    takes a sidecar dict, not a path, so a caller that hand-built one never
    passed through ``load_sidecar``. Nothing here may raise.
    """
    if not isinstance(sidecar, dict) or not text:
        return False
    signatures = sidecar.get("signatures")
    if not isinstance(signatures, dict):
        return False
    patterns = signatures.get(kind)
    if not isinstance(patterns, (list, tuple)):
        return False
    for pattern in patterns:
        if not isinstance(pattern, str):
            continue
        try:
            if re.search(pattern, text):
                return True
        except re.error:
            continue
    return False


# --- generic delivery facts (tfork's side of the combination) ---------------

DELIVERY_COMPLETE = "complete"      # the line was pasted and Enter was sent
DELIVERY_ABSENT = "absent"          # nothing reached the pane at all
DELIVERY_AMBIGUOUS = "ambiguous"    # something may have landed; can't tell
DELIVERY_STATES = (DELIVERY_COMPLETE, DELIVERY_ABSENT, DELIVERY_AMBIGUOUS)
