"""Score per-step assertions against worker JSONL logs.

An assertion is a dict (loaded from catalog.yaml). Supported keys:
  worker            : str    — which JSONL to read (sim_driver.jsonl, etc.)
  event             : str    — "send_result" (default) or "inbound_frame"
  kind              : "ok" | "error" | "informational"
  observed_code     : str    — required when kind=error
  observed_kind     : str    — message | bootstrap (for ok)
  peer_status       : str    — live | stale (for ok)
  resolved_by       : str    — title_in_workspace | explicit_surface | ...
  one_way           : bool
  intended_peer     : str
  intended_peer_not : str    — strict: zero events targeted this peer
  count             : int | ">=N"
  body_prefix       : str    — for inbound_frame body filter
  distinct_attempt_ids : bool
  all_one_way       : bool
  candidate_check   : dict   — subset-match against candidates[0]
  candidates_min    : int    — >=N entries in candidates
  payload_file_nonempty : bool
  handoff_skill     : str
  action_required   : str    — recovery verb from p2p error envelope
  retryable         : bool   — retryability bit from p2p error envelope
  surface_differs_from_step_id : int
  reason            : str    — for kind=informational, match informational.reason
  any_of            : list[dict] — alternation; pass if any sub-assertion passes
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.proto import parse_body, MessageClass


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
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"score: skipping malformed JSONL line in {log_path}: {e}",
                  file=sys.stderr)
            continue
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


def _successful_surfaces_for_peer(events: list[dict[str, Any]],
                                  peer: str | None) -> set[str]:
    """Surface refs that were successfully resolved for `peer` across
    `events`. Only `raw_stdout.surface` on ok=True counts. peer_unknown
    responses carry no surface at all (see p2plib/errors.py::peer_unknown),
    so we cannot infer the dead surface from a failure record — only from
    a prior successful resolve."""
    out: set[str] = set()
    for ev in events:
        if peer is not None and ev.get("intended_peer") != peer:
            continue
        raw = ev.get("raw_stdout") or {}
        if raw.get("ok") is not True:
            continue
        s = raw.get("surface")
        if s:
            out.add(s)
    return out


def score_assertion(assertion: dict[str, Any], *, step_id: int,
                    log_dir: Path) -> AssertionResult:
    # any_of: pass if any sub-assertion passes
    if "any_of" in assertion:
        worker = assertion["worker"]
        sub_results = []
        for sub in assertion["any_of"]:
            merged = {"worker": worker, **sub}
            r = score_assertion(merged, step_id=step_id, log_dir=log_dir)
            sub_results.append(r)
            if r.passed:
                return AssertionResult(True, "ok (any_of)", r.observed)
        reasons = "; ".join(r.reason for r in sub_results)
        return AssertionResult(False, f"any_of: all branches failed: {reasons}",
                               [e for r in sub_results for e in r.observed])

    worker = assertion["worker"]
    event = assertion.get("event", "send_result")
    log_path = log_dir / f"{worker}.jsonl"
    log_exists = log_path.exists()
    events = _read_events(log_path, step_id=step_id, event=event)

    # informational kind: read sidecar informational.jsonl (driver-managed)
    if assertion.get("kind") == "informational":
        info_path = log_dir / f"{worker}.informational.jsonl"
        if not info_path.exists():
            return AssertionResult(False,
                f"expected informational event but {info_path.name} missing",
                events)
        for line in info_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("step_id") != step_id:
                continue
            if "reason" in assertion and rec.get("reason") != assertion["reason"]:
                continue
            return AssertionResult(True, "ok (informational)", [rec])
        return AssertionResult(False,
            f"no informational event matched at step {step_id}", events)

    # filter by body_prefix if specified
    if "body_prefix" in assertion:
        events = [e for e in events if e.get("body", "").startswith(assertion["body_prefix"])]

    # intended_peer_not is a strict negative check — independently of all
    # other filters, no event in this step may have targeted that peer.
    if "intended_peer_not" in assertion and event == "send_result":
        bad = [e for e in events if e.get("intended_peer") == assertion["intended_peer_not"]]
        if bad:
            return AssertionResult(False,
                f"expected zero sends to {assertion['intended_peer_not']!r}, got {len(bad)}",
                events)
        # then drop them so subsequent count/field checks see only allowed events
        events = [e for e in events if e.get("intended_peer") != assertion["intended_peer_not"]]

    # filter send_result by ok/error and other selectors
    if event == "send_result":
        if assertion.get("kind") == "ok":
            events = [e for e in events if (e.get("raw_stdout") or {}).get("ok") is True]
        elif assertion.get("kind") == "error":
            events = [e for e in events if (e.get("raw_stdout") or {}).get("ok") is False]
        if "intended_peer" in assertion:
            events = [e for e in events if e.get("intended_peer") == assertion["intended_peer"]]
        if "one_way" in assertion:
            events = [e for e in events if e.get("one_way") == assertion["one_way"]]

    # count check (only when count is specified)
    if "count" in assertion:
        # `count: 0` plus missing log file is suspicious — the worker may
        # never have spawned at all, which is not the same as "the worker
        # spawned and emitted zero events." Require the file to exist.
        if assertion["count"] == 0 and not log_exists:
            return AssertionResult(False,
                f"count: 0 but log file {log_path.name} does not exist "
                f"(worker may never have spawned)", events)
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
        if "action_required" in assertion and ev.get("action_required") != assertion["action_required"]:
            return AssertionResult(False,
                f"expected action_required={assertion['action_required']!r}, got {ev.get('action_required')!r}",
                events)
        if "retryable" in assertion and ev.get("retryable") != assertion["retryable"]:
            return AssertionResult(False,
                f"expected retryable={assertion['retryable']!r}, got {ev.get('retryable')!r}",
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
        if "candidates_min" in assertion:
            cands = ev.get("candidates") or []
            n = assertion["candidates_min"]
            if len(cands) < n:
                return AssertionResult(False,
                    f"expected >={n} candidates, got {len(cands)}", events)
        if "surface_differs_from_step_id" in assertion:
            prior_step = assertion["surface_differs_from_step_id"]
            peer = ev.get("intended_peer")
            # Scan ALL events at or before the cited step (not just that
            # single step). peer_unknown responses carry no surface, so a
            # narrow lookup at step N often returns empty if N was a
            # failure; we want the last surface the peer was ever known
            # to hold while alive.
            all_prior: list[dict[str, Any]] = []
            for line in log_path.read_text().splitlines() if log_exists else []:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("event") != "send_result":
                    continue
                sid = rec.get("step_id")
                if not isinstance(sid, int) or sid > prior_step:
                    continue
                all_prior.append(rec)
            prior_surfaces = _successful_surfaces_for_peer(all_prior, peer)
            if not prior_surfaces:
                return AssertionResult(False,
                    f"surface_differs_from_step_id: no successful prior surface "
                    f"recorded for peer {peer!r} at or before step {prior_step} "
                    f"(cannot prove the resurrection used a new surface)",
                    events)
            current_surface = (ev.get("raw_stdout") or {}).get("surface")
            if not current_surface:
                return AssertionResult(False,
                    "surface_differs_from_step_id: current event has no resolved surface",
                    events)
            if current_surface in prior_surfaces:
                return AssertionResult(False,
                    f"surface {current_surface!r} matches a surface seen at or before "
                    f"step {prior_step} for peer {peer!r}", events)
        if event == "inbound_frame":
            if assertion.get("all_one_way") and not ev.get("one_way"):
                return AssertionResult(False, "expected all events to be one_way", events)

    # distinct_attempt_ids check for inbound frames.
    # Every filtered event must yield exactly one parseable COUNTER
    # attempt_id. Non-COUNTER bodies, parse errors, missing attempt_ids,
    # and non-"ok" parse_status all fail the assertion — otherwise the
    # check would pass vacuously when bodies are garbled.
    if assertion.get("distinct_attempt_ids"):
        ids: list[str] = []
        for ev in events:
            if ev.get("parse_status") and ev["parse_status"] != "ok":
                return AssertionResult(False,
                    f"distinct_attempt_ids: event parse_status={ev['parse_status']!r}",
                    events)
            body = ev.get("body", "")
            parsed = parse_body(body)
            if parsed.kind != MessageClass.COUNTER:
                return AssertionResult(False,
                    f"distinct_attempt_ids: expected COUNTER body, got kind={parsed.kind.value!r}",
                    events)
            if parsed.parse_error:
                return AssertionResult(False,
                    f"distinct_attempt_ids: COUNTER parse error: {parsed.parse_error}",
                    events)
            aid = parsed.payload.get("attempt_id")
            if not aid:
                return AssertionResult(False,
                    "distinct_attempt_ids: COUNTER payload missing attempt_id",
                    events)
            ids.append(aid)
        if len(set(ids)) != len(ids):
            return AssertionResult(False, f"duplicate attempt_ids: {ids}", events)

    return AssertionResult(True, "ok", events)
