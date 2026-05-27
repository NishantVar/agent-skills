"""The JSON contract between Python helpers and the calling coding agent.

There is no LLM client here. Helpers prepare redacted scrollback, expose a
"pending" payload, accept Summary JSON back from the agent, and cache
results by (surface_ref, screen_hash, prompt_version).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from .errors import Failure
from .model import Snapshot, Summary
from .redact import redact


def _screen_hash(redacted_text: str) -> str:
    return hashlib.sha256(redacted_text.encode("utf-8")).hexdigest()


def _cache_lookup(
    conn: sqlite3.Connection, surface_ref: str, screen_hash: str, prompt_version: int,
) -> Summary | None:
    row = conn.execute(
        "SELECT summary_json, cached_at FROM summary_cache "
        "WHERE surface_ref=? AND screen_hash=? AND prompt_version=?",
        (surface_ref, screen_hash, prompt_version),
    ).fetchone()
    if not row:
        return None
    payload = json.loads(row[0])
    return Summary(
        text=payload["summary"],
        state_hint=payload["state_hint"],
        needs_input_reason=payload.get("needs_input_reason"),
        confidence=payload["confidence"],
        cache_hit=True,
        cached_at=datetime.fromisoformat(row[1]),
        prompt_version=prompt_version,
        screen_hash=screen_hash,
        redactions_applied=payload.get("redactions_applied", []),
        redaction_summary=payload.get("redaction_summary", ""),
    )


def _is_summary_eligible(agent) -> bool:
    # cmux_tag agents are summarized when active; heuristic agents always
    # flow through (the summarizer is how we learn their real state).
    if agent.type_source == "heuristic":
        return True
    return agent.state in ("running", "needs_input")


def attach_cached_summaries(
    snap: Snapshot, conn: sqlite3.Connection,
    screens: dict[str, str], prompt_version: int,
) -> None:
    """Attach cached summaries for the requested `prompt_version` and clear
    stale ones. Walks each summary-eligible agent (cmux_tag running /
    needs_input, plus every heuristic-classified agent) that has screen
    content: if a cache row exists for `(surface_ref, redacted_screen_hash,
    prompt_version)`, the matching Summary is attached; otherwise
    `agent.summary` is set to None so a previously-attached Summary from a
    different prompt_version does not shadow a cache miss.
    """
    for agent in snap.agents:
        if not _is_summary_eligible(agent):
            continue
        raw = screens.get(agent.surface_ref)
        if raw is None:
            continue
        redacted, _applied = redact(raw)
        h = _screen_hash(redacted)
        cached = _cache_lookup(conn, agent.surface_ref, h, prompt_version)
        agent.summary = cached


def pending_for_agent(
    snap: Snapshot, conn: sqlite3.Connection,
    screens: dict[str, str], prompt_version: int,
) -> list[dict]:
    """Return JSON-ready payload listing agents that still need a summary.

    Cache hits are short-circuited: those agents get their Summary attached
    directly to `snap` and are absent from the returned list.
    """
    attach_cached_summaries(snap, conn, screens, prompt_version)
    pending: list[dict] = []
    for agent in snap.agents:
        if not _is_summary_eligible(agent):
            continue
        if agent.summary is not None:
            continue
        raw = screens.get(agent.surface_ref)
        if raw is None:
            continue
        redacted, applied = redact(raw)
        h = _screen_hash(redacted)
        # workspace title lookup
        ws_title = next(
            (w.title for w in snap.workspaces if w.ref == agent.workspace_ref),
            "",
        )
        cwd = next(
            (s.cwd for w in snap.workspaces for s in w.surfaces if s.ref == agent.surface_ref),
            None,
        )
        title = next(
            (s.title for w in snap.workspaces for s in w.surfaces if s.ref == agent.surface_ref),
            "",
        )
        pending.append({
            "surface_ref": agent.surface_ref,
            "workspace_title": ws_title,
            "type": agent.type,
            "cmux_state": agent.state,
            "title": title,
            "cwd": cwd,
            "scrollback": redacted,
            "screen_hash": h,
            "redactions_applied": applied,
            "prompt_version": prompt_version,
        })
    return pending


def record_from_agent(
    payload: dict, snap: Snapshot, conn: sqlite3.Connection, *,
    prompt_version: int,
    screen_hashes: dict[str, str],
    redactions_by_surface: dict[str, list[str]] | None = None,
) -> list[Failure]:
    """Accept the agent's Summary JSON, validate, persist to cache, attach.

    `screen_hashes` is the mapping returned in the pending payload so the
    helper can write the cache key without re-hashing. `redactions_by_surface`
    is the same `redactions_applied` list per surface.
    """
    redactions_by_surface = redactions_by_surface or {}
    failures: list[Failure] = []
    summaries = payload.get("summaries", [])
    by_ref = {a.surface_ref: a for a in snap.agents}
    now = datetime.now(timezone.utc)

    for entry in summaries:
        sref = entry.get("surface_ref")
        if sref not in by_ref:
            failures.append(Failure(
                component="summarize_io", target=str(sref),
                message="unknown surface_ref in agent response",
            ))
            continue
        agent = by_ref[sref]
        h = screen_hashes.get(sref)
        if h is None:
            failures.append(Failure(
                component="summarize_io", target=sref,
                message="missing screen_hash for response",
            ))
            continue

        try:
            text = str(entry["summary"]).strip()
            state_hint = str(entry["state_hint"]).strip()
            confidence = float(entry.get("confidence", 0.0))
        except (KeyError, ValueError, TypeError) as e:
            failures.append(Failure(
                component="summarize_io", target=sref,
                message=f"malformed summary entry: {e}",
            ))
            continue

        applied = list(redactions_by_surface.get(sref, []))
        summary = Summary(
            text=text,
            state_hint=state_hint,
            needs_input_reason=entry.get("needs_input_reason"),
            confidence=confidence,
            cache_hit=False,
            cached_at=now,
            prompt_version=prompt_version,
            screen_hash=h,
            redactions_applied=applied,
            redaction_summary=", ".join(applied),
        )

        # cmux tag wins on state-hint disagreement.
        if state_hint and state_hint != agent.state:
            failures.append(Failure(
                component="summarize_io", target=sref,
                message=f"state hint {state_hint!r} disagreed with cmux tag {agent.state!r}",
            ))

        cache_payload = {
            "surface_ref": sref,
            "summary": text,
            "state_hint": state_hint,
            "needs_input_reason": entry.get("needs_input_reason"),
            "confidence": confidence,
            "redactions_applied": applied,
            "redaction_summary": summary.redaction_summary,
        }
        conn.execute(
            "INSERT OR REPLACE INTO summary_cache "
            "(surface_ref, screen_hash, prompt_version, summary_json, cached_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (sref, h, prompt_version, json.dumps(cache_payload), now.isoformat()),
        )
        agent.summary = summary
    conn.commit()
    return failures


_MIN_SUMMARY_COVERAGE = 0.30
_MIN_THEME_CONFIDENCE = 0.5


def themes_payload(snap: Snapshot, *, summaries_enabled: bool = True) -> dict:
    """Compact payload for the theme grouping step. No raw scrollback.

    Deterministic guardrails — these collapse the section BEFORE asking the
    calling agent to author themes, so the agent's instruction-following
    doesn't have to be the only line of defense:

    1. If `summaries_enabled` is False, return `{payload: null, omit: True,
       reason: "summaries-disabled"}`.
    2. If fewer than 30% of running/needs_input agents carry a Summary,
       return `{payload: null, omit: True, reason: "sparse-summaries", ...}`.

    Otherwise return `{payload: {surfaces: [...]}, omit: False}`.
    """
    if not summaries_enabled:
        return {"payload": None, "omit": True, "reason": "summaries-disabled"}

    active = [a for a in snap.agents if a.state in ("running", "needs_input")]
    if active:
        with_summary = sum(1 for a in active if a.summary is not None)
        coverage = with_summary / len(active)
        if coverage < _MIN_SUMMARY_COVERAGE:
            return {
                "payload": None, "omit": True,
                "reason": "sparse-summaries",
                "coverage": coverage,
            }

    items = []
    for ws in snap.workspaces:
        for s in ws.surfaces:
            ag = next((a for a in snap.agents if a.surface_ref == s.ref), None)
            items.append({
                "surface_ref": s.ref,
                "workspace_ref": ws.ref,
                "workspace_title": ws.title,
                "title": s.title,
                "cwd": s.cwd,
                "type": ag.type if ag else None,
                "state": ag.state if ag else None,
                "summary": ag.summary.text if (ag and ag.summary) else None,
            })
    return {"payload": {"surfaces": items}, "omit": False}


def record_themes_from_agent(payload: dict, snap: Snapshot) -> list[Failure]:
    """Validate and attach themes. Errors are non-fatal.

    Deterministic guardrail (mirrors themes_payload): if all proposed themes
    have confidence < 0.5, the helper drops them on the floor and leaves
    `snap.themes` empty. Renderer omits the section when themes is empty.
    """
    from .model import Theme  # local import to avoid cycle on doc build
    failures: list[Failure] = []
    parsed: list[Theme] = []
    for raw in payload.get("themes", []):
        try:
            theme = Theme(
                label=str(raw["label"]).strip(),
                member_refs=list(raw["member_refs"]),
                why=str(raw.get("why", "")).strip(),
                confidence=float(raw.get("confidence", 0.0)),
            )
        except (KeyError, ValueError, TypeError) as e:
            failures.append(Failure(
                component="summarize_io", target=str(raw),
                message=f"malformed theme entry: {e}",
            ))
            continue
        parsed.append(theme)

    if parsed and all(t.confidence < _MIN_THEME_CONFIDENCE for t in parsed):
        # All low-confidence — collapse the section deterministically.
        snap.themes = []
        return failures

    snap.themes = parsed
    return failures
