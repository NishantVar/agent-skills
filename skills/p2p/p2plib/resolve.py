"""Resolve `addressed -> surface` for `send`.

Single routing key: the cmux tab title, scoped to the caller's current
workspace by default. There is no separate manifest `name` to compete
with the title.

Resolution:
  1. Match `addressed` (case-insensitive) against tab titles in
     `scope_workspace_ref` when supplied; otherwise match across all
     workspaces.
  2. 0 hits -> unknown. 1 hit -> live (or stale if its manifest is
     marked stale). >1 hits -> ambiguous with candidates carrying
     workspace info so the caller can disambiguate via --peer-surface
     or --workspace.

Rename detection (only fires when step 1 yields zero live matches):
  - Scan in-scope live manifests for `former_titles` containing the
    addressed title. Any hit becomes a `renamed` candidate carrying
    the surface's current title + the matched former title. A live
    current-title match in step 1 always wins over rename detection
    (peer_renamed is the fallback when no live current match exists).

Stale resolution:
  - When the matched manifest has `status="stale"`, the result kind is
    `stale`. The peer is expected to receive a fresh bootstrap so it
    can re-touch itself.
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
    # title is the destination tab title (used as the routing key).
    title: str | None = None
    # source describes which path matched. "title_in_workspace" |
    # "title_global" | None.
    source: str | None = None
    # candidates is populated only for kind="ambiguous".
    candidates: list[dict] = field(default_factory=list)


def _stale(manifest: dict | None) -> bool:
    return bool(manifest) and manifest.get("status") == "stale"


def resolve_peer(addressed: str, manifests: list[dict],
                 surfaces: dict[str, dict],
                 scope_workspace_ref: str | None = None
                 ) -> ResolveResult:
    """`manifests` is the post-sweep registry list; `surfaces` is the
    surface_index keyed by surface_ref. When `scope_workspace_ref` is
    given, only tabs in that workspace are considered; cross-workspace
    matches collapse to `unknown` unless explicitly opted out by
    passing None for global scope."""
    addressed_cf = addressed.casefold()

    in_scope: list[dict] = []
    out_of_scope: list[dict] = []
    for s in surfaces.values():
        if (s.get("title") or "").casefold() != addressed_cf:
            continue
        if (scope_workspace_ref is None
                or s.get("workspace_ref") == scope_workspace_ref):
            in_scope.append(s)
        else:
            out_of_scope.append(s)

    matches = in_scope if scope_workspace_ref is not None else in_scope

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
            rename_candidates.append({
                "ref": s["ref"],
                "workspace_ref": s.get("workspace_ref"),
                "workspace_title": s.get("workspace_title", ""),
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
                candidates=[
                    {"ref": s["ref"],
                     "workspace_ref": s.get("workspace_ref"),
                     "workspace_title": s.get("workspace_title", ""),
                     "title": s.get("title", "")}
                    for s in out_of_scope
                ],
            )
        return ResolveResult(kind="unknown")

    if len(matches) > 1:
        return ResolveResult(
            kind="ambiguous",
            candidates=[
                {"ref": s["ref"],
                 "workspace_ref": s.get("workspace_ref"),
                 "workspace_title": s.get("workspace_title", ""),
                 "title": s.get("title", "")}
                for s in matches
            ],
        )

    s = matches[0]
    by_surface = {m.get("surface_ref"): m for m in manifests}
    m = by_surface.get(s["ref"])
    if m is None:
        kind = "live_first_contact"
    elif _stale(m):
        kind = "stale"
    else:
        kind = "live"
    return ResolveResult(
        kind=kind,
        surface_ref=s["ref"],
        workspace_ref=s.get("workspace_ref"),
        workspace_title=s.get("workspace_title", ""),
        title=s.get("title", ""),
        source=("title_in_workspace" if scope_workspace_ref
                else "title_global"),
    )
