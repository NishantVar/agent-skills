"""Score per-step assertions against worker JSONL logs.

An assertion is a dict (loaded from catalog.yaml). Supported keys:
  worker            : str    — which JSONL to read (sim_driver.jsonl, etc.)
  event             : str    — "send_result" (default) or "inbound_frame"
  kind              : "ok" | "error"  (for send_result events)
  observed_code     : str    — required when kind=error
  observed_kind     : str    — message | bootstrap (for ok)
  peer_status       : str    — live | stale (for ok)
  resolved_by       : str    — title_in_workspace | explicit_surface | ...
  one_way           : bool
  intended_peer     : str
  intended_peer_not : str    — none of the events targets this peer
  count             : int | ">=N"
  body_prefix       : str    — for inbound_frame body filter
  distinct_attempt_ids : bool
  all_one_way       : bool
  candidate_check   : dict   — subset-match against candidates[0]
  payload_file_nonempty : bool
  handoff_skill     : str
  surface_differs_from_step_id : int
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AssertionResult:
    passed: bool
    reason: str
    observed: list[dict[str, Any]]


def _read_events(log_path: Path, *, step_id: int, event: str) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    out = []
    for line in log_path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("event") != event:
            continue
        if rec.get("step_id") != step_id:
            continue
        out.append(rec)
    return out


def _check_count(actual: int, expected: Any) -> tuple[bool, str]:
    if isinstance(expected, int):
        return actual == expected, f"expected count={expected}, got {actual}"
    if isinstance(expected, str) and expected.startswith(">="):
        n = int(expected[2:])
        return actual >= n, f"expected count>={n}, got {actual}"
    raise ValueError(f"unsupported count spec: {expected!r}")


def score_assertion(assertion: dict[str, Any], *, step_id: int,
                    log_dir: Path) -> AssertionResult:
    worker = assertion["worker"]
    event = assertion.get("event", "send_result")
    log_path = log_dir / f"{worker}.jsonl"
    events = _read_events(log_path, step_id=step_id, event=event)

    # filter by body_prefix if specified
    if "body_prefix" in assertion:
        events = [e for e in events if e.get("body", "").startswith(assertion["body_prefix"])]

    # filter send_result by ok/error and intended_peer_not
    if event == "send_result":
        if assertion.get("kind") == "ok":
            events = [e for e in events if (e.get("raw_stdout") or {}).get("ok") is True]
        elif assertion.get("kind") == "error":
            events = [e for e in events if (e.get("raw_stdout") or {}).get("ok") is False]
        if "intended_peer" in assertion:
            events = [e for e in events if e.get("intended_peer") == assertion["intended_peer"]]
        if "intended_peer_not" in assertion:
            events = [e for e in events if e.get("intended_peer") != assertion["intended_peer_not"]]
        if "one_way" in assertion:
            events = [e for e in events if e.get("one_way") == assertion["one_way"]]

    # count check (only when count is specified)
    if "count" in assertion:
        ok, msg = _check_count(len(events), assertion["count"])
        if not ok:
            return AssertionResult(False, msg, events)
    elif not events:
        return AssertionResult(False, f"no {event} events at step_id={step_id} for {worker}", events)

    # for each remaining event, check field constraints
    for ev in events:
        if "observed_code" in assertion and ev.get("observed_code") != assertion["observed_code"]:
            return AssertionResult(False,
                f"expected observed_code={assertion['observed_code']!r}, got {ev.get('observed_code')!r}",
                events)
        if "observed_kind" in assertion and ev.get("observed_kind") != assertion["observed_kind"]:
            return AssertionResult(False,
                f"expected observed_kind={assertion['observed_kind']!r}, got {ev.get('observed_kind')!r}",
                events)
        if "peer_status" in assertion and ev.get("peer_status") != assertion["peer_status"]:
            return AssertionResult(False,
                f"expected peer_status={assertion['peer_status']!r}, got {ev.get('peer_status')!r}",
                events)
        if "resolved_by" in assertion and ev.get("resolved_by") != assertion["resolved_by"]:
            return AssertionResult(False,
                f"expected resolved_by={assertion['resolved_by']!r}, got {ev.get('resolved_by')!r}",
                events)
        if "handoff_skill" in assertion and ev.get("handoff_skill") != assertion["handoff_skill"]:
            return AssertionResult(False,
                f"expected handoff_skill={assertion['handoff_skill']!r}, got {ev.get('handoff_skill')!r}",
                events)
        if assertion.get("payload_file_nonempty") and not ev.get("payload_file"):
            return AssertionResult(False, "expected non-empty payload_file", events)
        if "candidate_check" in assertion:
            cands = ev.get("candidates") or []
            if not cands:
                return AssertionResult(False, "expected candidates, got none", events)
            top = cands[0]
            for k, v in assertion["candidate_check"].items():
                if top.get(k) != v:
                    return AssertionResult(False,
                        f"candidate[0].{k}: expected {v!r}, got {top.get(k)!r}", events)
        if event == "inbound_frame":
            if assertion.get("all_one_way") and not ev.get("one_way"):
                return AssertionResult(False, "expected all events to be one_way", events)

    # distinct_attempt_ids check for inbound frames
    if assertion.get("distinct_attempt_ids"):
        ids = []
        for ev in events:
            body = ev.get("body", "")
            if body.startswith("COUNTER:"):
                try:
                    p = json.loads(body[len("COUNTER:"):])
                    ids.append(p.get("attempt_id"))
                except json.JSONDecodeError:
                    pass
        if len(set(ids)) != len(ids):
            return AssertionResult(False, f"duplicate attempt_ids: {ids}", events)

    return AssertionResult(True, "ok", events)
