"""Forking a split must never steal focus from the caller's pane.

cmux instantiates a split's terminal lazily, so historically tfork created
the split with ``--focus true`` to force its shell up — which bounced the
human's view on every fork. The fix creates the split unfocused
(``--focus false``) and wakes its lazy shell with a ``send-key enter`` from
``_wait_ready`` (a keystroke brings the shell up without moving focus).
"""

import subprocess
import time

import pytest

from tforklib import terminal as term_mod


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)


def _ok(stdout=""):
    return subprocess.CompletedProcess([], 0, stdout, "")


def _fail(stderr="boom"):
    return subprocess.CompletedProcess([], 1, "", stderr)


def test_new_split_does_not_steal_focus(monkeypatch):
    """The split is created with ``--focus false`` — never ``true``."""
    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        return _ok('{"surface_ref": "surface:9"}')

    monkeypatch.setattr(term_mod, "_run", fake_run)
    monkeypatch.setattr(term_mod, "_workspace_of", lambda _s: None)

    cmx = term_mod.CmuxTerminal()
    ref = cmx._new_split("right", "surface:1")

    assert ref == "surface:9"
    split_cmd = next(c for c in calls if "new-split" in c)
    assert "--focus" in split_cmd
    assert split_cmd[split_cmd.index("--focus") + 1] == "false"
    assert "true" not in split_cmd


def test_wait_ready_wakes_unfocused_split_with_keystroke(monkeypatch):
    """A not-yet-live pane gets a ``send-key enter`` nudge between polls; a
    pane that is already live (read-screen succeeds first poll) does not."""
    calls = []
    # read-screen fails once (lazy split, no shell yet), then succeeds.
    read_results = iter([_fail(), _ok("prompt")])

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        if "read-screen" in cmd:
            return next(read_results)
        return _ok()

    monkeypatch.setattr(term_mod, "_run", fake_run)
    monkeypatch.setattr(term_mod, "_workspace_of", lambda _s: None)

    cmx = term_mod.CmuxTerminal()
    cmx._wait_ready("surface:9")

    wake = [c for c in calls if "send-key" in c and "enter" in c]
    assert len(wake) == 1, "expected exactly one wake keystroke after the failed poll"
    assert wake[0][:4] == ["cmux", "send-key", "--surface", "surface:9"]


def test_wait_ready_skips_wake_when_pane_already_live(monkeypatch):
    """An eagerly-seeded pane (workspace/window placement) is live on the
    first poll, so no wake keystroke is ever sent."""
    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        if "read-screen" in cmd:
            return _ok("prompt")
        return _ok()

    monkeypatch.setattr(term_mod, "_run", fake_run)
    monkeypatch.setattr(term_mod, "_workspace_of", lambda _s: None)

    cmx = term_mod.CmuxTerminal()
    cmx._wait_ready("surface:9")

    assert not [c for c in calls if "send-key" in c]
