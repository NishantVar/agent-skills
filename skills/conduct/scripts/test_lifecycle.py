"""Lifecycle + status orchestration with a fully stubbed cmux backend.

The cmux seam (cmux module) is monkeypatched so no live cmux/agent is
touched. We verify: ownership-gated control, runtime_unknown / verb_unsupported
fail-closed refusals, that an owned claude `clear` dispatches the right
keystroke sequence (captured, not sent), and the JSON envelope shape.
"""

import pytest

import adapters
import cmux
import core
import ownership

CALLER = "uuid-caller"
TGT = "uuid-target"
OTHER = "uuid-other-owner"


@pytest.fixture
def stub_cmux(monkeypatch, tmp_path):
    """Stub the whole cmux seam + point the manifest at a temp file."""
    # Isolate the manifest.
    monkeypatch.setattr(ownership, "MANIFEST_PATH", tmp_path / "owners.json")
    monkeypatch.setattr(ownership, "LOCK_PATH", tmp_path / "owners.lock")
    monkeypatch.setattr(ownership, "CONDUCT_DIR", tmp_path)

    state = {
        # surface UUID -> record (as surface_index would return)
        "index": {
            TGT: {"uuid": TGT, "surface_ref": "surface:7", "title": "worker",
                  "type": "terminal", "tty": "ttys9",
                  "workspace_ref": "workspace:3", "workspace_title": "ws",
                  "window_ref": "window:1"},
            CALLER: {"uuid": CALLER, "surface_ref": "surface:1",
                     "title": "boss", "type": "terminal", "tty": "ttys1",
                     "workspace_ref": "workspace:3", "workspace_title": "ws",
                     "window_ref": "window:1"},
            OTHER: {"uuid": OTHER, "surface_ref": "surface:2", "title": "rival",
                    "type": "terminal", "tty": "ttys2",
                    "workspace_ref": "workspace:3", "workspace_title": "ws",
                    "window_ref": "window:1"},
        },
        "procs": {TGT: ["claude.exe", "node"]},  # target runs claude
        "screen": "  ctx:42%  /repo  main",
        "sent": [],  # captured keystroke steps
    }

    monkeypatch.setattr(cmux, "caller_surface_uuid", lambda: CALLER)
    monkeypatch.setattr(cmux, "tree", lambda: {"_state": state})
    monkeypatch.setattr(cmux, "surface_index",
                        lambda t=None: state["index"])
    monkeypatch.setattr(cmux, "resolve_to_uuid",
                        lambda ref, t=None: next(
                            (u for u, r in state["index"].items()
                             if r["surface_ref"] == ref or u == ref), None))
    monkeypatch.setattr(cmux, "runtime_processes", lambda t=None: state["procs"])
    monkeypatch.setattr(cmux, "read_screen",
                        lambda sref, wref, lines=60: state["screen"])
    monkeypatch.setattr(cmux, "send_text",
                        lambda s, w, txt: state["sent"].append(("text", txt)))
    monkeypatch.setattr(cmux, "send_key",
                        lambda s, w, k: state["sent"].append(("key", k)))
    monkeypatch.setattr(cmux, "close_surface",
                        lambda s, w: state["sent"].append(("close", None)))
    return state


def _assert_envelope(obj):
    """Envelope shape parity with p2p/afork on both ok paths."""
    for k in ("ok", "human_message"):
        assert k in obj
    if not obj["ok"]:
        for k in ("code", "agent_instruction", "action_required",
                  "handoff_skill", "rerun_argv", "retryable"):
            assert k in obj, f"ok:false envelope missing {k}"
        # rerun_argv must always be a list (never dropped to a missing/None).
        assert isinstance(obj["rerun_argv"], list)


# ---------------- status / first-touch ----------------

def test_status_single_first_touch_claims(stub_cmux):
    out = core.run_status(agent_ref="surface:7")
    _assert_envelope(out)
    assert out["ok"] is True
    assert out["agent"]["type"] == "claude"
    assert out["agent"]["context_pct"] == 42
    # The touch claimed the target for the caller.
    assert ownership.load()[TGT]["owner_uuid"] == CALLER


def test_status_target_unknown(stub_cmux):
    out = core.run_status(agent_ref="surface:999")
    _assert_envelope(out)
    assert out["code"] == "target_unknown"


def test_status_all_owned_set_only(stub_cmux):
    core.run_claim("surface:7")  # claim TGT
    out = core.run_status(all_owned=True)
    assert out["ok"] is True
    assert out["scope"] == "owned_set"
    assert {a["uuid"] for a in out["agents"]} == {TGT}


def test_status_view_includes_state_field(stub_cmux):
    # Regression: _agent_view must emit `state` (SKILL/CLI advertise it).
    out = core.run_status(agent_ref="surface:7")
    assert "state" in out["agent"]
    # idle screen (no "esc to interrupt") -> null state.
    assert out["agent"]["state"] is None


def test_status_view_state_busy_when_interrupting(stub_cmux):
    stub_cmux["screen"] = "  ctx:42%  /repo  main\n• Working (3s • esc to interrupt)"
    out = core.run_status(agent_ref="surface:7")
    assert out["agent"]["state"] == "busy"


def test_status_codex_runtime_and_context_pct(stub_cmux):
    # Ground-truth codex: arch-suffixed proc name + `Context NN% left` footer.
    stub_cmux["procs"] = {TGT: ["codex-aarch64-a", "zsh"]}
    stub_cmux["screen"] = "gpt-5.5 xhigh · Context 37% left · ~/repo"
    out = core.run_status(agent_ref="surface:7")
    assert out["ok"] is True
    assert out["agent"]["type"] == "codex"        # not fail-closed/unknown
    assert out["agent"]["context_pct"] == 63       # 37 left -> 63 used
    assert "state" in out["agent"]


# ---------------- ownership refusal on control ----------------

def test_control_owned_by_other_refused(stub_cmux):
    # Pre-seed: OTHER owns TGT and is live.
    with ownership.manifest_lock():
        m = ownership.load()
        m[TGT] = {"owner_uuid": OTHER, "claimed_at": "x"}
        ownership.save(m)
    out = core.run_lifecycle("clear", agent_ref="surface:7")
    _assert_envelope(out)
    assert out["code"] == "not_owner"
    assert out["owner"] == OTHER
    assert stub_cmux["sent"] == []  # nothing injected


# ---------------- runtime-aware fail-closed ----------------

def test_clear_unknown_runtime_refused(stub_cmux):
    stub_cmux["procs"] = {TGT: ["zsh"]}  # not a supported agent
    out = core.run_lifecycle("clear", agent_ref="surface:7")
    _assert_envelope(out)
    assert out["code"] == "runtime_unknown"
    assert stub_cmux["sent"] == []  # never injected blindly


def test_compact_unsupported_for_pi_refused(stub_cmux):
    stub_cmux["procs"] = {TGT: ["pi"]}
    out = core.run_lifecycle("compact", agent_ref="surface:7")
    _assert_envelope(out)
    assert out["code"] == "verb_unsupported"
    assert out["runtime"] == "pi"
    assert stub_cmux["sent"] == []


# ---------------- rerun_argv survives the refusal builders ----------------

# Regression guard: owned_by_other / not_owner / runtime_unknown /
# verb_unsupported previously accepted a rerun_argv param but never wrote it
# into the envelope (Pyright "rerun_argv is not accessed"). These assert the
# caller-supplied rerun_argv actually round-trips to the emitted JSON.

RERUN = ["conduct.py", "clear", "--agent", "surface:7"]


def test_not_owner_carries_rerun_argv(stub_cmux):
    with ownership.manifest_lock():
        m = ownership.load()
        m[TGT] = {"owner_uuid": OTHER, "claimed_at": "x"}
        ownership.save(m)
    out = core.run_lifecycle("clear", agent_ref="surface:7",
                                   rerun_argv=RERUN)
    assert out["code"] == "not_owner"
    assert out["rerun_argv"] == RERUN


def test_runtime_unknown_carries_rerun_argv(stub_cmux):
    stub_cmux["procs"] = {TGT: ["zsh"]}
    out = core.run_lifecycle("clear", agent_ref="surface:7",
                                   rerun_argv=RERUN)
    assert out["code"] == "runtime_unknown"
    assert out["rerun_argv"] == RERUN


def test_verb_unsupported_carries_rerun_argv(stub_cmux):
    stub_cmux["procs"] = {TGT: ["pi"]}
    out = core.run_lifecycle("compact", agent_ref="surface:7",
                                   rerun_argv=RERUN)
    assert out["code"] == "verb_unsupported"
    assert out["rerun_argv"] == RERUN


def test_owned_by_other_carries_rerun_argv(stub_cmux):
    # claim path (not lifecycle) returns owned_by_other directly.
    with ownership.manifest_lock():
        m = ownership.load()
        m[TGT] = {"owner_uuid": OTHER, "claimed_at": "x"}
        ownership.save(m)
    out = core.run_claim("surface:7", rerun_argv=RERUN)
    assert out["code"] == "owned_by_other"
    assert out["rerun_argv"] == RERUN


# ---------------- successful dispatch (captured, not live) ----------------

def test_owned_claude_clear_dispatches_sequence(stub_cmux):
    out = core.run_lifecycle("clear", agent_ref="surface:7")
    _assert_envelope(out)
    assert out["ok"] is True
    assert out["runtime"] == "claude"
    assert stub_cmux["sent"] == [("text", "/clear"), ("key", "enter")]


def test_interrupt_sends_escape(stub_cmux):
    out = core.run_lifecycle("interrupt", agent_ref="surface:7")
    assert out["ok"] is True
    assert stub_cmux["sent"] == [("key", "escape")]


def test_kill_closes_surface(stub_cmux):
    out = core.run_lifecycle("kill", agent_ref="surface:7")
    assert out["ok"] is True
    assert stub_cmux["sent"] == [("close", None)]


def test_all_broadcast_owned_set_only(stub_cmux):
    core.run_claim("surface:7")  # own TGT only
    out = core.run_lifecycle("interrupt", all_owned=True)
    assert out["ok"] is True
    assert out["scope"] == "owned_set"
    assert out["count"] == 1
    assert out["applied"] == 1
    assert stub_cmux["sent"] == [("key", "escape")]


# ---------------- release ----------------

def test_release_drops_claim(stub_cmux):
    core.run_claim("surface:7")
    out = core.run_release("surface:7")
    assert out["ok"] is True
    assert out["released"] is True
    assert TGT not in ownership.load()


def test_not_in_cmux_when_no_caller(stub_cmux, monkeypatch):
    monkeypatch.setattr(cmux, "caller_surface_uuid", lambda: None)
    out = core.run_status(agent_ref="surface:7")
    _assert_envelope(out)
    assert out["code"] == "not_in_cmux"
