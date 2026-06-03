"""Unit tests for the pure detection / parsing logic in watchdog.py."""

from __future__ import annotations

import os
import sys

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
