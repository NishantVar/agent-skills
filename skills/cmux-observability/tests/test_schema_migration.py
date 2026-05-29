"""v1.2 — schema_version bump 1 → 2. Legacy v1 snapshots must still load.

Loader entrypoint is `runstate.read(run_id)` which calls `_rehydrate()` on
the persisted dict. The on-disk payload wraps the snapshot in
`{"run_id", "snapshot": <dict>, "screen_hashes", "redactions_by_surface"}`.
"""
import json
from pathlib import Path

import pytest

from cmux_observability import runstate


def _legacy_v1_snapshot_dict() -> dict:
    return {
        "schema_version": 1,
        "captured_at": "2026-05-27T00:00:00",
        "host": "laptop",
        "cmux_version": "1.2.3",
        "workspaces": [],
        "agents": [
            {
                "surface_ref": "surface:1",
                "workspace_ref": "workspace:1",
                "type": "claude_code",
                "type_source": "cmux_tag",
                "type_confidence": 1.0,
                "state": "running",
                "state_source": "cmux_tag",  # legacy values only — no "scrollback"
                "pid": 12345,
                "summary": None,
            }
        ],
        "themes": [],
        "productivity": None,
        "history": {"points": []},
        "failures": [],
    }


def test_legacy_v1_snapshot_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    run_id = "legacyv1test"
    payload = {
        "run_id": run_id,
        "snapshot": _legacy_v1_snapshot_dict(),
        "screen_hashes": {},
        "redactions_by_surface": {},
    }

    state_file = runstate.state_path(run_id)
    state_file.write_text(json.dumps(payload))

    snap, screen_hashes, redactions = runstate.read(run_id)
    # v1 payload loads with its declared schema_version unchanged. (Loader
    # echoes the on-disk value; we accept either 1 or 2 to allow a future
    # auto-migrate without churn.)
    assert snap.schema_version in (1, 2)
    assert len(snap.agents) == 1
    assert snap.agents[0].state_source == "cmux_tag"
    assert snap.agents[0].surface_ref == "surface:1"
    assert screen_hashes == {}
    assert redactions == {}
