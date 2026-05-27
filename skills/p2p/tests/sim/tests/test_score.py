import json
from pathlib import Path

from lib.score import score_assertion, AssertionResult


def _seed_log(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_assert_ok_kind_message_passes(tmp_path: Path):
    log = tmp_path / "worker_alpha.jsonl"
    _seed_log(log, [{"event": "send_result", "raw_stdout": {"ok": True},
                     "observed_code": None, "observed_kind": "message",
                     "peer_status": "live", "resolved_by": "title_in_workspace",
                     "step_id": 1, "intended_peer": "worker_bravo"}])
    a = {"worker": "worker_alpha", "kind": "ok", "observed_kind": "message",
         "peer_status": "live"}
    res = score_assertion(a, step_id=1, log_dir=tmp_path)
    assert res.passed, res.reason


def test_assert_error_code_passes(tmp_path: Path):
    log = tmp_path / "worker_alpha.jsonl"
    _seed_log(log, [{"event": "send_result",
                     "raw_stdout": {"ok": False, "code": "peer_renamed"},
                     "observed_code": "peer_renamed", "step_id": 2,
                     "candidates": [{"current_title": "bravo_renamed",
                                     "former_title": "worker_bravo",
                                     "ref": "surface:3"}]}])
    a = {"worker": "worker_alpha", "kind": "error",
         "observed_code": "peer_renamed",
         "candidate_check": {"current_title": "bravo_renamed",
                             "former_title": "worker_bravo"}}
    res = score_assertion(a, step_id=2, log_dir=tmp_path)
    assert res.passed, res.reason


def test_assert_inbound_frame_count_passes(tmp_path: Path):
    log = tmp_path / "bravo_renamed.jsonl"
    _seed_log(log, [{"event": "inbound_frame", "step_id": 4,
                     "from_title": "worker_alpha", "one_way": True,
                     "raw_frame": "[from: worker_alpha | one-way] x",
                     "body": "x", "parse_status": "ok"}] * 5)
    a = {"worker": "bravo_renamed", "event": "inbound_frame", "count": 5,
         "all_one_way": True}
    res = score_assertion(a, step_id=4, log_dir=tmp_path)
    assert res.passed, res.reason


def test_assert_inbound_count_fails_on_wrong_count(tmp_path: Path):
    log = tmp_path / "bravo_renamed.jsonl"
    _seed_log(log, [{"event": "inbound_frame", "step_id": 4,
                     "from_title": "worker_alpha", "one_way": True,
                     "raw_frame": "", "body": "x", "parse_status": "ok"}] * 4)
    a = {"worker": "bravo_renamed", "event": "inbound_frame", "count": 5}
    res = score_assertion(a, step_id=4, log_dir=tmp_path)
    assert not res.passed
    assert "count" in res.reason


def test_assert_zero_outbound_passes(tmp_path: Path):
    log = tmp_path / "bravo_renamed.jsonl"
    _seed_log(log, [{"event": "inbound_frame", "step_id": 5,
                     "from_title": "worker_alpha", "one_way": False,
                     "raw_frame": "", "body": "x", "parse_status": "ok"}])
    a = {"worker": "bravo_renamed", "event": "send_result", "count": 0}
    res = score_assertion(a, step_id=5, log_dir=tmp_path)
    assert res.passed
