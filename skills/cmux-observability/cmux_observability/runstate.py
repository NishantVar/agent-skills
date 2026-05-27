"""Run-state JSON files at ~/.local/state/cmux-observability/run-<id>.json.

A coding agent invokes `collect`, then `record-summaries`, etc.; each
subcommand reads/writes the in-progress Snapshot via a run_id token.

HOME is resolved lazily on each call via `_state_dir()` so tests (and
agents) can `monkeypatch.setenv("HOME", ...)` and have the state dir
follow. Module-level capture would freeze HOME at import time.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from .errors import Failure
from .model import (
    Agent,
    HistoryPoint,
    HistorySeries,
    Productivity,
    RepoStats,
    Snapshot,
    Summary,
    Surface,
    Theme,
    Workspace,
)


def _state_dir() -> Path:
    """Resolve the run-state dir from the current environment.

    Lazy on purpose: tests `monkeypatch.setenv("HOME", ...)` after import.
    """
    home = os.environ.get("HOME", os.path.expanduser("~"))
    return Path(home) / ".local" / "state" / "cmux-observability"


def _ensure_dir() -> Path:
    d = _state_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def state_path(run_id: str) -> Path:
    return _ensure_dir() / f"run-{run_id}.json"


def _serialize(snap: Snapshot) -> dict:
    def default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        if hasattr(o, "__dict__"):
            return o.__dict__
        raise TypeError(f"non-serializable: {type(o)!r}")
    return json.loads(json.dumps(snap, default=default))


def write(run_id: str, snap: Snapshot, *, screen_hashes: dict[str, str],
          redactions_by_surface: dict[str, list[str]]) -> None:
    payload = {
        "run_id": run_id,
        "snapshot": _serialize(snap),
        "screen_hashes": screen_hashes,
        "redactions_by_surface": redactions_by_surface,
    }
    state_path(run_id).write_text(json.dumps(payload, indent=2))


def read(run_id: str) -> tuple[Snapshot, dict[str, str], dict[str, list[str]]]:
    raw = json.loads(state_path(run_id).read_text())
    snap = _rehydrate(raw["snapshot"])
    return snap, raw["screen_hashes"], raw["redactions_by_surface"]


def discard(run_id: str) -> None:
    p = state_path(run_id)
    if p.exists():
        p.unlink()


def _rehydrate(d: dict) -> Snapshot:
    workspaces = [
        Workspace(
            ref=w["ref"], title=w["title"], window_ref=w["window_ref"],
            surfaces=[Surface(**s) for s in w.get("surfaces", [])],
        )
        for w in d.get("workspaces", [])
    ]
    agents: list[Agent] = []
    for a in d.get("agents", []):
        summary = a.get("summary")
        agents.append(Agent(
            surface_ref=a["surface_ref"],
            workspace_ref=a["workspace_ref"],
            type=a["type"],
            type_source=a["type_source"],
            type_confidence=a["type_confidence"],
            state=a["state"],
            state_source=a["state_source"],
            pid=a.get("pid"),
            summary=(
                Summary(
                    text=summary["text"],
                    state_hint=summary["state_hint"],
                    needs_input_reason=summary.get("needs_input_reason"),
                    confidence=summary["confidence"],
                    cache_hit=summary["cache_hit"],
                    cached_at=datetime.fromisoformat(summary["cached_at"]),
                    prompt_version=summary["prompt_version"],
                    screen_hash=summary["screen_hash"],
                    redactions_applied=summary.get("redactions_applied", []),
                    redaction_summary=summary.get("redaction_summary", ""),
                )
                if summary else None
            ),
        ))
    themes = [Theme(**t) for t in d.get("themes", [])]
    prod = d.get("productivity")
    productivity = None
    if prod:
        repos = []
        for r in prod.get("repos", []):
            last = r.get("last_commit_at")
            repos.append(RepoStats(
                path=r["path"],
                name=r["name"],
                commits=r.get("commits", {}),
                last_commit_at=datetime.fromisoformat(last) if last else None,
            ))
        productivity = Productivity(repos=repos, totals=prod.get("totals", {}))
    history = d.get("history")
    history_obj = None
    if history:
        pts = [
            HistoryPoint(
                captured_at=datetime.fromisoformat(p["captured_at"]),
                agents_total=p["agents_total"],
                agents_running=p["agents_running"],
                agents_needs_input=p["agents_needs_input"],
                by_type=p.get("by_type", {}),
            )
            for p in history.get("points", [])
        ]
        history_obj = HistorySeries(points=pts)
    return Snapshot(
        schema_version=d["schema_version"],
        captured_at=datetime.fromisoformat(d["captured_at"]),
        host=d["host"],
        cmux_version=d.get("cmux_version"),
        workspaces=workspaces,
        agents=agents,
        themes=themes,
        productivity=productivity,
        history=history_obj,
        failures=[Failure(**f) for f in d.get("failures", [])],
    )
