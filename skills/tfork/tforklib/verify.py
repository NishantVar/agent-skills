"""The post-fork verification check.

One function, one bounded sleep, one pane read. The pasted line carries a
per-fork sentinel wrapper:

    __tfork_nonce=<NONCE>; set +e;
    printf '\\n__tfork_start_%s__\\n' "$__tfork_nonce";
    cd <cwd> && <command>;
    __tfork_ec=$?;
    printf '\\n__tfork_end_%s=%d__\\n' "$__tfork_nonce" "$__tfork_ec"

``observe_fork`` reads the pane once and returns the raw ``Observation`` — the
generic, runtime-agnostic facts. ``verdict`` turns those facts into the
human-facing ``(verified, foreground, exit_status, note)`` tuple, and
``result.derive_launch_outcome`` turns the same facts (plus afork's sidecar)
into the machine-facing ``launch_outcome``. Both consumers read one snapshot;
the pane is never polled twice. Neither raises and neither closes the pane — a
False verdict is surfaced as an unverified success with the pane left open.
"""

import re
import time
from collections import namedtuple

from .outcome import SHELL_NAMES, is_shell  # noqa: F401  (re-exported)

# Seconds to wait after spawn before reading the pane. The wrapper needs
# enough time to print the start marker and either let the command exit
# (so the end marker prints) or settle into a long-running foreground
# process; 2s covers shell startup on every machine seen so far.
DEFAULT_DELAY = 2

# One snapshot of the pane. ``readable`` is False when the pane could not be
# read at all (``pane_text`` returns "" both for a read failure and for a pane
# that has genuinely printed nothing — either way we observed nothing, which is
# the only claim the launch_outcome contract makes from it).
Observation = namedtuple(
    "Observation",
    "start_sentinel_seen end_sentinel_seen exit_status foreground pane_text "
    "readable")


def observe_fork(terminal, session, nonce, delay):
    """Sleep once, read the pane once, and return the raw ``Observation``."""
    time.sleep(delay)
    text = terminal.pane_text(session)
    foreground = terminal.pane_process(session)

    start_seen = f"__tfork_start_{nonce}__" in text
    end_match = re.search(rf"__tfork_end_{re.escape(nonce)}=(-?\d+)__", text)
    return Observation(
        start_sentinel_seen=start_seen,
        end_sentinel_seen=end_match is not None,
        exit_status=int(end_match.group(1)) if end_match else None,
        foreground=foreground,
        pane_text=text,
        readable=bool(text),
    )


def verdict(obs):
    """``(verified, foreground, exit_status, note)`` from one ``Observation``.

    Verdict matrix:

    =======================================  ========  ======================
    What we observed                         verified  note
    =======================================  ========  ======================
    start sentinel not in pane               False     "paste corrupt or shell
                                                       does not support the
                                                       wrapper"
    start + end with exit_status == 0        True      "exited cleanly"
    start + end with exit_status != 0        False     "exited with status N"
    start, no end, non-shell foreground      True      "still running, ..."
    start, no end, shell foreground          False     "state unknown ..."
    =======================================  ========  ======================
    """
    if not obs.start_sentinel_seen:
        return False, obs.foreground, None, (
            "start sentinel not observed; paste may be corrupted or the "
            "target shell may not support the verification wrapper"
        )

    if obs.end_sentinel_seen:
        if obs.exit_status == 0:
            return True, obs.foreground, obs.exit_status, "exited cleanly"
        return (False, obs.foreground, obs.exit_status,
                f"exited with status {obs.exit_status}")

    # Start fired, no end yet — the command is either still running or it
    # died without the wrapper printing the end marker. Foreground decides:
    # a non-shell process means real work is happening (server, agent);
    # a shell means whatever ran is gone and we cannot account for it.
    if obs.foreground is not None and not is_shell(obs.foreground):
        return (True, obs.foreground, None,
                f"still running, foreground = {obs.foreground}")
    return False, obs.foreground, None, (
        "state unknown: no end sentinel observed and no non-shell foreground "
        "process is running"
    )


def verify_fork(terminal, session, nonce, delay):
    """Observe once and return the verdict — the original single-call API."""
    return verdict(observe_fork(terminal, session, nonce, delay))
