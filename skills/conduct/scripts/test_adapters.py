"""Per-runtime verb -> keystroke mapping, runtime identification, and the
fail-closed gates. No live agent is dispatched — these inspect the adapter
mapping only.
"""

import pytest

import adapters


def _adapter(runtime):
    """get_adapter that asserts a real adapter (narrows Optional for the type
    checker and fails the test loudly if a runtime ever stops resolving)."""
    a = adapters.get_adapter(runtime)
    assert a is not None, f"expected an adapter for {runtime!r}"
    return a


# ---------------- runtime identification ----------------

@pytest.mark.parametrize("names,expected", [
    (["claude.exe", "node"], "claude"),
    (["claude"], "claude"),
    (["codex"], "codex"),
    (["codex.exe"], "codex"),
    # Ground-truth: cmux top reports codex's arch-suffixed (often truncated)
    # binary name. Regression for the fail-closed-on-every-codex-agent bug.
    (["SkyComputerUseC", "codex-aarch64-a", "sleep", "zsh"], "codex"),
    (["codex-aarch64-apple-darwin"], "codex"),
    (["codex-x86_64-unknown-linux-gnu"], "codex"),
    (["claude-aarch64-apple-darwin"], "claude"),
    (["pi"], "pi"),
    (["pi.exe"], "pi"),
    (["zsh", "node"], None),         # a shell -> no supported runtime
    ([], None),
    # Over-match guards: pi must NOT prefix-match pip/pipenv/pixi/python, and
    # an arbitrary "codexterity"-style word must not pass on the codex- prefix.
    (["pip"], None),
    (["pipenv"], None),
    (["pixi"], None),
    (["python3"], None),
    (["codexterity"], None),         # no `codex-` boundary -> not codex
])
def test_runtime_from_processes(names, expected):
    assert adapters.runtime_from_processes(names) == expected


def test_get_adapter_unknown_is_none():
    assert adapters.get_adapter(None) is None
    assert adapters.get_adapter("vim") is None


# ---------------- verb -> keystroke sequences ----------------

def test_claude_clear_sequence():
    a = _adapter("claude")
    assert a.supports("clear")
    assert a.sequence("clear") == [("text", "/clear"), ("key", "enter")]


def test_claude_interrupt_is_escape():
    a = _adapter("claude")
    assert a.sequence("interrupt") == [("key", "escape")]


def test_claude_kill_is_close():
    a = _adapter("claude")
    assert a.sequence("kill") == [("close", None)]


def test_codex_exit_uses_quit():
    a = _adapter("codex")
    assert a.sequence("exit") == [("text", "/quit"), ("key", "enter")]


def test_pi_compact_unsupported():
    # pi has no compact this round -> fail closed (verb_unsupported upstream).
    a = _adapter("pi")
    assert not a.supports("compact")
    assert a.sequence("compact") is None


def test_every_runtime_supports_interrupt_and_kill():
    for rt in ("claude", "codex", "pi"):
        a = _adapter(rt)
        assert a.supports("interrupt")
        assert a.supports("kill")


# ---------------- context% extraction ----------------
# Semantics: context_pct is the percent of context USED (higher = closer to
# full). claude's `ctx:NN%` is already "used"; codex's footer reports "left"
# (remaining) and is converted to used via 100 - left.

def test_claude_context_pct_parses_status_line():
    a = _adapter("claude")
    screen = "✽ Sautéing… (2m 27s)\n  ctx:58%  /git/agent-skills  main [?]"
    assert a.context_pct(screen) == 58


def test_claude_context_pct_none_when_absent():
    a = _adapter("claude")
    assert a.context_pct("nothing here") is None
    assert a.context_pct("") is None


def test_codex_context_pct_parses_context_left_and_converts_to_used():
    # Ground-truth codex footer: `Context 37% left` -> 63% used.
    a = _adapter("codex")
    screen = "gpt-5.5 xhigh · Context 37% left · ~/git/agent-skills"
    assert a.context_pct(screen) == 63


def test_codex_context_pct_word_order_variant():
    # The reviewer described `NN% context left`; accept that order too -> used.
    a = _adapter("codex")
    assert a.context_pct("42% context left") == 58


def test_codex_context_pct_none_when_absent():
    a = _adapter("codex")
    assert a.context_pct("no footer here") is None
    assert a.context_pct("") is None
    # claude's `ctx:NN%` is NOT codex's format -> codex does not parse it.
    assert a.context_pct("ctx:58%") is None


def test_pi_context_pct_always_none():
    assert _adapter("pi").context_pct("Context 37% left") is None


# ---------------- coarse state ----------------

def test_busy_state_from_interrupt_affordance():
    for rt in ("claude", "codex", "pi"):
        a = _adapter(rt)
        assert a.state("• Working (15s • esc to interrupt)") == "busy"


def test_state_none_when_no_busy_marker():
    for rt in ("claude", "codex", "pi"):
        a = _adapter(rt)
        assert a.state("idle prompt, nothing running") is None
        assert a.state("") is None
