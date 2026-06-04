"""Watchdog side of the shared golden capture-envelope contract.

The committed golden must equal what the capture layer deterministically
produces (regen guard: run `python3 tests/gen_golden.py` to refresh), and it
must validate. Observability consumes the SAME file on its side.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import capture as cap  # noqa: E402
from gen_golden import build  # noqa: E402


GOLDEN = Path(__file__).parent / "fixtures" / "golden_snapshot.json"


def test_capture_layer_matches_committed_golden():
    produced = build()
    committed = json.loads(GOLDEN.read_text())
    assert produced == committed, (
        "capture layer drifted from the committed golden; "
        "run `python3 tests/gen_golden.py` if this change is intended"
    )


def test_golden_validates():
    cap.validate_envelope(json.loads(GOLDEN.read_text()))


def test_golden_with_bumped_major_is_rejected():
    env = json.loads(GOLDEN.read_text())
    env["capture_schema_version"] = cap.CAPTURE_SCHEMA_VERSION + 1
    try:
        cap.validate_envelope(env)
    except ValueError:
        return
    raise AssertionError("expected ValueError on bumped major")


def test_golden_carries_dashboard_rebuild_data():
    env = json.loads(GOLDEN.read_text())
    # Browser/non-agent surface preserved for the dashboard.
    assert any(s["kind"] == "browser"
               for w in env["workspaces"] for s in w["surfaces"])
    # Redaction metadata present on captures.
    assert all({"redacted_scrollback", "screen_hash", "redactions_applied"}
               <= set(c) for c in env["captures"])
    # No raw secret leaked.
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWX" not in json.dumps(env)
