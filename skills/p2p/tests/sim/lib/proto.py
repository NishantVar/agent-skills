"""Parse and serialize p2p-sim message bodies.

Three namespaces, strictly prefixed so they cannot be confused:
  COUNTER:<json>              — token-ring counter traffic (worker<->worker)
  SIM:<VERB> <json>           — control traffic (driver<->worker)
  DEATH_NOTICE:<json>         — graceful-death notice (worker->worker, one-way)
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from typing import Any

SIM_VERBS = frozenset({
    "PRIME", "RECOVER", "REPORT", "HALT",
    "ANNOUNCE_DEATH", "SET_NEXT_PEER",
    "MARK_INELIGIBLE", "UPDATE_RING",
})


class MessageClass(enum.Enum):
    COUNTER = "counter"
    SIM = "sim"
    DEATH_NOTICE = "death_notice"
    UNKNOWN = "unknown"


@dataclass
class ParsedMessage:
    kind: MessageClass
    raw: str
    payload: dict[str, Any] = field(default_factory=dict)
    verb: str | None = None
    parse_error: str | None = None


_REPLY_TRAILER = "\n\nTo reply: "


def _strip_p2p_trailer(body: str) -> str:
    """p2plib appends `\\n\\nTo reply: Load p2p` to every non-one-way frame
    (see p2plib/send.py::_frame). Strip it before namespace-payload parsing
    so JSON bodies don't get extra trailing text."""
    idx = body.find(_REPLY_TRAILER)
    return body[:idx] if idx >= 0 else body


def parse_body(body: str) -> ParsedMessage:
    body = _strip_p2p_trailer(body).strip()
    if body.startswith("COUNTER:"):
        return _parse_counter(body)
    if body.startswith("SIM:"):
        return _parse_sim(body)
    if body.startswith("DEATH_NOTICE:"):
        return _parse_death_notice(body)
    return ParsedMessage(kind=MessageClass.UNKNOWN, raw=body)


def _parse_counter(body: str) -> ParsedMessage:
    json_part = body[len("COUNTER:"):]
    try:
        payload = json.loads(json_part)
    except json.JSONDecodeError as e:
        return ParsedMessage(kind=MessageClass.COUNTER, raw=body, parse_error=str(e))
    return ParsedMessage(kind=MessageClass.COUNTER, raw=body, payload=payload)


def _parse_sim(body: str) -> ParsedMessage:
    rest = body[len("SIM:"):]
    verb, _, json_part = rest.partition(" ")
    if verb not in SIM_VERBS:
        return ParsedMessage(kind=MessageClass.SIM, raw=body, verb=verb,
                             parse_error=f"unknown verb: {verb}")
    payload: dict[str, Any] = {}
    json_part = json_part.strip()
    if json_part:
        try:
            payload = json.loads(json_part)
        except json.JSONDecodeError as e:
            return ParsedMessage(kind=MessageClass.SIM, raw=body, verb=verb,
                                 parse_error=str(e))
    return ParsedMessage(kind=MessageClass.SIM, raw=body, verb=verb, payload=payload)


def _parse_death_notice(body: str) -> ParsedMessage:
    json_part = body[len("DEATH_NOTICE:"):]
    try:
        payload = json.loads(json_part)
    except json.JSONDecodeError as e:
        return ParsedMessage(kind=MessageClass.DEATH_NOTICE, raw=body, parse_error=str(e))
    return ParsedMessage(kind=MessageClass.DEATH_NOTICE, raw=body, payload=payload)


def encode_counter(*, run_id: str, step_id: int, attempt_id: str,
                   sender: str, value: int) -> str:
    payload = {
        "run_id": run_id, "step_id": step_id, "attempt_id": attempt_id,
        "sender": sender, "value": value,
    }
    return "COUNTER:" + json.dumps(payload, separators=(",", ":"))


def encode_sim(verb: str, payload: dict[str, Any]) -> str:
    if verb not in SIM_VERBS:
        raise ValueError(f"unknown SIM verb: {verb}")
    if not payload:
        return f"SIM:{verb}"
    return f"SIM:{verb} " + json.dumps(payload, separators=(",", ":"))


def encode_death_notice(*, from_title: str) -> str:
    return "DEATH_NOTICE:" + json.dumps({"from": from_title}, separators=(",", ":"))
