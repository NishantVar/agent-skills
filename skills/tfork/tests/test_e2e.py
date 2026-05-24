"""End-to-end tests — require a live cmux session.

These exercise ``CmuxTerminal`` and surface resolution against the real cmux
CLI: the code that cannot be covered with mocks. They are skipped automatically
when not running inside cmux.

    python3 -m pytest tests/test_e2e.py -v

The multi-runtime surface-resolution matrix (Claude Code, Codex, Gemini) is
covered by running this file from inside each runtime's cmux surface.
"""

import pytest

import tforklib as ft

pytestmark = pytest.mark.skipif(
    not ft.CmuxTerminal.detect(),
    reason="requires a live cmux session",
)


def test_surface_resolution_returns_the_callers_own_surface():
    surface_ref = ft.CmuxTerminal()._resolve_origin_surface()
    assert surface_ref.startswith("surface:")


def test_fork_plain_command_lifecycle():
    """Fork a harmless command in a real pane and check the verified result.

    The per-fork sentinel wrapper makes the verdict deterministic against a
    live cmux pane: the start marker is read off the top of the scrollback
    and the clean-exit end marker carries the exit status. The pane is
    cleaned up at the end so the test does not litter."""
    result = ft.run_fork(["echo", "tfork-e2e-ok"], placement="right",
                         type_override="command")
    assert result["ok"] is True
    assert result["ran"] == "echo"
    assert result["session"].startswith("surface:")
    assert result["verified"] is True
    assert result["exit_status"] == 0
    ft.CmuxTerminal().kill(result["session"])  # remove the pane this test made


def test_unverified_command_keeps_its_pane_open():
    """A command whose verification reports a non-zero exit is still a
    success with ``verified`` false, and its pane is left open for the user
    to inspect."""
    result = ft.run_fork(["tfork-definitely-not-a-real-command-xyz"],
                         placement="right", type_override="command", delay=1)
    assert result["ok"] is True
    assert result["verified"] is False
    assert result["note"]
    ft.CmuxTerminal().kill(result["session"])  # tfork leaves it; clean up here
