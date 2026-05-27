import json
from pathlib import Path

from lib.score import score_assertion


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


def test_count_zero_fails_when_log_file_missing(tmp_path: Path):
    # No log file written for the worker — count: 0 should fail because the
    # worker may have never spawned (we can't distinguish "zero events" from
    # "didn't run at all").
    a = {"worker": "never_spawned", "event": "send_result", "count": 0}
    res = score_assertion(a, step_id=1, log_dir=tmp_path)
    assert not res.passed
    assert "does not exist" in res.reason


def test_intended_peer_not_fails_on_any_send_to_excluded_peer(tmp_path: Path):
    # Reviewer issue 4: previously this would have passed because the
    # filter dropped the bad event before the count check.
    log = tmp_path / "worker_alpha.jsonl"
    _seed_log(log, [
        {"event": "send_result", "step_id": 7,
         "raw_stdout": {"ok": True}, "intended_peer": "bravo_renamed"},
        {"event": "send_result", "step_id": 7,
         "raw_stdout": {"ok": True}, "intended_peer": "worker_charlie"},
    ])
    a = {"worker": "worker_alpha", "kind": "ok",
         "intended_peer_not": "worker_charlie"}
    res = score_assertion(a, step_id=7, log_dir=tmp_path)
    assert not res.passed
    assert "worker_charlie" in res.reason


def test_intended_peer_not_passes_when_only_allowed_peers(tmp_path: Path):
    log = tmp_path / "worker_alpha.jsonl"
    _seed_log(log, [
        {"event": "send_result", "step_id": 7,
         "raw_stdout": {"ok": True}, "intended_peer": "bravo_renamed"},
    ])
    a = {"worker": "worker_alpha", "kind": "ok",
         "intended_peer_not": "worker_charlie"}
    res = score_assertion(a, step_id=7, log_dir=tmp_path)
    assert res.passed, res.reason


def test_surface_differs_from_step_id_passes_when_new_surface(tmp_path: Path):
    log = tmp_path / "worker_alpha.jsonl"
    _seed_log(log, [
        # step 8: peer_unknown with dead-surface candidate
        {"event": "send_result", "step_id": 8,
         "intended_peer": "bravo_renamed",
         "raw_stdout": {"ok": False, "code": "peer_unknown",
                        "candidates": [{"ref": "surface:OLD"}]},
         "candidates": [{"ref": "surface:OLD"}]},
        # step 9: success with a brand-new surface
        {"event": "send_result", "step_id": 9,
         "intended_peer": "bravo_renamed",
         "raw_stdout": {"ok": True, "surface": "surface:NEW",
                        "kind": "bootstrap", "peer_status": "live",
                        "resolved_by": "title_in_workspace"},
         "observed_kind": "bootstrap", "peer_status": "live",
         "resolved_by": "title_in_workspace"},
    ])
    a = {"worker": "worker_alpha", "kind": "ok", "observed_kind": "bootstrap",
         "peer_status": "live", "resolved_by": "title_in_workspace",
         "surface_differs_from_step_id": 8}
    res = score_assertion(a, step_id=9, log_dir=tmp_path)
    assert res.passed, res.reason


def test_surface_differs_from_step_id_fails_when_same_surface(tmp_path: Path):
    log = tmp_path / "worker_alpha.jsonl"
    _seed_log(log, [
        {"event": "send_result", "step_id": 8,
         "intended_peer": "bravo_renamed",
         "raw_stdout": {"ok": False, "code": "peer_unknown",
                        "candidates": [{"ref": "surface:SAME"}]}},
        {"event": "send_result", "step_id": 9,
         "intended_peer": "bravo_renamed",
         "raw_stdout": {"ok": True, "surface": "surface:SAME",
                        "kind": "bootstrap", "peer_status": "live",
                        "resolved_by": "title_in_workspace"},
         "observed_kind": "bootstrap", "peer_status": "live",
         "resolved_by": "title_in_workspace"},
    ])
    a = {"worker": "worker_alpha", "kind": "ok", "observed_kind": "bootstrap",
         "peer_status": "live", "resolved_by": "title_in_workspace",
         "surface_differs_from_step_id": 8}
    res = score_assertion(a, step_id=9, log_dir=tmp_path)
    assert not res.passed
    assert "surface:SAME" in res.reason


def test_candidates_min(tmp_path: Path):
    log = tmp_path / "sim_driver.jsonl"
    _seed_log(log, [{"event": "send_result", "step_id": 11,
                     "intended_peer": "bravo_renamed",
                     "raw_stdout": {"ok": False, "code": "peer_ambiguous",
                                    "candidates": [{"ref": "s:1"}, {"ref": "s:2"}]},
                     "observed_code": "peer_ambiguous",
                     "candidates": [{"ref": "s:1"}, {"ref": "s:2"}]}])
    ok = {"worker": "sim_driver", "kind": "error",
          "observed_code": "peer_ambiguous", "candidates_min": 2}
    res = score_assertion(ok, step_id=11, log_dir=tmp_path)
    assert res.passed, res.reason
    bad = {"worker": "sim_driver", "kind": "error",
           "observed_code": "peer_ambiguous", "candidates_min": 5}
    res2 = score_assertion(bad, step_id=11, log_dir=tmp_path)
    assert not res2.passed
    assert "candidates" in res2.reason


def test_any_of_passes_if_any_branch_passes(tmp_path: Path):
    log = tmp_path / "sim_driver.jsonl"
    _seed_log(log, [{"event": "send_result", "step_id": 11,
                     "intended_peer": "bravo_renamed",
                     "raw_stdout": {"ok": False, "code": "peer_ambiguous",
                                    "candidates": [{"ref": "s:1"}, {"ref": "s:2"}]},
                     "observed_code": "peer_ambiguous",
                     "candidates": [{"ref": "s:1"}, {"ref": "s:2"}]}])
    a = {"worker": "sim_driver", "any_of": [
        {"kind": "error", "observed_code": "peer_ambiguous", "candidates_min": 2},
        {"kind": "informational", "reason": "cmux rejected rename"},
    ]}
    res = score_assertion(a, step_id=11, log_dir=tmp_path)
    assert res.passed, res.reason


def test_any_of_fails_when_all_branches_fail(tmp_path: Path):
    log = tmp_path / "sim_driver.jsonl"
    _seed_log(log, [{"event": "send_result", "step_id": 11,
                     "intended_peer": "x",
                     "raw_stdout": {"ok": True, "kind": "message"},
                     "observed_kind": "message"}])
    a = {"worker": "sim_driver", "any_of": [
        {"kind": "error", "observed_code": "peer_ambiguous"},
        {"kind": "informational", "reason": "x"},
    ]}
    res = score_assertion(a, step_id=11, log_dir=tmp_path)
    assert not res.passed
    assert "any_of" in res.reason


def test_informational_branch_reads_sidecar(tmp_path: Path):
    # the informational sidecar file is what the driver writes when a
    # non-p2p action (e.g. cmux refused a rename) needs to be asserted.
    sidecar = tmp_path / "sim_driver.informational.jsonl"
    sidecar.write_text(json.dumps({"step_id": 11,
                                   "reason": "cmux rejected rename"}) + "\n")
    a = {"worker": "sim_driver", "kind": "informational",
         "reason": "cmux rejected rename"}
    res = score_assertion(a, step_id=11, log_dir=tmp_path)
    assert res.passed, res.reason


def test_distinct_attempt_ids_handles_p2p_reply_trailer(tmp_path: Path):
    # regression for reviewer issue 1: counter bodies arrive with the p2p
    # "\n\nTo reply: Load p2p" trailer. The check must extract attempt_id
    # despite the trailer.
    log = tmp_path / "bravo_renamed.jsonl"
    _seed_log(log, [
        {"event": "inbound_frame", "step_id": 4, "from_title": "worker_alpha",
         "one_way": True, "raw_frame": "",
         "body": 'COUNTER:{"attempt_id":"a1","value":1}\n\nTo reply: Load p2p',
         "parse_status": "ok"},
        {"event": "inbound_frame", "step_id": 4, "from_title": "worker_alpha",
         "one_way": True, "raw_frame": "",
         "body": 'COUNTER:{"attempt_id":"a2","value":2}\n\nTo reply: Load p2p',
         "parse_status": "ok"},
    ])
    a = {"worker": "bravo_renamed", "event": "inbound_frame", "count": 2,
         "distinct_attempt_ids": True, "all_one_way": True}
    res = score_assertion(a, step_id=4, log_dir=tmp_path)
    assert res.passed, res.reason


def test_distinct_attempt_ids_fails_on_dupes(tmp_path: Path):
    log = tmp_path / "bravo_renamed.jsonl"
    _seed_log(log, [
        {"event": "inbound_frame", "step_id": 4, "from_title": "x",
         "one_way": True, "raw_frame": "",
         "body": 'COUNTER:{"attempt_id":"a1","value":1}', "parse_status": "ok"},
        {"event": "inbound_frame", "step_id": 4, "from_title": "x",
         "one_way": True, "raw_frame": "",
         "body": 'COUNTER:{"attempt_id":"a1","value":1}', "parse_status": "ok"},
    ])
    a = {"worker": "bravo_renamed", "event": "inbound_frame", "count": 2,
         "distinct_attempt_ids": True}
    res = score_assertion(a, step_id=4, log_dir=tmp_path)
    assert not res.passed
    assert "duplicate" in res.reason


def test_read_events_skips_malformed_json_line(tmp_path: Path):
    log = tmp_path / "worker_alpha.jsonl"
    log.write_text(
        json.dumps({"event": "send_result", "step_id": 1,
                    "raw_stdout": {"ok": True}, "intended_peer": "x"}) + "\n"
        + "not valid json\n"
        + json.dumps({"event": "send_result", "step_id": 1,
                      "raw_stdout": {"ok": True}, "intended_peer": "y"}) + "\n"
    )
    a = {"worker": "worker_alpha", "kind": "ok", "count": 2}
    res = score_assertion(a, step_id=1, log_dir=tmp_path)
    assert res.passed, res.reason
