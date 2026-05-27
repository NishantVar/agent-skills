import hashlib
from datetime import datetime, timezone

from cmux_observability.model import (
    Agent, Snapshot, Surface, Workspace,
)
from cmux_observability.persist import connect, migrate
from cmux_observability.redact import redact
from cmux_observability.summarize_io import (
    pending_for_agent, record_from_agent,
)


def _snap_with_one_running_agent() -> tuple[Snapshot, str]:
    surface = Surface(
        ref="surface:1", pane_ref="pane:1", workspace_ref="workspace:1",
        kind="terminal", title="claude_code", tty="ttys001",
        cwd="/home/u/repo", is_agent=True,
    )
    ws = Workspace(ref="workspace:1", title="Project A", window_ref="window:1",
                   surfaces=[surface])
    agent = Agent(
        surface_ref="surface:1", workspace_ref="workspace:1",
        type="claude_code", type_source="cmux_tag", type_confidence=1.0,
        state="running", state_source="cmux_tag", pid=42,
    )
    snap = Snapshot(
        schema_version=1,
        captured_at=datetime.now(timezone.utc),
        host="h", cmux_version="x",
        workspaces=[ws], agents=[agent], themes=[],
        productivity=None, history=None, failures=[],
    )
    raw_screen = (
        "[claude_code] working on parser tests\n"
        "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUv0123456789  # leaked token\n"
    )
    return snap, raw_screen


def test_pending_returns_redacted_payload_and_excludes_originals(tmp_path):
    snap, raw_screen = _snap_with_one_running_agent()
    screens = {"surface:1": raw_screen}

    with connect(tmp_path / "obs.sqlite") as conn:
        migrate(conn)
        pending = pending_for_agent(snap, conn, screens, prompt_version=1)
    assert len(pending) == 1
    p = pending[0]
    assert p["surface_ref"] == "surface:1"
    assert "<REDACTED:SK_TOKEN>" in p["scrollback"]
    assert "sk-ant-api03-AbCdEf" not in p["scrollback"]
    assert "screen_hash" in p
    assert "type" in p and p["type"] == "claude_code"
    # Cache key is computed against the REDACTED text, not the raw text.
    expected_hash = hashlib.sha256(
        redact(raw_screen)[0].encode("utf-8"),
    ).hexdigest()
    assert p["screen_hash"] == expected_hash


def test_cache_hit_on_second_call_returns_empty_pending(tmp_path):
    snap, raw_screen = _snap_with_one_running_agent()
    screens = {"surface:1": raw_screen}

    with connect(tmp_path / "obs.sqlite") as conn:
        migrate(conn)
        first = pending_for_agent(snap, conn, screens, prompt_version=1)
        assert len(first) == 1
        record_from_agent(
            {"summaries": [{
                "surface_ref": "surface:1",
                "summary": "writing pytest fixtures for the tree parser",
                "state_hint": "running",
                "needs_input_reason": None,
                "confidence": 0.85,
            }]},
            snap, conn,
            prompt_version=1,
            screen_hashes={"surface:1": first[0]["screen_hash"]},
            redactions_by_surface={"surface:1": ["SK_TOKEN:1"]},
        )

        # 2nd call, identical screen → empty pending; cached summary attached.
        second = pending_for_agent(snap, conn, screens, prompt_version=1)
    assert second == []
    attached = snap.agents[0].summary
    assert attached is not None
    assert attached.cache_hit is True
    assert attached.text.startswith("writing pytest fixtures")


def test_themes_payload_collapses_on_sparse_summaries():
    """Deterministic guardrail: <30% of active agents summarized → omit."""
    from cmux_observability.summarize_io import themes_payload

    # Build a snapshot with 4 running agents, only 1 with a summary (25%).
    surfaces = [
        Surface(ref=f"surface:{i}", pane_ref=f"pane:{i}",
                workspace_ref="workspace:1", kind="terminal",
                title=f"agent_{i}", tty=f"ttys00{i}", cwd=None, is_agent=True)
        for i in range(1, 5)
    ]
    ws = Workspace(ref="workspace:1", title="W", window_ref="window:1",
                   surfaces=surfaces)
    agents = [
        Agent(surface_ref=s.ref, workspace_ref="workspace:1",
              type="claude_code", type_source="cmux_tag", type_confidence=1.0,
              state="running", state_source="cmux_tag", pid=None)
        for s in surfaces
    ]
    snap = Snapshot(
        schema_version=1, captured_at=datetime.now(timezone.utc),
        host="h", cmux_version=None,
        workspaces=[ws], agents=agents, themes=[],
        productivity=None, history=None, failures=[],
    )
    # No summaries attached → coverage 0% → omit
    out = themes_payload(snap, summaries_enabled=True)
    assert out["omit"] is True
    assert out["reason"] == "sparse-summaries"
    assert out["payload"] is None


def test_themes_payload_collapses_when_summaries_disabled():
    from cmux_observability.summarize_io import themes_payload
    snap, _ = _snap_with_one_running_agent()
    out = themes_payload(snap, summaries_enabled=False)
    assert out == {"payload": None, "omit": True,
                   "reason": "summaries-disabled"}


def test_record_themes_drops_all_low_confidence():
    """All themes <0.5 confidence → snap.themes stays empty."""
    from cmux_observability.summarize_io import record_themes_from_agent
    snap, _ = _snap_with_one_running_agent()
    payload = {"themes": [
        {"label": "weak", "member_refs": ["surface:1"], "why": "?",
         "confidence": 0.2},
        {"label": "also weak", "member_refs": ["surface:1"], "why": "?",
         "confidence": 0.4},
    ]}
    record_themes_from_agent(payload, snap)
    assert snap.themes == []


def test_prompt_version_bump_invalidates_cache(tmp_path):
    snap, raw_screen = _snap_with_one_running_agent()
    screens = {"surface:1": raw_screen}

    with connect(tmp_path / "obs.sqlite") as conn:
        migrate(conn)
        first = pending_for_agent(snap, conn, screens, prompt_version=1)
        record_from_agent(
            {"summaries": [{
                "surface_ref": "surface:1",
                "summary": "writing tests",
                "state_hint": "running",
                "needs_input_reason": None,
                "confidence": 0.9,
            }]},
            snap, conn, prompt_version=1,
            screen_hashes={"surface:1": first[0]["screen_hash"]},
            redactions_by_surface={"surface:1": ["SK_TOKEN:1"]},
        )
        bumped = pending_for_agent(snap, conn, screens, prompt_version=2)
    assert len(bumped) == 1


def test_malformed_and_unknown_summary_entries_produce_non_fatal_failures(tmp_path):
    snap, raw_screen = _snap_with_one_running_agent()
    screens = {"surface:1": raw_screen}

    with connect(tmp_path / "obs.sqlite") as conn:
        migrate(conn)
        first = pending_for_agent(snap, conn, screens, prompt_version=1)
        assert len(first) == 1
        screen_hashes = {"surface:1": first[0]["screen_hash"]}

        # Malformed entry placed LAST so the valid entry's summary attaches
        # cleanly before the malformed entry tries to overwrite.
        payload = {"summaries": [
            {
                "surface_ref": "surface:does_not_exist",
                "summary": "ignored",
                "state_hint": "running",
                "needs_input_reason": None,
                "confidence": 0.9,
            },
            {
                "surface_ref": "surface:1",
                "summary": "<valid text>",
                "state_hint": "running",
                "needs_input_reason": None,
                "confidence": 0.9,
            },
            {
                "surface_ref": "surface:1",
                # missing "summary" key
                "state_hint": "running",
                "needs_input_reason": None,
                "confidence": 0.9,
            },
        ]}
        failures = record_from_agent(
            payload, snap, conn,
            prompt_version=1,
            screen_hashes=screen_hashes,
            redactions_by_surface={"surface:1": ["SK_TOKEN:1"]},
        )

    assert len(failures) == 2
    assert all(f.component == "summarize_io" for f in failures)
    messages = [f.message for f in failures]
    assert any("unknown surface_ref" in m for m in messages)
    assert any("malformed summary entry" in m for m in messages)
    assert snap.agents[0].summary is not None
    assert snap.agents[0].summary.text == "<valid text>"
