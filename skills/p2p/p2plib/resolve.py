"""Resolve `addressed -> surface` for `send`.

Single routing key: the cmux tab title, scoped to the caller's current
workspace by default. There is no separate manifest `name` to compete
with the title.

Resolution:
  1. Match `addressed` (case-insensitive) against tab titles in the
     supplied workspace/window scope. With no scope, match across all
     workspaces and windows.
  2. 1 hit -> live (or live_first_contact if no manifest exists yet
     for that surface). >1 hits -> ambiguous with candidates carrying
     workspace info so the caller can disambiguate via --peer-surface
     or --workspace. 0 hits -> not_in_workspace when OTHER registered
     agents are live in scope (their titles become candidates so the
     caller can correct a misnamed --peer), else unknown. p2p never
     spawns; both zero-hit kinds are routing-only signals, and the
     caller decides whether to retarget or spawn a peer itself (via
     tfork / afork).

Liveness is grounded entirely in `cmux tree`. A surface present in
the tree is reachable; manifest age is not consulted. There is no
`stale` kind — an idle agent waiting at its prompt is `live`.

Rename detection (only fires when step 1 yields zero live matches):
  - Scan in-scope live manifests for `former_titles` containing the
    addressed title. Any hit becomes a `renamed` candidate carrying
    the surface's current title + the matched former title. A live
    current-title match in step 1 always wins over rename detection
    (peer_renamed is the fallback when no live current match exists).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResolveResult:
    kind: str
    # surface_ref / workspace_ref are set for every non-unknown kind.
    surface_ref: str | None = None
    workspace_ref: str | None = None
    workspace_title: str = ""
    window_ref: str | None = None
    # title is the destination tab title (used as the routing key).
    title: str | None = None
    # source describes which path matched: title_in_workspace,
    # title_in_window, title_global, or None.
    source: str | None = None
    # candidates is populated for kind in {"ambiguous", "renamed",
    # "not_in_workspace"}.
    candidates: list[dict] = field(default_factory=list)


def resolve_peer(addressed: str, manifests: list[dict],
                 surfaces: dict[str, dict],
                 scope_workspace_ref: str | None = None,
                 scope_window_ref: str | None = None,
                 self_surface_ref: str | None = None
                 ) -> ResolveResult:
    """`manifests` is the post-sweep registry list; `surfaces` is the
    surface_index keyed by surface_ref. Scope refs restrict title
    matching to a workspace, a window, or their intersection; passing
    None for a dimension makes that dimension global."""
    addressed_cf = addressed.casefold()

    def is_in_scope(s: dict) -> bool:
        if (scope_workspace_ref is not None
                and s.get("workspace_ref") != scope_workspace_ref):
            return False
        if (scope_window_ref is not None
                and s.get("window_ref") != scope_window_ref):
            return False
        return True

    def candidate(s: dict) -> dict:
        return {
            "ref": s["ref"],
            "workspace_ref": s.get("workspace_ref"),
            "workspace_title": s.get("workspace_title", ""),
            "window_ref": s.get("window_ref"),
            "title": s.get("title", ""),
        }

    scoped_matches: list[dict] = []
    out_of_scope: list[dict] = []
    for s in surfaces.values():
        if (s.get("title") or "").casefold() != addressed_cf:
            continue
        if is_in_scope(s):
            scoped_matches.append(s)
        else:
            out_of_scope.append(s)

    matches = scoped_matches

    if not matches:
        # No live current-title match in scope. Check for an in-scope
        # former-title match FIRST — a renamed agent in the caller's
        # own workspace is more relevant than a current-title match
        # in some other workspace. If the caller's workspace itself
        # has a peer that used to hold this title, we want
        # peer_renamed to fire rather than the out-of-scope
        # ambiguous bounce.
        rename_candidates: list[dict] = []
        for m in manifests:
            if (scope_workspace_ref is not None
                    and m.get("workspace_ref") != scope_workspace_ref):
                continue
            matched_former = None
            for ft in (m.get("former_titles") or []):
                if ft.casefold() == addressed_cf:
                    matched_former = ft
                    break
            if matched_former is None:
                continue
            m_ref = m.get("surface_ref") or ""
            s = surfaces.get(m_ref)
            if s is None:
                # Manifest references a surface not in the snapshot —
                # shouldn't happen post-sweep but skip defensively.
                continue
            if not is_in_scope(s):
                continue
            rename_candidates.append({
                "ref": s["ref"],
                "workspace_ref": s.get("workspace_ref"),
                "workspace_title": s.get("workspace_title", ""),
                "window_ref": s.get("window_ref"),
                "current_title": s.get("title", ""),
                "former_title": matched_former,
            })
        if rename_candidates:
            return ResolveResult(kind="renamed",
                                 candidates=rename_candidates)
        if out_of_scope:
            # No in-scope match (current or former). Caller scoped to
            # current workspace but the title exists elsewhere — let
            # them opt out via --workspace.
            return ResolveResult(
                kind="ambiguous",
                candidates=[candidate(s) for s in out_of_scope],
            )
        # No match under any title in scope. Before declaring the peer
        # absent, list the OTHER registered agents that are live in
        # scope. If the addressed title was a misname (a guess that
        # matches no live tab) while a real agent sits right there under
        # a different title, the caller gets a "did you mean one of
        # these" rather than concluding the workspace is empty. p2p
        # never spawns — this list is purely a routing aid. An empty
        # list (kind="unknown") means no registered agent is reachable
        # under any title in scope.
        peer_candidates: list[dict] = []
        for m in manifests:
            m_ref = m.get("surface_ref") or ""
            if m_ref == self_surface_ref:
                continue
            s = surfaces.get(m_ref)
            if s is None:
                # Manifest references a surface not in the snapshot —
                # not live post-sweep; skip.
                continue
            if not is_in_scope(s):
                continue
            peer_candidates.append(candidate(s))
        if peer_candidates:
            return ResolveResult(kind="not_in_workspace",
                                 candidates=peer_candidates)
        return ResolveResult(kind="unknown")

    if len(matches) > 1:
        return ResolveResult(
            kind="ambiguous",
            candidates=[candidate(s) for s in matches],
        )

    s = matches[0]
    by_surface = {m.get("surface_ref"): m for m in manifests}
    m = by_surface.get(s["ref"])
    kind = "live_first_contact" if m is None else "live"
    return ResolveResult(
        kind=kind,
        surface_ref=s["ref"],
        workspace_ref=s.get("workspace_ref"),
        workspace_title=s.get("workspace_title", ""),
        window_ref=s.get("window_ref"),
        title=s.get("title", ""),
        source=("title_in_workspace" if scope_workspace_ref
                else "title_in_window" if scope_window_ref
                else "title_global"),
    )
