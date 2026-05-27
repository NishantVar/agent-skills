"""Build a Snapshot from collector outputs."""

from __future__ import annotations

from datetime import datetime

from .collector.cmux import TopResult
from .model import Agent, Snapshot, Workspace


# Title-sniff hints for type fallback when cmux tag is absent.
_TITLE_HINTS = (
    ("claude_code", ("claude code", "claude_code", "✳ claude")),
    ("codex",       ("codex",)),
    ("opencode",    ("opencode",)),
    ("gemini",      ("gemini",)),
)


def _sniff_type(title: str) -> tuple[str, float, str] | None:
    low = title.lower()
    for kind, needles in _TITLE_HINTS:
        if any(n in low for n in needles):
            return kind, 0.6, "title_sniff"
    return None


def _normalize_state(raw: str) -> str:
    raw = raw.strip().lower()
    if raw == "running":
        return "running"
    if "input" in raw:
        return "needs_input"
    if raw in ("idle", "waiting"):
        return "idle"
    return "unknown"


def normalize(
    *, workspaces: list[Workspace], top: TopResult,
    host: str, cmux_version: str | None, now: datetime,
) -> Snapshot:
    # Attach per-surface CPU/MEM stats.
    for w in workspaces:
        for s in w.surfaces:
            stats = top.stats_by_surface.get(s.ref)
            if stats is not None:
                s.cpu_pct = stats.cpu_pct
                s.mem_bytes = stats.mem_bytes

    agents: list[Agent] = []
    workspace_index = {w.ref: w for w in workspaces}

    # Authoritative path: cmux tags.
    for ws_ref, tags in top.tags_by_workspace.items():
        ws = workspace_index.get(ws_ref)
        if ws is None:
            continue
        # Heuristic: pair each tag with the most likely surface in the
        # workspace whose title matches the tag kind, falling back to the
        # first surface that doesn't already have an agent.
        used: set[str] = set()
        for tag in tags:
            picked = None
            # Pass A: exact tag.kind match in the surface title.
            for s in ws.surfaces:
                if s.ref in used:
                    continue
                if tag.kind in s.title.lower():
                    picked = s
                    break
            # Pass B: fall back to the first unused surface.
            if picked is None:
                for s in ws.surfaces:
                    if s.ref not in used:
                        picked = s
                        break
            if picked is None:
                continue
            used.add(picked.ref)
            picked.is_agent = True
            agents.append(Agent(
                surface_ref=picked.ref,
                workspace_ref=ws.ref,
                type=tag.kind,
                type_source="cmux_tag",
                type_confidence=1.0,
                state=_normalize_state(tag.state),
                state_source="cmux_tag",
                pid=tag.pid,
            ))

    # Fallback: title sniff for any agent-titled surface that didn't get a tag.
    tagged_refs = {a.surface_ref for a in agents}
    for w in workspaces:
        for s in w.surfaces:
            if s.ref in tagged_refs:
                continue
            hit = _sniff_type(s.title)
            if hit is None:
                continue
            kind, conf, source = hit
            s.is_agent = True
            agents.append(Agent(
                surface_ref=s.ref,
                workspace_ref=w.ref,
                type=kind,
                type_source=source,
                type_confidence=conf,
                state="unknown",
                state_source="unknown",
                pid=None,
            ))

    return Snapshot(
        schema_version=1,
        captured_at=now,
        host=host,
        cmux_version=cmux_version,
        workspaces=workspaces,
        agents=agents,
        themes=[],
        productivity=None,
        history=None,
        failures=[],
    )
