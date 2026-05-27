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


def test_surface_differs_fails_when_current_matches_prior_success(tmp_path: Path):
    log = tmp_path / "worker_alpha.jsonl"
    _seed_log(log, [
        # step 7: success at the dead surface
        {"event": "send_result", "step_id": 7,
         "intended_peer": "bravo_renamed",
         "raw_stdout": {"ok": True, "surface": "surface:SAME",
                        "kind": "message", "peer_status": "live",
                        "resolved_by": "title_in_workspace"}},
        # step 9: "resurrection" but somehow reusing the same surface — fail
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


def test_distinct_attempt_ids_fails_on_non_counter_body(tmp_path: Path):
    # Rp2p HIGH-1: previously, non-COUNTER bodies were silently skipped,
    # so 5 inbound frames of garbage passed distinct_attempt_ids vacuously.
    log = tmp_path / "bravo_renamed.jsonl"
    _seed_log(log, [
        {"event": "inbound_frame", "step_id": 4, "from_title": "x",
         "one_way": True, "raw_frame": "", "body": "SIM:HALT {}",
         "parse_status": "ok"},
        {"event": "inbound_frame", "step_id": 4, "from_title": "x",
         "one_way": True, "raw_frame": "", "body": "noise",
         "parse_status": "ok"},
    ])
    a = {"worker": "bravo_renamed", "event": "inbound_frame", "count": 2,
         "distinct_attempt_ids": True}
    res = score_assertion(a, step_id=4, log_dir=tmp_path)
    assert not res.passed
    assert "COUNTER" in res.reason


def test_distinct_attempt_ids_fails_on_missing_attempt_id(tmp_path: Path):
    log = tmp_path / "bravo_renamed.jsonl"
    _seed_log(log, [
        {"event": "inbound_frame", "step_id": 4, "from_title": "x",
         "one_way": True, "raw_frame": "",
         "body": 'COUNTER:{"value":1}', "parse_status": "ok"},
    ])
    a = {"worker": "bravo_renamed", "event": "inbound_frame", "count": 1,
         "distinct_attempt_ids": True}
    res = score_assertion(a, step_id=4, log_dir=tmp_path)
    assert not res.passed
    assert "attempt_id" in res.reason


def test_distinct_attempt_ids_fails_on_bad_parse_status(tmp_path: Path):
    log = tmp_path / "bravo_renamed.jsonl"
    _seed_log(log, [
        {"event": "inbound_frame", "step_id": 4, "from_title": "x",
         "one_way": True, "raw_frame": "",
         "body": 'COUNTER:{"attempt_id":"a1","value":1}',
         "parse_status": "Expecting value: line 1"},
    ])
    a = {"worker": "bravo_renamed", "event": "inbound_frame", "count": 1,
         "distinct_attempt_ids": True}
    res = score_assertion(a, step_id=4, log_dir=tmp_path)
    assert not res.passed
    assert "parse_status" in res.reason


def test_surface_differs_uses_prior_success_not_peer_unknown_event(tmp_path: Path):
    # Rp2p HIGH-2: peer_unknown has no surface/candidates fields, so the
    # only way to know the dead surface is to look at the most recent
    # successful send to that peer at or before the cited step.
    log = tmp_path / "worker_alpha.jsonl"
    _seed_log(log, [
        # step 7: successful send to bravo_renamed at the soon-to-die surface
        {"event": "send_result", "step_id": 7,
         "intended_peer": "bravo_renamed",
         "raw_stdout": {"ok": True, "surface": "surface:OLD",
                        "kind": "message", "peer_status": "live",
                        "resolved_by": "title_in_workspace"}},
        # step 8: peer_unknown — realistic shape, no surface, no candidates
        {"event": "send_result", "step_id": 8,
         "intended_peer": "bravo_renamed",
         "raw_stdout": {"ok": False, "code": "peer_unknown",
                        "action_required": "spawn_peer", "retryable": True,
                        "handoff_skill": "tfork",
                        "payload_file": "/tmp/spawn.txt"},
         "observed_code": "peer_unknown", "action_required": "spawn_peer",
         "retryable": True, "handoff_skill": "tfork",
         "payload_file": "/tmp/spawn.txt"},
        # step 9: success with brand-new surface — must pass
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


def test_surface_differs_fails_defensively_when_no_prior_success(tmp_path: Path):
    log = tmp_path / "worker_alpha.jsonl"
    # only a peer_unknown at step 8 — no prior success anywhere
    _seed_log(log, [
        {"event": "send_result", "step_id": 8,
         "intended_peer": "bravo_renamed",
         "raw_stdout": {"ok": False, "code": "peer_unknown"}},
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
    assert not res.passed
    assert "no successful prior surface" in res.reason


def test_action_required_and_retryable_checks(tmp_path: Path):
    log = tmp_path / "worker_alpha.jsonl"
    _seed_log(log, [{"event": "send_result", "step_id": 2,
                     "intended_peer": "worker_bravo",
                     "raw_stdout": {"ok": False, "code": "peer_renamed",
                                    "action_required": "confirm_rename",
                                    "retryable": True},
                     "observed_code": "peer_renamed",
                     "action_required": "confirm_rename", "retryable": True}])
    ok = {"worker": "worker_alpha", "kind": "error",
          "observed_code": "peer_renamed",
          "action_required": "confirm_rename", "retryable": True}
    assert score_assertion(ok, step_id=2, log_dir=tmp_path).passed
    bad_action = {**ok, "action_required": "something_else"}
    res = score_assertion(bad_action, step_id=2, log_dir=tmp_path)
    assert not res.passed and "action_required" in res.reason
    bad_retry = {**ok, "retryable": False}
    res2 = score_assertion(bad_retry, step_id=2, log_dir=tmp_path)
    assert not res2.passed and "retryable" in res2.reason


def test_hygiene_fails_on_non_canonical_event(tmp_path: Path):
    """Driver/worker tampering signature from QA v2 run 1f007b8c...:
    worker_alpha had 14 events with `event` values like SIM:PRIME,
    COUNTER:recv, etc. — only send_result / inbound_frame are
    canonical. Scorer must refuse to trust the log."""
    log = tmp_path / "worker_alpha.jsonl"
    _seed_log(log, [
        {"event": "send_result", "step_id": 1,
         "raw_stdout": {"ok": True}, "ts": "2026-05-27T11:00:00+00:00"},
        {"event": "SIM:PRIME", "step_id": 1,  # non-canonical
         "ts": "2026-05-27T11:00:01+00:00"},
    ])
    a = {"worker": "worker_alpha", "kind": "ok", "count": ">=1"}
    res = score_assertion(a, step_id=1, log_dir=tmp_path)
    assert not res.passed
    assert "non-canonical" in res.reason
    assert "SIM:PRIME" in res.reason


def test_hygiene_fails_on_float_timestamp(tmp_path: Path):
    """The canonical helpers always emit `ts` as an ISO string. Float
    epoch timestamps mean somebody wrote to the file directly."""
    log = tmp_path / "worker_alpha.jsonl"
    _seed_log(log, [
        {"event": "send_result", "step_id": 1,
         "raw_stdout": {"ok": True}, "ts": 1779865723.609888},  # float
    ])
    a = {"worker": "worker_alpha", "kind": "ok", "count": ">=1"}
    res = score_assertion(a, step_id=1, log_dir=tmp_path)
    assert not res.passed
    assert "non-ISO" in res.reason


def test_hygiene_passes_on_clean_log(tmp_path: Path):
    log = tmp_path / "worker_alpha.jsonl"
    _seed_log(log, [
        {"event": "send_result", "step_id": 1,
         "raw_stdout": {"ok": True}, "ts": "2026-05-27T11:00:00+00:00",
         "intended_peer": "worker_bravo"},
    ])
    a = {"worker": "worker_alpha", "kind": "ok", "count": ">=1"}
    res = score_assertion(a, step_id=1, log_dir=tmp_path)
    assert res.passed, res.reason


def test_observed_kind_filters_before_count(tmp_path: Path):
    """Regression: count must be checked AFTER observed_kind narrows the
    event set, not before. QA caught this on the baseline smoke (run
    fbc3d78b...): step 1 asserted count=3 bootstrap sends, but the
    scorer counted all 14 ok sends because observed_kind was checked
    per-event, after the count assertion."""
    log = tmp_path / "sim_driver.jsonl"
    bootstrap = {"event": "send_result", "step_id": 1,
                 "raw_stdout": {"ok": True}, "observed_kind": "bootstrap",
                 "peer_status": "live", "resolved_by": "title_in_workspace",
                 "intended_peer": "worker_alpha"}
    message = {"event": "send_result", "step_id": 1,
               "raw_stdout": {"ok": True}, "observed_kind": "message",
               "peer_status": "live", "resolved_by": "title_in_workspace",
               "intended_peer": "worker_alpha"}
    _seed_log(log, [bootstrap] * 3 + [message] * 11)
    a = {"worker": "sim_driver", "kind": "ok",
         "observed_kind": "bootstrap", "peer_status": "live",
         "resolved_by": "title_in_workspace", "count": ">=3"}
    res = score_assertion(a, step_id=1, log_dir=tmp_path)
    assert res.passed, res.reason


def test_peer_status_filters_before_count(tmp_path: Path):
    log = tmp_path / "worker_alpha.jsonl"
    live = {"event": "send_result", "step_id": 1,
            "raw_stdout": {"ok": True}, "observed_kind": "message",
            "peer_status": "live", "intended_peer": "worker_bravo"}
    stale = {"event": "send_result", "step_id": 1,
             "raw_stdout": {"ok": True}, "observed_kind": "message",
             "peer_status": "stale", "intended_peer": "worker_bravo"}
    _seed_log(log, [live] * 2 + [stale] * 3)
    a = {"worker": "worker_alpha", "kind": "ok",
         "peer_status": "stale", "count": 3}
    res = score_assertion(a, step_id=1, log_dir=tmp_path)
    assert res.passed, res.reason


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
