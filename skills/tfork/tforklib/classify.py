"""Post-hoc agent-versus-command classification.

The new design wraps every fork with the same sentinel and reads the result;
the classification falls out of *what was observed*, not upfront detection. A
foreground process that is not a plain shell, with no exit status recorded,
is treated as an agent (or agent-like long-runner such as ``npm run dev``);
everything else is a command. The user can correct with ``--type``.
"""

from .verify import is_shell


def classify_observed(exit_status, foreground):
    """Post-hoc label for what the fork turned out to be.

    Returns ``"agent"`` only when the wrapped command is still running with a
    non-shell process in the foreground at the time of the verify snapshot;
    everything else (clean exit, non-zero exit, the wrapper itself broke,
    just a shell sitting at a prompt) is ``"command"``. The label is
    descriptive, not prescriptive — the verify result drives every other
    field in the response.
    """
    if exit_status is None and foreground is not None and not is_shell(foreground):
        return "agent"
    return "command"
