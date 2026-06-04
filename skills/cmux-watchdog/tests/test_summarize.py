"""Unit tests for summarize.py — the LLM summarizer + launchd plumbing.

Network is never touched: call_llm takes an injectable transport, and the
end-to-end run_pass / run_catchup tests run the REAL watchdog.py digest (pure
local file I/O) against a temp CMUX_WATCHDOG_HOME while stubbing only the API.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import summarize as s


# --- env file parsing + config merge --------------------------------------

def test_parse_env_file_handles_comments_quotes_export():
    text = (
        "# a comment\n"
        "\n"
        "LLM_API_KEY=sk-abc123\n"
        "export LLM_MODEL='deepseek-v4-pro'\n"
        'OBSIDIAN="/Users/x/obsidian"\n'
        "BARE\n"  # no '=' -> ignored
    )
    out = s._parse_env_file(text)
    assert out["LLM_API_KEY"] == "sk-abc123"
    assert out["LLM_MODEL"] == "deepseek-v4-pro"
    assert out["OBSIDIAN"] == "/Users/x/obsidian"
    assert "BARE" not in out


def test_load_config_defaults_and_deepseek_key_alias():
    cfg = s.load_config(env={"DEEPSEEK_API_KEY": "sk-z", "OBSIDIAN": "/v"},
                        env_files=[Path("/nonexistent")])
    assert cfg["api_key"] == "sk-z"
    assert cfg["api_base"] == s.DEFAULT_API_BASE
    assert cfg["model"] == s.DEFAULT_MODEL
    assert cfg["obsidian"] == "/v"


def test_load_config_env_overrides_file(tmp_path):
    envf = tmp_path / "summarizer.env"
    envf.write_text("LLM_API_KEY=from-file\nLLM_MODEL=file-model\nOBSIDIAN=/file/v\n")
    cfg = s.load_config(env={"LLM_API_KEY": "from-env"}, env_files=[envf])
    assert cfg["api_key"] == "from-env"      # env wins
    assert cfg["model"] == "file-model"      # falls back to file
    assert cfg["obsidian"] == "/file/v"


def test_load_config_missing_key_is_none():
    cfg = s.load_config(env={}, env_files=[Path("/nonexistent")])
    assert cfg["api_key"] is None
    assert cfg["obsidian"] is None


def test_load_config_expands_tilde_in_obsidian(tmp_path):
    envf = tmp_path / "e.env"
    envf.write_text("DEEPSEEK_API_KEY=k\nOBSIDIAN=~/obsidian\n")
    cfg = s.load_config(env={}, env_files=[envf])
    assert cfg["obsidian"] == os.path.expanduser("~/obsidian")
    assert "~" not in cfg["obsidian"]  # literal tilde would create a bogus dir


def test_load_config_reads_second_file_and_first_wins(tmp_path):
    # mirrors summarizer.env (first) + ~/genesis/.env (second): genesis supplies the
    # key when summarizer.env is absent/silent; summarizer.env overrides when both set.
    summarizer = tmp_path / "summarizer.env"   # absent
    genesis = tmp_path / "genesis.env"
    genesis.write_text("DEEPSEEK_API_KEY=from-genesis\nOBSIDIAN=/g/vault\n")
    cfg = s.load_config(env={}, env_files=[summarizer, genesis])
    assert cfg["api_key"] == "from-genesis"    # genesis used when summarizer.env missing
    assert cfg["obsidian"] == "/g/vault"

    summarizer.write_text("DEEPSEEK_API_KEY=from-summarizer\n")
    cfg2 = s.load_config(env={}, env_files=[summarizer, genesis])
    assert cfg2["api_key"] == "from-summarizer"  # earlier file wins
    assert cfg2["obsidian"] == "/g/vault"        # still falls through to genesis


# --- payload / response shape ---------------------------------------------

def test_build_payload_shape():
    p = s.build_payload("some log text", "deepseek-v4-flash",
                        ws_title="meta-eval", title="builder")
    assert p["model"] == "deepseek-v4-flash"
    assert p["stream"] is False
    assert p["messages"][0]["role"] == "system"
    assert "never invent" in p["messages"][0]["content"]
    assert "some log text" in p["messages"][1]["content"]
    assert "builder" in p["messages"][1]["content"]


def test_extract_content():
    resp = {"choices": [{"message": {"content": "  - Done: x  "}}]}
    assert s.extract_content(resp) == "- Done: x"


def test_call_llm_uses_transport_and_builds_url():
    seen = {}

    def transport(url, headers, body):
        seen["url"] = url
        seen["auth"] = headers["Authorization"]
        seen["body"] = json.loads(body)
        return {"choices": [{"message": {"content": "- Done: ok"}}]}

    cfg = {"api_base": "https://api.deepseek.com", "api_key": "sk-1",
           "model": "deepseek-v4-flash"}
    out = s.call_llm(s.build_payload("t", "deepseek-v4-flash",
                                     ws_title="w", title="p"), cfg, transport)
    assert out == "- Done: ok"
    assert seen["url"] == "https://api.deepseek.com/chat/completions"
    assert seen["auth"] == "Bearer sk-1"
    assert seen["body"]["model"] == "deepseek-v4-flash"


# --- worklog formatting ----------------------------------------------------

def test_format_worklog_groups_by_workspace():
    results = [
        {"workspace_title": "meta-eval", "title": "builder",
         "surface_ref": "surface:2", "bullets": "- Done: built X"},
        {"workspace_title": "meta-eval", "title": "qa",
         "surface_ref": "surface:9", "bullets": "- Errors: flaky test"},
        {"workspace_title": "other", "title": "rev",
         "surface_ref": "surface:5", "bullets": "- Notes: idle"},
    ]
    md = s.format_worklog(results, "14:30")
    assert "## 14:30 — meta-eval" in md
    assert "## 14:30 — other" in md
    assert "**builder** (surface:2)" in md
    assert "- Done: built X" in md
    assert md.count("## 14:30 — meta-eval") == 1  # both meta-eval surfaces share one heading


def test_append_worklog_creates_then_appends(tmp_path):
    s.append_worklog("first\n", str(tmp_path), "2026-06-04")
    p = tmp_path / "worklog" / "2026-06-04.md"
    assert p.read_text() == "first\n"
    s.append_worklog("second\n", str(tmp_path), "2026-06-04")
    assert p.read_text() == "first\n\nsecond\n"  # blank-line separator on append


# --- launchd plist rendering ----------------------------------------------

def test_render_plist_contents():
    pl = s.render_plist(label="com.cmux-watchdog.summarizer", python="/usr/bin/python3",
                        script="/x/summarize.py", scope="all", interval=3600,
                        out_log="/l/o", err_log="/l/e", run_at_load=False)
    assert "<string>com.cmux-watchdog.summarizer</string>" in pl
    assert "<integer>3600</integer>" in pl
    assert "<string>/usr/bin/python3</string>" in pl
    assert "<string>run</string>" in pl
    assert "<string>all</string>" in pl
    assert "<false/>" in pl
    assert s.render_plist(label="l", python="p", script="x", scope="all",
                          interval=60, out_log="o", err_log="e",
                          run_at_load=True).count("<true/>") == 1


# --- digest + journal helpers (mirror watchdog's test scaffolding) ---------

def _write_journal(root: Path, date: str, name: str, text: str,
                   *, ws_ref: str = "", ws_title: str | None = None) -> Path:
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
    idx[name] = {"workspace_ref": ws_ref,
                 "workspace_title": ws_title if ws_title is not None else ws_slug,
                 "surface_ref": surface_ref, "title": title}
    idx_path.write_text(json.dumps(idx), encoding="utf-8")
    return p


def _stub_transport(_url, _headers, body):
    payload = json.loads(body)
    pane = payload["messages"][1]["content"].split("\n", 1)[0]
    return {"choices": [{"message": {"content": f"- Done: summary for {pane}"}}]}


# --- run_pass end-to-end (real digest, stubbed API) ------------------------

def test_run_pass_summarizes_and_writes_worklog(tmp_path, monkeypatch):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    vault = tmp_path / "vault"
    _write_journal(tmp_path, "2026-06-04", "meta-eval__builder__surface:2.log",
                   "# 2026-06-04T10:00:00\n● built the thing\n● ran tests\n")
    cfg = {"api_base": "https://api.deepseek.com", "api_key": "sk", "model": "m",
           "obsidian": str(vault)}

    report = s.run_pass("all", "2026-06-04", cfg, transport=_stub_transport)
    assert report["surfaces_summarized"] == 1
    worklog = (vault / "worklog" / "2026-06-04.md").read_text()
    assert "meta-eval" in worklog
    assert "**builder** (surface:2)" in worklog
    assert "Done: summary for" in worklog

    # cursor advanced: a second pass has nothing unread and writes nothing new.
    before = (vault / "worklog" / "2026-06-04.md").read_text()
    report2 = s.run_pass("all", "2026-06-04", cfg, transport=_stub_transport)
    assert report2["surfaces_summarized"] == 0
    assert (vault / "worklog" / "2026-06-04.md").read_text() == before


# --- pending_dates + catch-up cap ------------------------------------------

def test_pending_dates_reports_unread_days(tmp_path, monkeypatch):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    _write_journal(tmp_path, "2026-06-02", "w__a__surface:1.log", "● old\n")
    _write_journal(tmp_path, "2026-06-04", "w__a__surface:1.log", "● new\n")
    assert s.pending_dates("2026-06-04") == ["2026-06-02", "2026-06-04"]


def test_run_catchup_defers_backlog_older_than_one_day(tmp_path, monkeypatch):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    vault = tmp_path / "vault"
    cfg = {"api_base": "b", "api_key": "k", "model": "m", "obsidian": str(vault)}
    # three unsummarized days; today=06-04, cutoff (max_days=1) = 06-03.
    _write_journal(tmp_path, "2026-06-02", "w__a__surface:1.log", "● two\n")
    _write_journal(tmp_path, "2026-06-03", "w__a__surface:1.log", "● three\n")
    _write_journal(tmp_path, "2026-06-04", "w__a__surface:1.log", "● four\n")

    rep = s.run_catchup("all", "2026-06-04", cfg, max_days=1, transport=_stub_transport)
    done = {d["date"] for d in rep["summarized"]}
    assert done == {"2026-06-03", "2026-06-04"}   # today + yesterday only
    assert rep["deferred"] == ["2026-06-02"]      # >1 day old -> deferred
    assert rep["resume_cmd"] and "--catch-up" in rep["resume_cmd"]
    assert (vault / "worklog" / "2026-06-03.md").exists()
    assert (vault / "worklog" / "2026-06-04.md").exists()
    assert not (vault / "worklog" / "2026-06-02.md").exists()


def test_run_catchup_flag_processes_all_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    vault = tmp_path / "vault"
    cfg = {"api_base": "b", "api_key": "k", "model": "m", "obsidian": str(vault)}
    _write_journal(tmp_path, "2026-06-01", "w__a__surface:1.log", "● one\n")
    _write_journal(tmp_path, "2026-06-04", "w__a__surface:1.log", "● four\n")

    rep = s.run_catchup("all", "2026-06-04", cfg, max_days=1, catch_up=True,
                        transport=_stub_transport)
    done = {d["date"] for d in rep["summarized"]}
    assert done == {"2026-06-01", "2026-06-04"}
    assert rep["deferred"] == []
    assert (vault / "worklog" / "2026-06-01.md").exists()


# --- failure / retry semantics (blocking review finding) -------------------

def _raising_transport(_url, _headers, _body):
    raise RuntimeError("boom 500 server error")


def _malformed_transport(_url, _headers, _body):
    return {"unexpected": "shape"}  # extract_content -> KeyError


def test_llm_failure_does_not_lose_content_and_retries_next_run(tmp_path, monkeypatch):
    # The blocking bug: digest advances the cursor before the LLM call, so a
    # failed summary must NOT make the content invisible — it must retry.
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    vault = tmp_path / "vault"
    cfg = {"api_base": "b", "api_key": "k", "model": "m", "obsidian": str(vault)}
    _write_journal(tmp_path, "2026-06-04", "meta-eval__builder__surface:2.log",
                   "# h\n● did important work\n")

    rep = s.run_pass("all", "2026-06-04", cfg, transport=_raising_transport)
    assert rep["surfaces_summarized"] == 0
    assert rep["failed"] and "boom" in rep["failed"][0]["error"]
    assert not (vault / "worklog" / "2026-06-04.md").exists()
    # content is NOT lost — the digest file is recorded un-summarized for retry
    assert s.unsummarized_dates() == ["2026-06-04"]

    # next run with a working transport retries the SAME digest -> lands in worklog
    rep2 = s.run_pass("all", "2026-06-04", cfg, transport=_stub_transport)
    assert rep2["surfaces_summarized"] == 1
    assert "Done" in (vault / "worklog" / "2026-06-04.md").read_text()
    assert s.unsummarized_dates() == []


def test_malformed_llm_response_is_caught_not_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    cfg = {"api_base": "b", "api_key": "k", "model": "m", "obsidian": str(tmp_path / "v")}
    _write_journal(tmp_path, "2026-06-04", "w__a__surface:1.log", "● x\n")
    rep = s.run_pass("all", "2026-06-04", cfg, transport=_malformed_transport)
    assert rep["surfaces_summarized"] == 0 and rep["failed"]
    assert s.unsummarized_dates() == ["2026-06-04"]  # retryable, not hidden


def test_append_failure_keeps_work_retryable(tmp_path, monkeypatch):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    cfg = {"api_base": "b", "api_key": "k", "model": "m", "obsidian": str(tmp_path / "v")}
    _write_journal(tmp_path, "2026-06-04", "w__a__surface:1.log", "● x\n")

    def _boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(s, "append_worklog", _boom)
    rep = s.run_pass("all", "2026-06-04", cfg, transport=_stub_transport)
    assert rep["ok"] is False and "append failed" in rep["error"]
    assert s.unsummarized_dates() == ["2026-06-04"]  # nothing marked -> full retry


def test_run_catchup_revisits_orphan_dates_with_no_new_bytes(tmp_path, monkeypatch):
    # A prior failed day has no NEW journal bytes (cursor already advanced) but
    # must still be retried via the summary-state manifest.
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    vault = tmp_path / "vault"
    cfg = {"api_base": "b", "api_key": "k", "model": "m", "obsidian": str(vault)}
    _write_journal(tmp_path, "2026-06-04", "w__a__surface:1.log", "● x\n")
    s.run_pass("all", "2026-06-04", cfg, transport=_raising_transport)  # fails, cursor advanced
    assert not pending_or_empty(tmp_path)  # cursor advanced: no new journal bytes
    rep = s.run_catchup("all", "2026-06-04", cfg, max_days=1, transport=_stub_transport)
    assert {d["date"] for d in rep["summarized"]} == {"2026-06-04"}
    assert (vault / "worklog" / "2026-06-04.md").exists()


def pending_or_empty(root):
    # helper: True if the journal cursor still shows unread bytes for today
    return bool(s.pending_dates("2026-06-04"))


# --- launchd hardening (review should-fixes) -------------------------------

def test_render_plist_escapes_special_chars():
    import plistlib
    pl = s.render_plist(label="com.x", python="/usr/bin/python3",
                        script="/tmp/a&b/summarize.py", scope="Work & Tools <x>",
                        interval=60, out_log="/l/o", err_log="/l/e", run_at_load=False)
    doc = plistlib.loads(pl.encode())  # must be valid plist despite & and <
    assert doc["ProgramArguments"][1] == "/tmp/a&b/summarize.py"
    assert doc["ProgramArguments"][4] == "Work & Tools <x>"
    assert doc["StartInterval"] == 60 and doc["RunAtLoad"] is False


def test_install_rejects_uuid_scope(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    rc = s.main(["install", "--workspace", "8E6903E5-D90D-4F88-BE5D-1C0A29E70746"])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and "UUID" in out["error"]


def test_summarizer_lock_is_exclusive(tmp_path, monkeypatch):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    with s._summarizer_lock() as got1:
        assert got1 is True
        with s._summarizer_lock() as got2:
            assert got2 is False           # second concurrent run is locked out
    with s._summarizer_lock() as got3:
        assert got3 is True                # released after the first exits


def test_resume_cmd_is_shell_quoted(tmp_path, monkeypatch):
    monkeypatch.setenv("CMUX_WATCHDOG_HOME", str(tmp_path))
    cfg = {"api_base": "b", "api_key": "k", "model": "m", "obsidian": str(tmp_path / "v")}
    _write_journal(tmp_path, "2026-06-01", "w__a__surface:1.log", "● x\n")  # >1 day old
    rep = s.run_catchup("Work Space", "2026-06-04", cfg, max_days=1, transport=_stub_transport)
    assert rep["deferred"] == ["2026-06-01"]
    assert "'Work Space'" in rep["resume_cmd"]  # spacey scope is a single quoted token
