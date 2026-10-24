import json
from pathlib import Path

from lib.log import write_send_result, write_inbound_frame


def test_write_send_result_appends_event(tmp_path: Path):
    log_path = tmp_path / "worker_alpha.jsonl"
    raw = {"ok": True, "kind": "message", "peer_status": "live",
           "resolved_by": "title_in_workspace", "title": "worker_bravo",
           "surface": "surface:3"}
    write_send_result(
        log_path,
        run_id="r1", step_id=1, attempt_id="a1",
        intended_peer="worker_bravo",
        raw_stdout=raw,
    )
    lines = log_path.read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["event"] == "send_result"
    assert rec["run_id"] == "r1"
    assert rec["step_id"] == 1
    assert rec["attempt_id"] == "a1"
    assert rec["intended_peer"] == "worker_bravo"
    assert rec["raw_stdout"] == raw
    assert rec["observed_kind"] == "message"
    assert rec["peer_status"] == "live"
    assert rec["resolved_by"] == "title_in_workspace"
    assert rec["observed_code"] is None
    assert "ts" in rec


def test_write_send_result_extracts_error_fields(tmp_path: Path):
    log_path = tmp_path / "worker_alpha.jsonl"
    raw = {
        "ok": False, "code": "peer_renamed",
        "action_required": "retry with current title",
        "retryable": True, "handoff_skill": None,
        "candidates": [{"current_title": "bravo_renamed",
                        "former_title": "worker_bravo",
                        "ref": "surface:3"}],
    }
    write_send_result(log_path, run_id="r1", step_id=2, attempt_id="a2",
                      intended_peer="worker_bravo", raw_stdout=raw)
    rec = json.loads(log_path.read_text().splitlines()[0])
    assert rec["observed_code"] == "peer_renamed"
    assert rec["action_required"] == "retry with current title"
    assert rec["retryable"] is True
    assert rec["candidates"][0]["current_title"] == "bravo_renamed"


def test_write_inbound_frame(tmp_path: Path):
    log_path = tmp_path / "worker_bravo.jsonl"
    write_inbound_frame(
        log_path,
        run_id="r1", step_id=4,
        raw_frame="[from: worker_alpha | one-way] COUNTER:{\"value\":3}",
        from_title="worker_alpha",
        body='COUNTER:{"value":3}',
        one_way=True,
        parse_status="ok",
    )
    rec = json.loads(log_path.read_text().splitlines()[0])
    assert rec["event"] == "inbound_frame"
    assert rec["from_title"] == "worker_alpha"
    assert rec["one_way"] is True
    assert rec["parse_status"] == "ok"
