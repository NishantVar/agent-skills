"""Post-hoc classification — ``classify_observed`` reads the verify snapshot
and decides whether what was observed looks like an agent or a command."""

import tforklib as ft


def test_clean_exit_is_command():
    assert ft.classify_observed(exit_status=0, foreground="zsh") == "command"


def test_nonzero_exit_is_command():
    """A failed command is still a command — exit status is what classifies."""
    assert ft.classify_observed(exit_status=127, foreground="zsh") == "command"


def test_long_runner_with_non_shell_foreground_is_agent():
    """No exit recorded and a non-shell foreground = long-running thing."""
    assert ft.classify_observed(exit_status=None, foreground="claude") == "agent"


def test_long_runner_with_shell_foreground_is_command():
    """No exit but the shell is back in front — the wrapper broke or the
    command exited without emitting the end sentinel. Treated as a command
    because we cannot honestly call it agent-like."""
    assert ft.classify_observed(exit_status=None, foreground="zsh") == "command"


def test_no_foreground_is_command():
    """Pane is dead or unreadable; without a process we cannot claim agent."""
    assert ft.classify_observed(exit_status=None, foreground=None) == "command"


def test_server_classifies_as_agent():
    """A long-running server (python3 http.server, npm run dev) is
    indistinguishable from an agent by this signal — and that is fine."""
    assert ft.classify_observed(exit_status=None, foreground="python3") == "agent"
