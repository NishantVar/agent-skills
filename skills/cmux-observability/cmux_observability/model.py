"""Dataclasses for the Snapshot data model.

The on-disk JSON snapshot is the dataclass serialization. Bump
`Snapshot.schema_version` on any breaking change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .errors import Failure  # re-exported for callers that import together


@dataclass
class HistoryPoint:
    captured_at: datetime
    agents_total: int
    agents_running: int
    agents_needs_input: int
    by_type: dict[str, int] = field(default_factory=dict)


@dataclass
class HistorySeries:
    points: list[HistoryPoint] = field(default_factory=list)


@dataclass
class RepoStats:
    path: str
    name: str
    commits: dict[str, int] = field(default_factory=dict)   # keys: today/week/30d
    last_commit_at: datetime | None = None


@dataclass
class Productivity:
    repos: list[RepoStats] = field(default_factory=list)
    totals: dict[str, int] = field(default_factory=dict)


@dataclass
class Summary:
    text: str
    state_hint: str
    needs_input_reason: str | None
    confidence: float
    cache_hit: bool
    cached_at: datetime
    prompt_version: int
    screen_hash: str
    redactions_applied: list[str] = field(default_factory=list)
    redaction_summary: str = ""


@dataclass
class Theme:
    label: str
    member_refs: list[str]
    why: str
    confidence: float


@dataclass
class Surface:
    ref: str
    pane_ref: str
    workspace_ref: str
    kind: str                                # "terminal" | "browser"
    title: str
    tty: str | None = None
    cwd: str | None = None
    cpu_pct: float | None = None
    mem_bytes: int | None = None
    is_agent: bool = False


@dataclass
class Workspace:
    ref: str
    title: str
    window_ref: str
    surfaces: list[Surface] = field(default_factory=list)


@dataclass
class Agent:
    surface_ref: str
    workspace_ref: str
    type: str                                # claude_code | codex | opencode | gemini | unknown_agent
    type_source: str                         # cmux_tag | heuristic   (process_sniff deferred post-v1)
    type_confidence: float
    state: str                               # running | needs_input | idle | unknown
    state_source: str
    pid: int | None = None
    summary: Summary | None = None


@dataclass
class Snapshot:
    schema_version: int
    captured_at: datetime
    host: str
    cmux_version: str | None
    workspaces: list[Workspace]
    agents: list[Agent]
    themes: list[Theme] = field(default_factory=list)
    productivity: Productivity | None = None
    history: HistorySeries | None = None
    failures: list[Failure] = field(default_factory=list)


SCHEMA_VERSION = 1
