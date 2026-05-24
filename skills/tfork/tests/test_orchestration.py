"""The full fork -> verify -> label -> persist flow, driven against
``FakeTerminal``. Tests use a known ``nonce`` so the scripted pane text can
contain the matching sentinel markers."""

import os
import time

import pytest

import tforklib as ft
from fake_terminal import FakeTerminal, make_scrollback

NONCE = "abc123"


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Keep the verify sleep instant in unit tests."""
    monkeypatch.setattr(time, "sleep", lambda *_: None)


@pytest.fixture
def reg(tmp_path):
    return tmp_path / "registry.toml"


# -- observation outcomes -------------------------------------------------

def test_clean_exit_is_verified_command(reg):
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=0))
    result = ft.run_fork(["echo", "hi"], terminal=term, nonce=NONCE,
                        registry_path=reg)
    assert result["ok"] is True
    assert result["verified"] is True
    assert result["type"] == "command"
    assert result["exit_status"] == 0
    assert result["foreground"] == "zsh"
    assert result["note"] == "exited cleanly"


def test_nonzero_exit_is_unverified_command(reg):
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=127))
    result = ft.run_fork(["xyz-nope"], terminal=term, nonce=NONCE,
                        registry_path=reg)
    assert result["verified"] is False
    assert result["type"] == "command"
    assert result["exit_status"] == 127
    assert "127" in result["note"]


def test_long_runner_with_non_shell_foreground_is_agent(reg):
    term = FakeTerminal(process="claude",
                        text=make_scrollback(NONCE))  # no end marker
    result = ft.run_fork(["claude"], terminal=term, nonce=NONCE,
                        registry_path=reg)
    assert result["verified"] is True
    assert result["type"] == "agent"
    assert result["foreground"] == "claude"
    assert result["exit_status"] is None
    assert "claude" in result["note"]


def test_server_classifies_as_agent(reg):
    """A long-running server with a non-shell foreground process is
    indistinguishable from a long-running agent — they share the verdict."""
    term = FakeTerminal(process="python3",
                        text=make_scrollback(NONCE))
    result = ft.run_fork(["python3", "-m", "http.server"], terminal=term,
                        nonce=NONCE, registry_path=reg)
    assert result["type"] == "agent"
    assert result["foreground"] == "python3"


def test_missing_start_sentinel_is_unverified(reg):
    """Wrapper never ran (e.g. fish shell or paste corruption)."""
    term = FakeTerminal(process="zsh", text="some random output\n")
    result = ft.run_fork(["echo", "hi"], terminal=term, nonce=NONCE,
                        registry_path=reg)
    assert result["verified"] is False
    assert "start sentinel" in result["note"]


def test_no_end_with_shell_foreground_is_state_unknown(reg):
    """The wrapper started but nothing took over the pane — the command
    stopped without emitting the end sentinel. We cannot account for it."""
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE))  # start only
    result = ft.run_fork(["something"], terminal=term, nonce=NONCE,
                        registry_path=reg)
    assert result["verified"] is False
    assert result["exit_status"] is None
    assert "state unknown" in result["note"]


# -- label resolution: --type override, registry, observation -----------

def test_type_override_agent_wins_over_observation(reg):
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=0))
    result = ft.run_fork(["echo", "hi"], type_override="agent",
                        terminal=term, nonce=NONCE, registry_path=reg)
    assert result["type"] == "agent"          # override honored
    assert result["verified"] is True          # observation still wins on verified
    assert result["exit_status"] == 0
    assert "correct if intended" in result["note"]


def test_type_override_command_wins_over_observation(reg):
    term = FakeTerminal(process="claude", text=make_scrollback(NONCE))
    result = ft.run_fork(["claude"], type_override="command",
                        terminal=term, nonce=NONCE, registry_path=reg)
    assert result["type"] == "command"
    assert result["foreground"] == "claude"
    assert "correct if intended" in result["note"]


def test_first_observation_writes_registry(reg):
    term = FakeTerminal(process="claude", text=make_scrollback(NONCE))
    ft.run_fork(["cm"], terminal=term, nonce=NONCE, registry_path=reg)
    assert ft.read_registry(reg) == {"cm": True}


def test_registry_label_wins_over_weak_observation(reg):
    """When the current observation is weak (no exit recorded — just a
    long-runner snapshot), the registry decides. A previously persisted
    ``cm = command`` label keeps a fresh still-running observation from
    flipping the label to agent, and the contradiction note explains it."""
    ft.write_registry_entry("cm", False, reg)
    term = FakeTerminal(process="claude", text=make_scrollback(NONCE))
    result = ft.run_fork(["cm"], terminal=term, nonce=NONCE, registry_path=reg)
    assert result["type"] == "command"
    assert "correct if intended" in result["note"]


def test_strong_observation_overrides_registry_for_return(reg):
    """A recorded exit status is a *strong* observation — strong enough to
    override the registry for the returned label. Concrete bug: ``npm run
    dev`` once writes ``npm = agent``; a later ``npm test`` exits cleanly
    and must be reported as a command in the result."""
    ft.write_registry_entry("npm", True, reg)  # learned from `npm run dev`
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=0))
    result = ft.run_fork(["npm", "test"], terminal=term, nonce=NONCE,
                        registry_path=reg)
    assert result["type"] == "command"
    assert result["exit_status"] == 0


def test_strong_command_does_not_demote_agent_registry(reg):
    """The asymmetric persistence guard. ``tfork -- claude --version`` exits
    cleanly and is honestly reported as a command — but rewriting
    ``claude = false`` would silently break the next plain ``tfork --
    claude``. The registry is left alone; the note tells the user how to
    lock the demotion in if that was intended."""
    ft.write_registry_entry("claude", True, reg)
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=0))
    result = ft.run_fork(["claude", "--version"], terminal=term, nonce=NONCE,
                        registry_path=reg)
    assert result["type"] == "command"
    assert result["exit_status"] == 0
    assert ft.read_registry(reg) == {"claude": True}
    assert "kept the agent label" in result["note"]
    assert "--type command" in result["note"]


def test_nonzero_exit_does_not_demote_agent_registry(reg):
    """A non-zero exit is still a strong command observation; the same
    guard applies — a crashed agent launch must not silently flip the
    registry."""
    ft.write_registry_entry("claude", True, reg)
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=127))
    result = ft.run_fork(["claude"], terminal=term, nonce=NONCE, registry_path=reg)
    assert result["type"] == "command"
    assert result["exit_status"] == 127
    assert ft.read_registry(reg) == {"claude": True}


def test_explicit_type_command_demotes_agent_registry(reg):
    """The guard fires only for un-overridden command observations. An
    explicit ``--type command`` is the user telling us the demotion is
    intentional, and that always rewrites."""
    ft.write_registry_entry("claude", True, reg)
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=0))
    ft.run_fork(["claude"], type_override="command", terminal=term,
                nonce=NONCE, registry_path=reg)
    assert ft.read_registry(reg) == {"claude": False}


def test_strong_command_writes_new_command_registry_entry(reg):
    """The guard is narrow: it only protects existing *agent* entries from
    silent demotion. A fresh command observation on a never-seen word still
    writes — auto-learning is preserved for the non-conflicting case."""
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=0))
    ft.run_fork(["mytool"], terminal=term, nonce=NONCE, registry_path=reg)
    assert ft.read_registry(reg) == {"mytool": False}


def test_strong_command_rewrites_existing_command_registry(reg):
    """Symmetric: re-confirming a command label is always written — there
    is nothing to protect."""
    ft.write_registry_entry("mytool", False, reg)
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=0))
    ft.run_fork(["mytool"], terminal=term, nonce=NONCE, registry_path=reg)
    assert ft.read_registry(reg) == {"mytool": False}


def test_type_override_overwrites_registry(reg):
    """Explicitly correcting with --type updates the persisted label."""
    ft.write_registry_entry("cm", True, reg)
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=0))
    ft.run_fork(["cm"], type_override="command", terminal=term,
                nonce=NONCE, registry_path=reg)
    assert ft.read_registry(reg) == {"cm": False}


def test_registry_agreement_produces_no_contradiction_note(reg):
    ft.write_registry_entry("cm", True, reg)
    term = FakeTerminal(process="claude", text=make_scrollback(NONCE))
    result = ft.run_fork(["cm"], terminal=term, nonce=NONCE, registry_path=reg)
    assert "correct if intended" not in result["note"]
    assert "still running" in result["note"]


# -- alias resolution -----------------------------------------------------

def test_alias_foreground_is_returned_verbatim(reg):
    """``ran`` carries the word the user typed; ``foreground`` carries what
    the kernel actually scheduled — together they explain alias resolution."""
    term = FakeTerminal(process="claude", text=make_scrollback(NONCE))
    result = ft.run_fork(["cm"], terminal=term, nonce=NONCE, registry_path=reg)
    assert result["ran"] == "cm"
    assert result["foreground"] == "claude"


# -- result shape ---------------------------------------------------------

def test_result_always_carries_foreground_and_exit_status(reg):
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=0))
    result = ft.run_fork(["echo"], terminal=term, nonce=NONCE, registry_path=reg)
    assert "foreground" in result
    assert "exit_status" in result
    assert "note" in result


# -- fork plumbing --------------------------------------------------------

def test_nonce_is_forwarded_to_fork(reg):
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=0))
    ft.run_fork(["echo"], terminal=term, nonce=NONCE, registry_path=reg)
    fork_call = term.calls[0]
    # (op, command, placement, cwd, nonce, anchor)
    assert fork_call[0] == "fork"
    assert fork_call[4] == NONCE


def test_command_words_are_shlex_joined(reg):
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=0))
    argv = ["python3", "-c", "import sys; print(sys.argv[1])", "hello world"]
    ft.run_fork(argv, terminal=term, nonce=NONCE, registry_path=reg)
    assert term.calls[0][1] == (
        "python3 -c 'import sys; print(sys.argv[1])' 'hello world'"
    )


def test_placement_is_forwarded_to_fork(reg):
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=0))
    ft.run_fork(["echo"], placement="top", terminal=term, nonce=NONCE,
                registry_path=reg)
    assert term.calls[0][2] == "top"


def test_anchor_is_forwarded_to_fork(reg):
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=0))
    ft.run_fork(["echo"], placement="left", anchor="my-tab",
                terminal=term, nonce=NONCE, registry_path=reg)
    assert term.calls[0][5] == "my-tab"


def test_cwd_passed_to_fork_is_caller_cwd(reg):
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=0))
    ft.run_fork(["echo"], terminal=term, nonce=NONCE, registry_path=reg)
    assert term.calls[0][3] == os.getcwd()


# -- pane lifecycle (no auto-kill) ---------------------------------------

def test_pane_is_never_killed_on_verified_false(reg):
    term = FakeTerminal(process="zsh",
                        text=make_scrollback(NONCE, exit_status=127))
    ft.run_fork(["xyz-nope"], terminal=term, nonce=NONCE, registry_path=reg)
    assert term.killed == []


def test_pane_is_never_killed_on_missing_start(reg):
    term = FakeTerminal(process="zsh", text="garbage\n")
    ft.run_fork(["xyz-nope"], terminal=term, nonce=NONCE, registry_path=reg)
    assert term.killed == []


# -- error propagation ----------------------------------------------------

def test_split_failure_propagates_with_no_pane_to_kill(reg):
    term = FakeTerminal(fork_error=ft.err_split_failed("cmux exploded"))
    with pytest.raises(ft.ForkError) as exc:
        ft.run_fork(["claude"], terminal=term, nonce=NONCE, registry_path=reg)
    assert exc.value.code == "split_failed"
    assert term.killed == []


def test_spawn_failure_propagates(reg):
    term = FakeTerminal(fork_error=ft.err_spawn_failed("paste failed"))
    with pytest.raises(ft.ForkError) as exc:
        ft.run_fork(["claude"], terminal=term, nonce=NONCE, registry_path=reg)
    assert exc.value.code == "spawn_failed"


def test_empty_command_is_bad_arguments(reg):
    with pytest.raises(ft.ForkError) as exc:
        ft.run_fork([], terminal=FakeTerminal(), registry_path=reg)
    assert exc.value.code == "bad_arguments"
