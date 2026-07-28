"""The launch_outcome matrix: every observation tfork can make, and the exact
object it must produce.

The asymmetry under test is the whole point. ``prework_failure`` is the only
state that licenses a dispatcher to start a second agent, so it must be
reachable ONLY from evidence afork vouched for in the sidecar. Everything else
— an exit status, unrecognized output, a missing sentinel, a shell in the
foreground, a delivery that might have landed — has to come back ``unknown``,
because being wrong there means two live agents doing the same work.
"""

import json
from pathlib import Path

import pytest

from tforklib.outcome import (
    DELIVERY_ABSENT,
    DELIVERY_AMBIGUOUS,
    EVIDENCE_CODES,
    OUTCOME_FIELDS,
    OutcomeContractError,
    REASON_CODES,
    STATES,
    launch_outcome,
    load_sidecar,
    prework_failure,
    unknown,
)
from tforklib.result import derive_launch_outcome, pane_creation_failed
from tforklib.verify import Observation

ATTEMPT = "deadbeefcafe0001"
MARKER = f"__afork_exec_failed_{ATTEMPT}__"

SIDECAR = {
    "version": 1,
    "attempt_id": ATTEMPT,
    "runtime": "codex",
    "agent": "reviewer",
    "model": "gpt-5",
    "effort": "high",
    "exec_marker": MARKER,
    "signatures": {
        "model_rejected": [r"(?i)\b(invalid|unknown|unsupported) model\b"],
        "runtime_launch_error": [r"(?im)^codex:\s"],
    },
}


def obs(start=True, end=False, exit_status=None, foreground="codex",
        pane_text="", readable=True):
    return Observation(start_sentinel_seen=start, end_sentinel_seen=end,
                       exit_status=exit_status, foreground=foreground,
                       pane_text=pane_text, readable=readable)


def assert_outcome(outcome, state, reason, evidence, **facts):
    """Field-exact: the object's shape is the contract, not just its state."""
    assert list(outcome) == list(OUTCOME_FIELDS)
    assert outcome["version"] == 1
    assert outcome["state"] == state
    assert outcome["reason_code"] == reason
    assert outcome["evidence_code"] == evidence
    for key, value in facts.items():
        assert outcome[key] == value, key


# --- the twelve rows --------------------------------------------------------

def test_started_non_shell_foreground():
    out = derive_launch_outcome(obs(foreground="codex"), SIDECAR)
    assert_outcome(out, "started", None, "agent_started",
                   start_sentinel_seen=True, end_sentinel_seen=False,
                   exit_status=None, foreground="codex")


def test_clean_immediate_exit_is_unknown():
    """Exit 0 before doing anything is not a launch failure — the runtime ran.
    ``--version`` and ``--help`` land here."""
    out = derive_launch_outcome(obs(end=True, exit_status=0, foreground="zsh"),
                                SIDECAR)
    assert_outcome(out, "unknown", None, "unrecognized_exit",
                   end_sentinel_seen=True, exit_status=0)


def test_nonzero_exit_nobody_recognized_is_unknown():
    out = derive_launch_outcome(
        obs(end=True, exit_status=7, foreground="zsh",
            pane_text="some output nobody has a pattern for"), SIDECAR)
    assert_outcome(out, "unknown", None, "unrecognized_exit", exit_status=7)


def test_contract_bound_missing_executable_is_a_trusted_failure():
    out = derive_launch_outcome(
        obs(end=True, exit_status=127, foreground="zsh",
            pane_text=f"launch.sh: codex: command not found\n{MARKER}\n"),
        SIDECAR)
    assert_outcome(out, "prework_failure", "runtime_unavailable",
                   "runtime_exec_failed", exit_status=127)


def test_recognized_model_rejection():
    out = derive_launch_outcome(
        obs(end=True, exit_status=2, foreground="zsh",
            pane_text="error: unknown model 'gpt-5'\n"), SIDECAR)
    assert_outcome(out, "prework_failure", "model_unavailable",
                   "model_rejected", exit_status=2)


def test_recognized_generic_launch_error():
    out = derive_launch_outcome(
        obs(end=True, exit_status=2, foreground="zsh",
            pane_text="codex: unrecognized option '--nope'\n"), SIDECAR)
    assert_outcome(out, "prework_failure", "launch_failed",
                   "runtime_launch_error", exit_status=2)


def test_missing_start_sentinel_is_unknown():
    out = derive_launch_outcome(obs(start=False, pane_text="garbled"), SIDECAR)
    assert_outcome(out, "unknown", None, "missing_start_sentinel",
                   start_sentinel_seen=False)


def test_started_with_only_a_shell_in_the_foreground_is_unknown():
    """Whatever ran is gone and the wrapper never recorded a status. We cannot
    say it failed to launch — only that we cannot account for it."""
    out = derive_launch_outcome(obs(foreground="zsh"), SIDECAR)
    assert_outcome(out, "unknown", None, "shell_foreground", foreground="zsh")


def test_started_with_no_foreground_at_all_is_unknown():
    out = derive_launch_outcome(obs(foreground=None), SIDECAR)
    assert_outcome(out, "unknown", None, "missing_foreground", foreground=None)


def test_unreadable_pane_is_unknown():
    out = derive_launch_outcome(obs(readable=False), SIDECAR)
    assert_outcome(out, "unknown", None, "observation_timeout")


def test_pane_never_created_is_a_trusted_failure():
    out = pane_creation_failed()
    assert_outcome(out, "prework_failure", "launch_failed",
                   "pane_creation_failed", start_sentinel_seen=False,
                   end_sentinel_seen=False, exit_status=None, foreground=None)


def test_command_definitely_never_delivered_is_a_trusted_failure():
    out = derive_launch_outcome(obs(start=False, foreground=None), SIDECAR,
                                delivery=DELIVERY_ABSENT)
    assert_outcome(out, "prework_failure", "launch_failed",
                   "command_delivery_absent")


def test_delivery_with_possible_side_effects_is_unknown():
    """The line reached the pane and only the Enter failed. Closing the pane is
    not proof it never ran, so no fallback is licensed."""
    out = derive_launch_outcome(obs(start=False, foreground=None), SIDECAR,
                                delivery=DELIVERY_AMBIGUOUS)
    assert_outcome(out, "unknown", None, "delivery_ambiguous")


# --- what can never elevate a launch to prework_failure ---------------------

def test_no_sidecar_means_no_trusted_classification():
    """Forking without --launch-contract costs exactly this: the same pane text
    that would have been classified now degrades to unknown."""
    text = "error: unknown model 'gpt-5'\n"
    with_contract = derive_launch_outcome(
        obs(end=True, exit_status=2, foreground="zsh", pane_text=text), SIDECAR)
    without = derive_launch_outcome(
        obs(end=True, exit_status=2, foreground="zsh", pane_text=text), None)

    assert with_contract["state"] == "prework_failure"
    assert_outcome(without, "unknown", None, "unrecognized_exit")


def test_free_form_note_is_not_an_input():
    """Policy must never parse the human-facing note, and it structurally
    cannot: ``derive_launch_outcome`` is not given one."""
    import inspect
    params = inspect.signature(derive_launch_outcome).parameters
    assert "note" not in params
    assert set(params) == {"obs", "sidecar", "delivery"}


def test_exit_status_alone_never_produces_a_reason():
    """Every plausible "failure-looking" exit status, with no evidence behind
    it, stays unknown."""
    for status in (1, 2, 5, 42, 126, 127, 255, -1):
        out = derive_launch_outcome(
            obs(end=True, exit_status=status, foreground="zsh",
                pane_text="no recognizable output"), SIDECAR)
        assert out["state"] == "unknown", status
        assert out["reason_code"] is None


def test_a_pane_echoing_a_foreign_marker_is_not_trusted():
    """The marker is bound to one attempt id. Text carrying a different
    attempt's marker is someone else's evidence, not this launch's."""
    out = derive_launch_outcome(
        obs(end=True, exit_status=127, foreground="zsh",
            pane_text="__afork_exec_failed_0000000000000000__\n"), SIDECAR)
    assert_outcome(out, "unknown", None, "unrecognized_exit")


def test_marker_on_a_clean_exit_is_contradictory_not_trusted():
    """The marker is only reachable after a failed exec, which never exits 0.
    Seeing both means one of them is wrong; trust neither."""
    out = derive_launch_outcome(
        obs(end=True, exit_status=0, foreground="zsh", pane_text=MARKER),
        SIDECAR)
    assert_outcome(out, "unknown", None, "contradictory_evidence")


def test_marker_without_a_start_sentinel_is_contradictory():
    out = derive_launch_outcome(obs(start=False, pane_text=MARKER), SIDECAR)
    assert_outcome(out, "unknown", None, "contradictory_evidence")


def test_marker_takes_precedence_over_a_matching_signature():
    """Both present: the marker is afork's own proof and wins, and the reason
    it carries is the more specific one."""
    out = derive_launch_outcome(
        obs(end=True, exit_status=127, foreground="zsh",
            pane_text=f"error: unknown model 'x'\n{MARKER}\n"), SIDECAR)
    assert_outcome(out, "prework_failure", "runtime_unavailable",
                   "runtime_exec_failed")


def test_signatures_are_not_consulted_on_a_successful_run():
    """A run that exited 0 succeeded at whatever it did. Reading a rejection out
    of its output would be inventing evidence."""
    out = derive_launch_outcome(
        obs(end=True, exit_status=0, foreground="zsh",
            pane_text="grep -n 'unknown model' notes.txt\n"), SIDECAR)
    assert out["state"] == "unknown"


def test_signatures_are_not_consulted_while_the_agent_is_running():
    """An agent that printed the phrase and kept running is running."""
    out = derive_launch_outcome(
        obs(foreground="codex", pane_text="thinking about: unknown model ids"),
        SIDECAR)
    assert out["state"] == "started"


# --- the contract object itself ---------------------------------------------

def test_started_requires_a_live_non_shell_foreground():
    with pytest.raises(OutcomeContractError):
        launch_outcome("started", "agent_started", start_sentinel_seen=True,
                       foreground="bash")
    with pytest.raises(OutcomeContractError):
        launch_outcome("started", "agent_started", start_sentinel_seen=True,
                       foreground=None)


def test_started_cannot_carry_a_reason_or_an_exit_status():
    with pytest.raises(OutcomeContractError):
        launch_outcome("started", "agent_started", reason_code="launch_failed",
                       start_sentinel_seen=True, foreground="codex")
    with pytest.raises(OutcomeContractError):
        launch_outcome("started", "agent_started", start_sentinel_seen=True,
                       end_sentinel_seen=True, exit_status=0,
                       foreground="codex")


def test_an_untrusted_code_can_never_be_a_prework_failure():
    for code in ("unrecognized_exit", "missing_start_sentinel",
                 "observation_timeout", "shell_foreground",
                 "delivery_ambiguous", "contradictory_evidence"):
        with pytest.raises(OutcomeContractError):
            prework_failure(code)


def test_a_trusted_code_can_never_be_reported_as_unknown():
    for code in ("runtime_exec_failed", "model_rejected",
                 "runtime_launch_error", "pane_creation_failed",
                 "command_delivery_absent"):
        with pytest.raises(OutcomeContractError):
            unknown(code)


def test_reason_cannot_be_paired_with_the_wrong_evidence_by_hand():
    with pytest.raises(OutcomeContractError):
        launch_outcome("prework_failure", "runtime_exec_failed",
                       reason_code="model_unavailable")


def test_unrecognized_states_evidence_and_reasons_are_rejected():
    with pytest.raises(OutcomeContractError):
        launch_outcome("failed", "agent_started")
    with pytest.raises(OutcomeContractError):
        unknown("something_new")
    with pytest.raises(OutcomeContractError):
        launch_outcome("prework_failure", "model_rejected",
                       reason_code="not_a_reason")


def test_the_enums_are_exactly_the_published_ones():
    """These three lists are copied verbatim into both SKILL.md files. If this
    breaks, the docs and the code have diverged."""
    assert STATES == ("started", "prework_failure", "unknown")
    assert REASON_CODES == ("runtime_unavailable", "model_unavailable",
                            "launch_failed")
    assert EVIDENCE_CODES == (
        "agent_started", "runtime_exec_failed", "model_rejected",
        "runtime_launch_error", "pane_creation_failed",
        "command_delivery_absent", "unrecognized_exit",
        "missing_start_sentinel", "observation_timeout", "shell_foreground",
        "missing_foreground", "delivery_ambiguous", "contradictory_evidence")


def test_outcomes_are_json_serializable():
    """The object crosses a process boundary as JSON on stdout."""
    for out in (derive_launch_outcome(obs(), SIDECAR),
                pane_creation_failed(),
                derive_launch_outcome(obs(readable=False), SIDECAR)):
        assert json.loads(json.dumps(out)) == out


# --- sidecar loading is never fatal -----------------------------------------

def test_load_sidecar_degrades_quietly(tmp_path):
    """A missing, corrupt, or future-versioned sidecar must not break a fork.
    It costs classification, not the launch."""
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    future = tmp_path / "future.json"
    future.write_text(json.dumps({"version": 99, "attempt_id": "x"}))

    assert load_sidecar(None) is None
    assert load_sidecar(str(tmp_path / "absent.json")) is None
    assert load_sidecar(str(bad)) is None
    assert load_sidecar(str(future)) is None


def test_a_broken_signature_pattern_does_not_break_classification():
    """An adapter regex that does not compile is skipped, not raised."""
    sidecar = dict(SIDECAR, signatures={
        "model_rejected": ["([unclosed", r"(?i)\bunknown model\b"],
        "runtime_launch_error": [],
    })
    out = derive_launch_outcome(
        obs(end=True, exit_status=2, foreground="zsh",
            pane_text="error: unknown model 'x'\n"), sidecar)
    assert out["evidence_code"] == "model_rejected"


def test_a_sidecar_with_no_signatures_still_classifies_the_marker():
    sidecar = dict(SIDECAR, signatures={"model_rejected": [],
                                        "runtime_launch_error": []})
    out = derive_launch_outcome(
        obs(end=True, exit_status=127, foreground="zsh", pane_text=MARKER),
        sidecar)
    assert out["evidence_code"] == "runtime_exec_failed"


# --- a malformed version-1 sidecar is unusable, not fatal -------------------

MALFORMED = [
    ("signatures is a list", {"signatures": ["not-a-map"]}),
    ("signatures is a string", {"signatures": "model_rejected"}),
    ("signatures is a number", {"signatures": 7}),
    ("patterns are a bare string", {"signatures": {"model_rejected": "boom"}}),
    ("patterns are a number", {"signatures": {"model_rejected": 5}}),
    ("patterns are a nested map", {"signatures": {"model_rejected": {"a": 1}}}),
    ("a pattern is not a string", {"signatures": {"model_rejected": [None]}}),
    ("a pattern is a list", {"signatures": {"model_rejected": [["x"]]}}),
    ("exec_marker is a list", {"exec_marker": ["marker"]}),
    ("exec_marker is a number", {"exec_marker": 1}),
    ("exec_marker is a map", {"exec_marker": {"m": MARKER}}),
]


@pytest.mark.parametrize("label,bad", MALFORMED, ids=[m[0] for m in MALFORMED])
def test_a_malformed_version_1_sidecar_is_rejected_whole(tmp_path, label, bad):
    """Announcing version 1 is a claim, not proof. Reading the well-formed half
    of a corrupt file is how a corrupt file ends up licensing a retry."""
    path = tmp_path / "lc.json"
    path.write_text(json.dumps(dict(SIDECAR, **bad)))
    assert load_sidecar(str(path)) is None, label


@pytest.mark.parametrize("label,bad", MALFORMED, ids=[m[0] for m in MALFORMED])
def test_a_malformed_sidecar_ends_as_unknown_not_as_a_crash(tmp_path, label,
                                                            bad):
    """End to end, the way a real fork runs it. The crash this guards against
    would land AFTER the pane exists, leaving the dispatcher with no
    launch_outcome at all for a launch that really was attempted — the one
    thing the contract promises can never happen."""
    path = tmp_path / "lc.json"
    path.write_text(json.dumps(dict(SIDECAR, **bad)))
    out = derive_launch_outcome(
        obs(end=True, exit_status=127, foreground="zsh",
            pane_text=f"launch.sh: codex: not found\n{MARKER}"),
        load_sidecar(str(path)))
    assert list(out) == list(OUTCOME_FIELDS)
    assert out["state"] == "unknown", label
    assert out["reason_code"] is None


@pytest.mark.parametrize("label,bad", MALFORMED, ids=[m[0] for m in MALFORMED])
def test_deriving_from_a_hand_built_malformed_dict_never_raises(label, bad):
    """``derive_launch_outcome`` is public and takes a dict, so a caller can
    reach it without going through ``load_sidecar``'s validation. It still may
    not raise; whatever it decides must be a valid contract object."""
    out = derive_launch_outcome(
        obs(end=True, exit_status=127, foreground="zsh",
            pane_text=f"launch.sh: codex: not found\n{MARKER}"),
        dict(SIDECAR, **bad))
    assert list(out) == list(OUTCOME_FIELDS)
    assert out["state"] in STATES, label


def test_a_bare_string_pattern_is_not_iterated_character_by_character():
    """str is iterable, so an un-listed pattern would be walked one character
    at a time — and single characters match almost anything. That is a false
    TRUSTED classification, strictly worse than the crash."""
    sidecar = dict(SIDECAR, signatures={"model_rejected": "xyz",
                                        "runtime_launch_error": []})
    out = derive_launch_outcome(
        obs(end=True, exit_status=2, foreground="zsh",
            pane_text="x marks the spot\n"), sidecar)
    assert out["state"] == "unknown"
    assert out["evidence_code"] == "unrecognized_exit"


def test_a_well_formed_sidecar_missing_signatures_entirely_still_loads(tmp_path):
    """Absent is not malformed: an adapter that declared nothing yields no
    match, which is exactly what an empty signature table already means."""
    body = {k: v for k, v in SIDECAR.items() if k != "signatures"}
    path = tmp_path / "lc.json"
    path.write_text(json.dumps(body))
    loaded = load_sidecar(str(path))
    assert loaded is not None
    out = derive_launch_outcome(
        obs(end=True, exit_status=127, foreground="zsh", pane_text=MARKER),
        loaded)
    assert out["evidence_code"] == "runtime_exec_failed"


# --- the shared module must not drift ---------------------------------------

def test_outcome_module_is_byte_identical_to_aforks():
    """afork and tfork ship as independent skill directories, so neither can
    import the other. The contract is duplicated on purpose — this test is what
    keeps the duplicate honest."""
    mine = Path(__file__).resolve().parents[1] / "tforklib" / "outcome.py"
    theirs = (Path(__file__).resolve().parents[2] / "afork" / "aforklib"
              / "outcome.py")
    if not theirs.exists():
        pytest.skip("afork skill not checked out beside tfork")
    assert mine.read_bytes() == theirs.read_bytes(), (
        "aforklib/outcome.py and tforklib/outcome.py have diverged — the two "
        "halves of the launch contract no longer agree")
