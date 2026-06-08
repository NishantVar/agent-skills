"""afork v2 pipeline: plain + custom modes, posture precedence, and the
fail-closed gate (a declared restriction the adapter can't enforce is a
refusal, overridable only with explicit --allow-unenforced)."""

import pytest

from aforklib import run_afork
from aforklib.errors import AforkError


def _codex_port(tmp_path, name, body):
    d = tmp_path / ".codex" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.toml").write_text(body)


def _claude_port(tmp_path, name, body="# agent\n"):
    d = tmp_path / ".claude" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(body)


# --- Plain mode (no agent) for every launchable runtime ---

def test_codex_plain_none_yolo(tmp_path):
    out = run_afork("codex", cwd=str(tmp_path))
    assert out["ok"] is True
    assert out["agent"] is None
    assert out["posture"] == "none"
    assert out["enforced"] is True
    assert out["workdir"] is None  # no temp launcher in plain mode
    assert "--dangerously-bypass-approvals-and-sandbox" in out["command"]
    assert 'model_reasoning_effort="xhigh"' in out["command"]


def test_claude_plain_none_launches(tmp_path):
    out = run_afork("claude", cwd=str(tmp_path))
    assert out["ok"] is True
    assert out["posture"] == "none"
    assert "--dangerously-skip-permissions" in out["command"]
    assert "--model opus" in out["command"]
    assert "--effort high" in out["command"]


def test_pi_plain_none_no_bypass_flag(tmp_path):
    out = run_afork("pi", cwd=str(tmp_path))
    assert out["ok"] is True
    assert out["command"].startswith("pi")
    assert "--dangerously" not in out["command"]


# --- Posture precedence: flag > definition > none ---

def test_flag_overrides_definition(tmp_path):
    _codex_port(tmp_path, "rev", 'sandbox_mode = "read-only"\n')
    out = run_afork("codex", "rev", permission="workspace-write",
                    cwd=str(tmp_path))
    assert out["posture"] == "workspace-write"


def test_definition_used_when_no_flag(tmp_path):
    _codex_port(tmp_path, "rev",
                'sandbox_mode = "read-only"\ndeveloper_instructions = "x"\n')
    out = run_afork("codex", "rev", cwd=str(tmp_path))
    assert out["posture"] == "read-only"
    assert out["enforced"] is True


def test_no_sandbox_codex_def_defaults_to_none(tmp_path):
    # v1 raised missing_sandbox_mode; v2 defaults to none (yolo).
    _codex_port(tmp_path, "nosb", 'developer_instructions = "x"\n')
    out = run_afork("codex", "nosb", cwd=str(tmp_path))
    assert out["posture"] == "none"
    assert out["enforced"] is True


def test_danger_full_access_normalizes_to_none(tmp_path):
    _codex_port(tmp_path, "df",
                'sandbox_mode = "danger-full-access"\ndeveloper_instructions = "x"\n')
    out = run_afork("codex", "df", cwd=str(tmp_path))
    assert out["posture"] == "none"


# --- Codex restricted is enforceable ---

def test_codex_read_only_flag_is_enforced(tmp_path):
    out = run_afork("codex", permission="read-only", cwd=str(tmp_path))
    assert out["ok"] is True
    assert out["posture"] == "read-only"
    assert out["enforced"] is True
    assert "--sandbox read-only" in out["command"]


def test_codex_unknown_posture_fails_closed(tmp_path):
    _codex_port(tmp_path, "weird", 'sandbox_mode = "wide-open"\n')
    with pytest.raises(AforkError) as exc:
        run_afork("codex", "weird", cwd=str(tmp_path))
    assert exc.value.code == "unenforceable"


# --- Claude/pi restricted fail closed; --allow-unenforced overrides ---

def test_claude_read_only_unenforceable(tmp_path):
    with pytest.raises(AforkError) as exc:
        run_afork("claude", permission="read-only", cwd=str(tmp_path))
    assert exc.value.code == "unenforceable"


def test_claude_read_only_allow_unenforced_proceeds_marked(tmp_path):
    out = run_afork("claude", permission="read-only", cwd=str(tmp_path),
                    allow_unenforced=True)
    assert out["ok"] is True
    assert out["enforced"] is False
    # none-flag path is unreachable, so no permission flag is emitted.
    assert "--dangerously-skip-permissions" not in out["command"]


def test_pi_read_only_unenforceable(tmp_path):
    with pytest.raises(AforkError) as exc:
        run_afork("pi", permission="read-only", cwd=str(tmp_path))
    assert exc.value.code == "unenforceable"


# --- pi has no agent dir: custom request errors ---

def test_pi_custom_is_custom_unsupported(tmp_path):
    with pytest.raises(AforkError) as exc:
        run_afork("pi", "somagent", cwd=str(tmp_path))
    assert exc.value.code == "custom_unsupported"


# --- antigravity / unknown runtime ---

def test_antigravity_is_runtime_unsupported(tmp_path):
    with pytest.raises(AforkError) as exc:
        run_afork("antigravity", cwd=str(tmp_path))
    assert exc.value.code == "runtime_unsupported"


def test_codex_non_string_sandbox_mode_is_parse_error_not_overridable(tmp_path):
    # A list-valued sandbox_mode is a malformed definition: a fix-the-file
    # port_unparsable error, NOT an --allow-unenforced-overridable refusal.
    _codex_port(tmp_path, "weird",
                'sandbox_mode = ["read-only"]\ndeveloper_instructions = "x"\n')
    with pytest.raises(AforkError) as exc:
        run_afork("codex", "weird", cwd=str(tmp_path))
    assert exc.value.code == "port_unparsable"
    # Even --allow-unenforced must not bypass a broken definition file.
    with pytest.raises(AforkError) as exc2:
        run_afork("codex", "weird", cwd=str(tmp_path), allow_unenforced=True)
    assert exc2.value.code == "port_unparsable"
