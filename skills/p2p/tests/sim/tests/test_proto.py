import pytest

from lib.proto import (
    MessageClass,
    parse_body,
    encode_counter,
    encode_sim,
    encode_death_notice,
)


def test_parse_counter():
    body = 'COUNTER:{"run_id":"r1","step_id":3,"attempt_id":"a1","sender":"worker_alpha","value":7}'
    parsed = parse_body(body)
    assert parsed.kind == MessageClass.COUNTER
    assert parsed.payload["value"] == 7
    assert parsed.payload["sender"] == "worker_alpha"


def test_parse_sim_verb():
    body = 'SIM:PRIME {"step_id":4,"role":"sender"}'
    parsed = parse_body(body)
    assert parsed.kind == MessageClass.SIM
    assert parsed.verb == "PRIME"
    assert parsed.payload == {"step_id": 4, "role": "sender"}


def test_parse_death_notice():
    body = 'DEATH_NOTICE:{"from":"worker_charlie"}'
    parsed = parse_body(body)
    assert parsed.kind == MessageClass.DEATH_NOTICE
    assert parsed.payload == {"from": "worker_charlie"}


def test_parse_unknown_returns_unknown_class():
    parsed = parse_body("hello world")
    assert parsed.kind == MessageClass.UNKNOWN
    assert parsed.raw == "hello world"


def test_parse_malformed_counter_marks_parse_error():
    parsed = parse_body("COUNTER:{not json}")
    assert parsed.kind == MessageClass.COUNTER
    assert parsed.parse_error is not None


def test_encode_counter_roundtrip():
    body = encode_counter(run_id="r1", step_id=1, attempt_id="a1",
                          sender="alpha", value=5)
    parsed = parse_body(body)
    assert parsed.kind == MessageClass.COUNTER
    assert parsed.payload["value"] == 5


def test_encode_sim_roundtrip():
    body = encode_sim("PRIME", {"step_id": 2, "role": "receiver_log_only",
                                "forward": False})
    parsed = parse_body(body)
    assert parsed.kind == MessageClass.SIM
    assert parsed.verb == "PRIME"
    assert parsed.payload["forward"] is False


def test_encode_death_notice_roundtrip():
    body = encode_death_notice(from_title="worker_charlie")
    parsed = parse_body(body)
    assert parsed.kind == MessageClass.DEATH_NOTICE
    assert parsed.payload["from"] == "worker_charlie"


def test_strips_p2p_reply_trailer_before_json_parse():
    # p2plib appends `\n\nTo reply: Load p2p` to every non-one-way frame.
    # The parser must strip it before json.loads to avoid Extra-data errors.
    body = ('COUNTER:{"run_id":"r1","step_id":3,"attempt_id":"a1",'
            '"sender":"worker_alpha","value":7}\n\nTo reply: Load p2p')
    parsed = parse_body(body)
    assert parsed.kind == MessageClass.COUNTER
    assert parsed.parse_error is None
    assert parsed.payload["value"] == 7
    assert parsed.payload["attempt_id"] == "a1"


def test_strips_p2p_reply_trailer_for_sim_verb():
    body = 'SIM:PRIME {"step_id":4,"role":"sender"}\n\nTo reply: Load p2p'
    parsed = parse_body(body)
    assert parsed.kind == MessageClass.SIM
    assert parsed.parse_error is None
    assert parsed.verb == "PRIME"
    assert parsed.payload["step_id"] == 4


@pytest.mark.parametrize("verb", [
    "PRIME", "RECOVER", "REPORT", "HALT",
    "ANNOUNCE_DEATH", "SET_NEXT_PEER",
    "MARK_INELIGIBLE", "UPDATE_RING",
])
def test_all_documented_sim_verbs_parse(verb):
    body = encode_sim(verb, {})
    parsed = parse_body(body)
    assert parsed.kind == MessageClass.SIM
    assert parsed.verb == verb
