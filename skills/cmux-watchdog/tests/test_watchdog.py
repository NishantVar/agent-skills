"""Unit tests for the pure detection / parsing logic in watchdog.py."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import watchdog as w


# --- unsent_p2p -----------------------------------------------------------

UNSENT = """\
● Done reviewing the auth module.

╭────────────────────────────────────────────────╮
│ > [from: qa_lead] please review PR #42 when free │
╰────────────────────────────────────────────────╯
  ? for shortcuts
"""

SENT_PROCESSING = """\
[from: qa_lead] please review PR #42 when free

  Thinking… (esc to interrupt)
"""

SENT_RESPONDED = """\
[from: qa_lead] please review PR #42 when free

● I'll take a look at PR #42 now.
● Reading diff...
"""

NO_FRAME = """\
● All tests passing.
╭──────────────────────╮
│ >                     │
╰──────────────────────╯
"""


def test_unsent_detected_when_frame_in_composer():
    f = w.detect_unsent_p2p(UNSENT)
    assert f is not None
    assert f.signature == "unsent_p2p"
    assert f.tier == "safe"
    assert f.remediation == "send_enter"
    assert "qa_lead" in f.evidence


def test_unsent_skipped_when_agent_processing():
    assert w.detect_unsent_p2p(SENT_PROCESSING) is None


def test_unsent_skipped_when_agent_responded():
    assert w.detect_unsent_p2p(SENT_RESPONDED) is None


def test_unsent_skipped_without_frame():
    assert w.detect_unsent_p2p(NO_FRAME) is None


def test_unsent_skipped_when_frame_scrolled_far_up():
    screen = "[from: qa_lead] old message\n" + "\n".join(f"line {i}" for i in range(50))
    assert w.detect_unsent_p2p(screen) is None


# --- api_error ------------------------------------------------------------

def test_api_error_overloaded():
    screen = "doing work...\nAPI Error: 529 overloaded_error\n"
    f = w.detect_api_error(screen)
    assert f is not None
    assert f.signature == "api_error"
    assert f.tier == "risky"


def test_api_error_connection():
    screen = "fetching...\nError: connection error (ECONNRESET)\n"
    assert w.detect_api_error(screen) is not None


def test_api_error_rate_limit():
    assert w.detect_api_error("hmm\n429 rate_limit_error\n") is not None


def test_api_error_absent_on_clean_output():
    assert w.detect_api_error("● All tests passing.\n  ? for shortcuts\n") is None


def test_api_error_only_in_recent_tail():
    screen = "API Error: 529\n" + "\n".join(f"ok line {i}" for i in range(40))
    assert w.detect_api_error(screen) is None


def test_api_error_ignores_token_count_in_thinking_status_line():
    # Claude/Codex thinking status lines render token counts that collide with
    # HTTP codes ("429 tokens", "500 tokens") — must NOT flag a healthy agent.
    assert w.detect_api_error("✳ Billowing… (9s · ↓ 429 tokens · thinking with high effort)\n") is None
    assert w.detect_api_error("✽ Working… (12s · ↑ 500 tokens)\n") is None
    assert w.detect_api_error("● thinking (3s · ↓ 503 tokens · esc to interrupt)\n") is None


def test_api_error_still_fires_on_real_codes_and_phrases():
    # The tightening must not suppress genuine errors.
    assert w.detect_api_error("hmm\n429 Too Many Requests\n") is not None
    assert w.detect_api_error("HTTP 503 Service Unavailable\n") is not None
    assert w.detect_api_error("Error: rate limit exceeded\n") is not None
    assert w.detect_api_error("API Error: 500 internal server error\n") is not None
    # "Too Many Requests" phrase alone (no bare code) still flags.
    assert w.detect_api_error("Error: Too Many Requests, please retry\n") is not None


def test_api_error_token_count_without_error_phrase_is_accepted_blind_spot():
    # Documented tradeoff: a bare "<code> tokens" status never flags. A real error
    # that ONLY says "<code> tokens ... exceeded" with no rate-limit/HTTP phrase is
    # the accepted residual blind spot (rare — real API errors carry a phrase).
    assert w.detect_api_error("✳ Billowing… (9s · ↓ 429 tokens)\n") is None


# --- redaction ------------------------------------------------------------

def test_redact_masks_token_in_evidence():
    screen = (
        "[from: builder] token is sk-ABCDEFGHIJKLMNOPQRSTUVWX\n"
        "╰──────╯\n  ? for shortcuts\n"
    )
    f = w.detect_unsent_p2p(screen)
    assert f is not None
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWX" not in f.evidence
    assert "REDACTED" in f.evidence


def test_redact_passthrough_clean_text():
    assert w.redact("nothing secret here") == "nothing secret here"


# --- detect aggregate -----------------------------------------------------

def test_detect_returns_both_when_present():
    screen = UNSENT + "\nAPI Error: 529 overloaded_error\n"
    sigs = {f.signature for f in w.detect(screen)}
    # api_error is near the very bottom; unsent frame is above it but the
    # error line is "content" below the frame, so only api_error fires here.
    assert "api_error" in sigs


# --- settled_lines --------------------------------------------------------

def test_settled_strips_composer_box_and_footer():
    got = w.settled_lines(UNSENT)
    # only the real output line survives
    assert got == ["● Done reviewing the auth module."]


def test_settled_drops_blank_and_box_only_lines():
    screen = "● first\n\n╭───╮\n╰───╯\n● second\n"
    assert w.settled_lines(screen) == ["● first", "● second"]


def test_settled_drops_spinner_lines():
    screen = "● working on it\n  Thinking… (esc to interrupt)\n● done\n"
    assert w.settled_lines(screen) == ["● working on it", "● done"]


def test_settled_redacts_secrets():
    screen = "● secret is sk-ABCDEFGHIJKLMNOPQRSTUVWX here\n"
    got = w.settled_lines(screen)
    assert len(got) == 1
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWX" not in got[0]
    assert "REDACTED" in got[0]


def test_settled_keeps_real_output_in_order():
    screen = "● step one\n● step two\n● step three\n"
    assert w.settled_lines(screen) == ["● step one", "● step two", "● step three"]


def test_settled_keeps_prose_mentioning_footer_keywords():
    # real transcript lines that merely contain footer keywords must survive
    screen = (
        "● we spent 5000 tokens on this run\n"
        "● remember to bypass the stale cache\n"
        "● auto-accept was discussed in the meeting\n"
    )
    assert w.settled_lines(screen) == [
        "● we spent 5000 tokens on this run",
        "● remember to bypass the stale cache",
        "● auto-accept was discussed in the meeting",
    ]


def test_settled_drops_agent_status_bars():
    # the volatile UI status/mode bars must be stripped (else anchoring churns)
    screen = (
        "● real output line\n"
        "gpt-5.5 xhigh · Context 48% left · ~/git/agent-skills · main\n"
        "  ctx:24%  /git/agent-skills  main [?]  c\n"
        "  -- INSERT -- ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents\n"
        "─ Worked for 3m 36s ────────────────────────────\n"
    )
    assert w.settled_lines(screen) == ["● real output line"]


def test_settled_drops_composer_prompt_lines():
    screen = "● real output\n❯ \n› Find and fix a bug in @filename\n"
    assert w.settled_lines(screen) == ["● real output"]


# --- append_new -----------------------------------------------------------

def test_append_new_seeds_on_empty_prev():
    new, gap = w.append_new([], ["a", "b", "c"])
    assert new == ["a", "b", "c"]
    assert gap is False


def test_append_new_appends_after_anchor():
    new, gap = w.append_new(["a", "b", "c"], ["a", "b", "c", "d", "e"])
    assert new == ["d", "e"]
    assert gap is False


def test_append_new_handles_scroll_off():
    # 'a' scrolled past the window; b,c still visible, d is new
    new, gap = w.append_new(["a", "b", "c"], ["b", "c", "d"])
    assert new == ["d"]
    assert gap is False


def test_append_new_no_change_returns_empty():
    new, gap = w.append_new(["a", "b", "c"], ["a", "b", "c"])
    assert new == []
    assert gap is False


def test_append_new_no_anchor_overcaptures_with_gap():
    # a burst scrolled the entire prior window away — no overlap at all
    new, gap = w.append_new(["a", "b", "c"], ["x", "y", "z"])
    assert new == ["x", "y", "z"]
    assert gap is True


def test_append_new_preserves_repeated_identical_lines():
    # the agent legitimately printed "● B" twice — the second is new, not a dup
    new, gap = w.append_new(["● A", "● B"], ["● A", "● B", "● B"])
    assert new == ["● B"]
    assert gap is False


def test_append_new_partial_line_completed():
    # last tick captured a mid-render line; this tick it completed. The
    # completed line must reach the journal (over-capture + gap, never lost).
    prev = ["● A", "● B", "● downloadi"]
    curr = ["● A", "● B", "● downloading done", "● C"]
    new, gap = w.append_new(prev, curr)
    assert "● downloading done" in new
    assert "● C" in new
    assert gap is True


# --- slugify --------------------------------------------------------------

def test_slugify_lowercases_and_replaces_spaces():
    assert w.slugify("Meta Eval") == "meta-eval"


def test_slugify_collapses_runs_and_trims():
    assert w.slugify("  Foo!!__Bar  ") == "foo-bar"


def test_slugify_passes_through_simple():
    assert w.slugify("builder") == "builder"


def test_slugify_underscore_becomes_dash():
    # underscores must not survive — they would break the __ filename delimiter
    assert "_" not in w.slugify("qa_lead")
    assert w.slugify("qa_lead") == "qa-lead"


def test_slugify_empty_when_no_alnum():
    assert w.slugify("!!!") == ""


# --- tree parsing + scope -------------------------------------------------

TREE = """\
window window:1 [current]
├── workspace workspace:2 "Meta Eval"
│   ├── pane pane:2 [focused]
│   │   └── surface surface:2 [terminal] "builder" [selected] tty=ttys005
│   └── pane pane:3
│       └── surface surface:3 [browser] "preview"
└── workspace workspace:5 "Other Task"
    └── pane pane:7
        └── surface surface:9 [terminal] "qa_lead"
"""


def test_parse_tree_keeps_only_terminals():
    surfaces = w.parse_tree(TREE)
    refs = {s.surface_ref for s in surfaces}
    assert refs == {"surface:2", "surface:9"}  # browser surface:3 dropped


def test_parse_tree_attaches_workspace():
    surfaces = {s.surface_ref: s for s in w.parse_tree(TREE)}
    assert surfaces["surface:2"].workspace_ref == "workspace:2"
    assert surfaces["surface:2"].workspace_title == "Meta Eval"
    assert surfaces["surface:9"].workspace_title == "Other Task"


def test_filter_scope_all():
    surfaces = w.parse_tree(TREE)
    assert len(w.filter_scope(surfaces, "all")) == 2


def test_filter_scope_by_ref():
    surfaces = w.parse_tree(TREE)
    got = w.filter_scope(surfaces, "workspace:5")
    assert {s.surface_ref for s in got} == {"surface:9"}


def test_filter_scope_by_title():
    surfaces = w.parse_tree(TREE)
    got = w.filter_scope(surfaces, "Meta Eval")
    assert {s.surface_ref for s in got} == {"surface:2"}


def test_filter_scope_caller_workspace_env(monkeypatch):
    monkeypatch.setenv("CMUX_WORKSPACE_ID", "workspace:5")
    surfaces = w.parse_tree(TREE)
    got = w.filter_scope(surfaces, None)
    assert {s.surface_ref for s in got} == {"surface:9"}


_WS_UUID = "8E6903E5-D90D-4F88-BE5D-1C0A29E70746"


def test_filter_scope_resolves_uuid_to_caller_ref():
    # The overnight regression: a workspace UUID scope (cmux tree only yields
    # workspace:N refs) must resolve to the caller's ref, NOT match zero.
    surfaces = w.parse_tree(TREE)
    got = w.filter_scope(surfaces, _WS_UUID, caller_ws_ref="workspace:5")
    assert {s.surface_ref for s in got} == {"surface:9"}


def test_filter_scope_default_uuid_env_resolves(monkeypatch):
    # bare scan/watch (scope=None) inheriting a UUID CMUX_WORKSPACE_ID resolves
    # via the caller ref instead of journaling zero — the exact overnight bug.
    monkeypatch.setenv("CMUX_WORKSPACE_ID", _WS_UUID)
    surfaces = w.parse_tree(TREE)
    got = w.filter_scope(surfaces, None, caller_ws_ref="workspace:5")
    assert {s.surface_ref for s in got} == {"surface:9"}


def test_filter_scope_uuid_unresolvable_degrades_to_all(monkeypatch):
    # If the UUID can't be resolved (no CMUX_SURFACE_ID), degrade to all rather
    # than silently matching zero.
    monkeypatch.delenv("CMUX_SURFACE_ID", raising=False)
    surfaces = w.parse_tree(TREE)
    got = w.filter_scope(surfaces, _WS_UUID)  # caller_ws_ref None -> identify -> None -> all
    assert len(got) == len(surfaces)


def test_filter_scope_ref_and_title_unchanged_with_uuid_support():
    # ref / title / all paths must still behave exactly as before.
    surfaces = w.parse_tree(TREE)
    assert len(w.filter_scope(surfaces, "all")) == 2
    assert {s.surface_ref for s in w.filter_scope(surfaces, "workspace:5")} == {"surface:9"}
    assert {s.surface_ref for s in w.filter_scope(surfaces, "Meta Eval")} == {"surface:2"}


def test_scope_matches_resolves_uuid():
    assert w._scope_matches("workspace:5", "Meta Eval", _WS_UUID, caller_ws_ref="workspace:5")
    assert not w._scope_matches("workspace:6", "Other", _WS_UUID, caller_ws_ref="workspace:5")


# --- journaling -----------------------------------------------------------

DATE = "2026-06-03"


def test_journal_surface_seeds_then_appends_only_new(tmp_path, monkeypatch):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    s = w.SurfaceRef("surface:2", "workspace:2", "Meta Eval", "builder")
    prev: dict = {}
    w.journal_surface(s, "● first line\n", prev, DATE)
    path = tmp_path / "journal" / DATE / "meta-eval__builder__surface:2.log"
    assert path.exists()
    body = path.read_text()
    assert "● first line" in body
    assert body.startswith("# ")  # ISO batch header
    w.journal_surface(s, "● first line\n● second line\n", prev, DATE)
    body2 = path.read_text()
    assert body2.count("● first line") == 1   # seed not re-written
    assert body2.count("● second line") == 1  # only the new line appended


def test_journal_surface_redacts_and_flags_gap(tmp_path, monkeypatch):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    s = w.SurfaceRef("surface:9", "workspace:5", "Other Task", "qa_lead")
    prev = {"surface:9": ["● old anchor"]}  # no overlap with curr → gap
    w.journal_surface(s, "● secret sk-ABCDEFGHIJKLMNOPQRSTUVWX\n", prev, DATE)
    path = tmp_path / "journal" / DATE / "other-task__qa-lead__surface:9.log"
    body = path.read_text()
    assert "gap" in body
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWX" not in body
    assert "REDACTED" in body


def test_journal_surface_noop_when_nothing_new(tmp_path, monkeypatch):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    s = w.SurfaceRef("surface:2", "workspace:2", "Meta Eval", "builder")
    prev: dict = {}
    w.journal_surface(s, "● only line\n", prev, DATE)
    path = tmp_path / "journal" / DATE / "meta-eval__builder__surface:2.log"
    size1 = path.stat().st_size
    w.journal_surface(s, "● only line\n", prev, DATE)  # identical screen
    assert path.stat().st_size == size1


def test_update_journal_index_records_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    surfaces = [w.SurfaceRef("surface:2", "workspace:2", "Meta Eval", "builder")]
    w.update_journal_index(DATE, surfaces)
    idx = json.loads((tmp_path / "journal" / DATE / "index.json").read_text())
    entry = idx["meta-eval__builder__surface:2.log"]
    assert entry["workspace_ref"] == "workspace:2"
    assert entry["workspace_title"] == "Meta Eval"   # raw title, not slug
    assert entry["surface_ref"] == "surface:2"
    assert entry["title"] == "builder"


# --- digest ---------------------------------------------------------------

def _write_journal(root: Path, date: str, name: str, text: str,
                   *, ws_ref: str = "", ws_title: str | None = None) -> Path:
    """Write a journal .log AND register its identity in the day's sidecar index,
    exactly as the watch loop does. ws_title defaults to the filename's ws slug."""
    d = root / "journal" / date
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(text, encoding="utf-8")
    ws_slug, title, surface_ref = name[: -len(".log")].rsplit("__", 2)
    idx_path = d / "index.json"
    try:
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        idx = {}
    idx[name] = {
        "workspace_ref": ws_ref,
        "workspace_title": ws_title if ws_title is not None else ws_slug,
        "surface_ref": surface_ref,
        "title": title,
    }
    idx_path.write_text(json.dumps(idx), encoding="utf-8")
    return p


def test_digest_advances_cursor_and_skips_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    _write_journal(tmp_path, DATE, "meta-eval__builder__surface:2.log",
                   "# 2026-06-03T10:00:00\n● did a thing\n● did another\n")
    assert w.main(["digest", "--workspace", "all", "--date", DATE]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert len(out["surfaces"]) == 1
    surf = out["surfaces"][0]
    assert surf["surface_ref"] == "surface:2"
    assert surf["workspace_title"] == "meta-eval"
    assert surf["title"] == "builder"
    assert surf["from_cursor"] == 0
    assert surf["to_cursor"] > 0
    assert surf["unread_line_count"] == 3
    assert Path(surf["digest_file"]).read_text().count("did a thing") == 1
    # second pass immediately: cursor advanced → nothing unread
    w.main(["digest", "--workspace", "all", "--date", DATE])
    assert json.loads(capsys.readouterr().out)["surfaces"] == []


def test_digest_only_new_lines_after_append(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    jpath = _write_journal(tmp_path, DATE, "meta-eval__builder__surface:2.log",
                           "● line one\n")
    w.main(["digest", "--workspace", "all", "--date", DATE])
    first = json.loads(capsys.readouterr().out)["surfaces"][0]
    with jpath.open("a", encoding="utf-8") as fh:
        fh.write("● line two\n")
    w.main(["digest", "--workspace", "all", "--date", DATE])
    second = json.loads(capsys.readouterr().out)["surfaces"][0]
    assert second["from_cursor"] == first["to_cursor"]
    assert second["unread_line_count"] == 1
    digest_body = Path(second["digest_file"]).read_text()
    assert "line two" in digest_body
    assert "line one" not in digest_body


def test_digest_scope_matches_filter_scope_by_title_and_ref(tmp_path, monkeypatch, capsys):
    # digest must select the SAME workspace filter_scope/watch would, by raw
    # title OR ref — not by slug. Mirrors filter_scope() semantics exactly.
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    _write_journal(tmp_path, DATE, "meta-eval__builder__surface:2.log", "● a\n",
                   ws_ref="workspace:2", ws_title="Meta Eval")
    _write_journal(tmp_path, DATE, "other-task__qa-lead__surface:9.log", "● b\n",
                   ws_ref="workspace:5", ws_title="Other Task")
    # by raw title
    w.main(["digest", "--workspace", "Meta Eval", "--date", DATE])
    by_title = json.loads(capsys.readouterr().out)
    assert {s["surface_ref"] for s in by_title["surfaces"]} == {"surface:2"}
    assert by_title["surfaces"][0]["workspace_title"] == "Meta Eval"
    # by ref — reset cursors so the same line is unread again
    (tmp_path / "cursors.json").unlink()
    w.main(["digest", "--workspace", "workspace:5", "--date", DATE])
    by_ref = json.loads(capsys.readouterr().out)
    assert {s["surface_ref"] for s in by_ref["surfaces"]} == {"surface:9"}


def test_digest_default_scope_uses_caller_workspace_env(tmp_path, monkeypatch, capsys):
    # bare digest (no --workspace) honors CMUX_WORKSPACE_ID like filter_scope
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    monkeypatch.setenv("CMUX_WORKSPACE_ID", "workspace:2")
    _write_journal(tmp_path, DATE, "meta-eval__builder__surface:2.log", "● a\n",
                   ws_ref="workspace:2", ws_title="Meta Eval")
    _write_journal(tmp_path, DATE, "other-task__qa-lead__surface:9.log", "● b\n",
                   ws_ref="workspace:5", ws_title="Other Task")
    w.main(["digest", "--date", DATE])
    out = json.loads(capsys.readouterr().out)
    assert {s["surface_ref"] for s in out["surfaces"]} == {"surface:2"}


def test_digest_missing_journal_dir_is_ok(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    assert w.main(["digest", "--workspace", "all", "--date", "2099-01-01"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["surfaces"] == []


def test_digest_filenames_are_collision_proof(tmp_path, monkeypatch, capsys):
    # two surfaces with the SAME ws/title slug must not alias onto one digest file
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    _write_journal(tmp_path, DATE, "meta-eval__builder__surface:2.log", "● from two\n")
    _write_journal(tmp_path, DATE, "meta-eval__builder__surface:7.log", "● from seven\n")
    w.main(["digest", "--workspace", "all", "--date", DATE])
    out = json.loads(capsys.readouterr().out)
    files = {s["digest_file"] for s in out["surfaces"]}
    assert len(files) == 2  # distinct files, no overwrite
    bodies = {Path(f).read_text() for f in files}
    assert any("from two" in b for b in bodies)
    assert any("from seven" in b for b in bodies)


def test_digest_rejects_malformed_date(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    assert w.main(["digest", "--workspace", "all", "--date", "../../etc"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert "invalid" in out["error"]


# --- controller-pane exclusion (Change 1) ---------------------------------

def test_controller_ref_none_when_env_unset(monkeypatch):
    monkeypatch.delenv("CMUX_SURFACE_ID", raising=False)
    assert w._controller_surface_ref() is None


def test_controller_ref_passthrough_when_already_a_ref(monkeypatch):
    monkeypatch.setenv("CMUX_SURFACE_ID", "surface:42")
    # already a surface:N ref — no need to shell out to cmux
    assert w._controller_surface_ref() == "surface:42"


def test_controller_ref_resolves_uuid_via_identify(monkeypatch):
    monkeypatch.setenv("CMUX_SURFACE_ID", "EB02F5AE-CB41-4634-8BF6-9747AF5053FD")
    captured = {}

    def fake_run(*args):
        captured["args"] = args
        return json.dumps({"caller": {"surface_ref": "surface:276"}})

    monkeypatch.setattr(w, "_run_cmux", fake_run)
    assert w._controller_surface_ref() == "surface:276"
    # resolves the UUID through `cmux identify --surface <uuid>`
    assert captured["args"][0] == "identify"
    assert "EB02F5AE-CB41-4634-8BF6-9747AF5053FD" in captured["args"]


def test_controller_ref_degrades_on_cmux_error(monkeypatch):
    monkeypatch.setenv("CMUX_SURFACE_ID", "some-uuid")

    def boom(*args):
        raise w.CmuxError("cmux down")

    monkeypatch.setattr(w, "_run_cmux", boom)
    # resolution failure must not crash the scan — skip nothing
    assert w._controller_surface_ref() is None


def test_scan_omits_controller_surface(monkeypatch):
    monkeypatch.setattr(w, "_controller_surface_ref", lambda: "surface:2")
    monkeypatch.setattr(w, "_load_resolutions", lambda: {})

    def fake_run(*args):
        if args[0] == "tree":
            return TREE
        return "doing work...\nAPI Error: 529 overloaded_error\n"

    monkeypatch.setattr(w, "_run_cmux", fake_run)
    rows = w._scan_surfaces("all")
    refs = {r["surface_ref"] for r in rows}
    assert "surface:2" not in refs   # controller pane excluded entirely
    assert "surface:9" in refs       # the other pane is still scanned


def test_scan_keeps_all_when_no_controller(monkeypatch):
    monkeypatch.setattr(w, "_controller_surface_ref", lambda: None)
    monkeypatch.setattr(w, "_load_resolutions", lambda: {})

    def fake_run(*args):
        if args[0] == "tree":
            return TREE
        return "doing work...\nAPI Error: 529 overloaded_error\n"

    monkeypatch.setattr(w, "_run_cmux", fake_run)
    rows = w._scan_surfaces("all")
    refs = {r["surface_ref"] for r in rows}
    assert {"surface:2", "surface:9"} <= refs  # nothing skipped


# --- learned-resolution store + graduation (Change 2) ---------------------

def test_record_resolution_writes_store(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    rc = w.main(["record-resolution", "--label", "server_5xx", "--action", "resend"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"ok": True, "label": "server_5xx", "action": "resend"}
    assert (tmp_path / "resolutions.json").exists()
    assert w._load_resolutions() == {"server_5xx": "resend"}


def test_record_resolution_upserts(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    w.main(["record-resolution", "--label", "overloaded", "--action", "resend"])
    capsys.readouterr()
    w.main(["record-resolution", "--label", "overloaded", "--action", "wait_retry"])
    capsys.readouterr()
    w.main(["record-resolution", "--label", "rate_limit", "--action", "resend"])
    capsys.readouterr()
    assert w._load_resolutions() == {"overloaded": "wait_retry", "rate_limit": "resend"}


def test_load_resolutions_empty_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    assert w._load_resolutions() == {}


def test_api_error_finding_carries_granular_label():
    f = w.detect_api_error("doing work...\nAPI Error: 529 overloaded_error\n")
    assert f is not None
    assert f.label == "overloaded"
    assert f.known_resolution == ""


def test_apply_known_resolution_graduates_matching_label():
    f = w.Finding(signature="api_error", tier="risky", remediation="retry_or_resend",
                  detail="(server_5xx)", evidence="500", label="server_5xx")
    g = w.apply_known_resolution(f, {"server_5xx": "resend"})
    assert g.tier == "safe"
    assert g.remediation == "resend"
    assert g.known_resolution == "resend"
    assert f.tier == "risky"  # original untouched (pure)


def test_apply_known_resolution_leaves_unknown_label_risky():
    f = w.Finding(signature="api_error", tier="risky", remediation="retry_or_resend",
                  detail="(rate_limit)", evidence="429", label="rate_limit")
    g = w.apply_known_resolution(f, {"server_5xx": "resend"})
    assert g.tier == "risky"
    assert g.remediation == "retry_or_resend"
    assert g.known_resolution == ""


def test_scan_graduates_finding_with_stored_resolution(monkeypatch):
    monkeypatch.setattr(w, "_controller_surface_ref", lambda: None)
    monkeypatch.setattr(w, "_load_resolutions", lambda: {"overloaded": "resend"})

    def fake_run(*args):
        if args[0] == "tree":
            return TREE
        return "doing work...\nAPI Error: 529 overloaded_error\n"

    monkeypatch.setattr(w, "_run_cmux", fake_run)
    rows = w._scan_surfaces("all")
    api_rows = [r for r in rows if r["signature"] == "api_error"]
    assert api_rows
    for r in api_rows:
        assert r["tier"] == "safe"
        assert r["remediation"] == "resend"
        assert r["known_resolution"] == "resend"


# --- resend subcommand (Change 3) -----------------------------------------

def test_resend_reports_resumed_on_active_marker(monkeypatch, capsys):
    seq = iter([
        "● idle\n  > last input echoed\n",                  # before
        "● idle\n  Working… (esc to interrupt)\n",          # after — agent resumed
    ])
    sent = []

    def fake_run(*args):
        if args[0] == "read-screen":
            return next(seq)
        if args[0] == "send-key":
            sent.append(args[-1])
        return ""

    monkeypatch.setattr(w, "_run_cmux", fake_run)
    monkeypatch.setattr(w.time, "sleep", lambda *_: None)
    rc = w.main(["resend", "--surface", "surface:9", "--workspace", "workspace:5"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["action"] == "resend"
    assert out["resumed"] is True
    assert out["surface_ref"] == "surface:9"
    assert sent == ["up", "enter"]  # recall last input, then submit


def test_resend_resumed_false_when_unchanged(monkeypatch, capsys):
    same = "● idle\n  > nothing happening\n"
    seq = iter([same, same])  # screen unchanged, no active marker

    def fake_run(*args):
        if args[0] == "read-screen":
            return next(seq)
        return ""

    monkeypatch.setattr(w, "_run_cmux", fake_run)
    monkeypatch.setattr(w.time, "sleep", lambda *_: None)
    rc = w.main(["resend", "--surface", "surface:9", "--workspace", "workspace:5"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["resumed"] is False


def test_resend_resumed_when_composer_changed(monkeypatch, capsys):
    seq = iter([
        "● idle\n  > old composer\n",   # before
        "● idle\n  > new state\n",      # after — changed, no spinner but moved on
    ])

    def fake_run(*args):
        if args[0] == "read-screen":
            return next(seq)
        return ""

    monkeypatch.setattr(w, "_run_cmux", fake_run)
    monkeypatch.setattr(w.time, "sleep", lambda *_: None)
    w.main(["resend", "--surface", "surface:9", "--workspace", "workspace:5"])
    out = json.loads(capsys.readouterr().out)
    assert out["resumed"] is True


def test_resend_reports_cmux_error(monkeypatch, capsys):
    def boom(*args):
        raise w.CmuxError("surface gone")

    monkeypatch.setattr(w, "_run_cmux", boom)
    rc = w.main(["resend", "--surface", "surface:9", "--workspace", "workspace:5"])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
