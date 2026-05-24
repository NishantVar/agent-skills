"""The post-fork verification check.

One function, one bounded sleep, one pane read. The pasted line carries a
per-fork sentinel wrapper:

    __tfork_nonce=<NONCE>; set +e;
    printf '\\n__tfork_start_%s__\\n' "$__tfork_nonce";
    cd <cwd> && <command>;
    __tfork_ec=$?;
    printf '\\n__tfork_end_%s=%d__\\n' "$__tfork_nonce" "$__tfork_ec"

``verify_fork`` reads the pane's full scrollback, locates those markers, and
returns ``(verified, foreground, exit_status, note)``. It never raises and
never closes the pane — a False verdict is surfaced to the caller as an
unverified success with the pane left open for the user to inspect.
"""

import re
import time
from pathlib import Path

# Seconds to wait after spawn before reading the pane. The wrapper needs
# enough time to print the start marker and either let the command exit
# (so the end marker prints) or settle into a long-running foreground
# process; 2s covers shell startup on every machine seen so far.
DEFAULT_DELAY = 2

# Process names that count as "just a shell" — the pane shows no live
# command/agent doing useful work.
SHELL_NAMES = {"sh", "bash", "zsh", "fish", "dash", "tcsh", "csh", "ksh"}


def is_shell(process):
    """True when ``process`` is a plain shell, not an agent or command."""
    return Path((process or "").lstrip("-")).name in SHELL_NAMES


def verify_fork(terminal, session, nonce, delay):
    """Single deterministic check; returns ``(verified, foreground, exit_status, note)``.

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
    time.sleep(delay)
    text = terminal.pane_text(session)
    foreground = terminal.pane_process(session)

    start_marker = f"__tfork_start_{nonce}__"
    end_re = re.compile(rf"__tfork_end_{re.escape(nonce)}=(-?\d+)__")

    if start_marker not in text:
        return False, foreground, None, (
            "start sentinel not observed; paste may be corrupted or the "
            "target shell may not support the verification wrapper"
        )

    end_match = end_re.search(text)
    if end_match:
        exit_status = int(end_match.group(1))
        if exit_status == 0:
            return True, foreground, exit_status, "exited cleanly"
        return (False, foreground, exit_status,
                f"exited with status {exit_status}")

    # Start fired, no end yet — the command is either still running or it
    # died without the wrapper printing the end marker. Foreground decides:
    # a non-shell process means real work is happening (server, agent);
    # a shell means whatever ran is gone and we cannot account for it.
    if foreground is not None and not is_shell(foreground):
        return (True, foreground, None,
                f"still running, foreground = {foreground}")
    return False, foreground, None, (
        "state unknown: no end sentinel observed and no non-shell foreground "
        "process is running"
    )
