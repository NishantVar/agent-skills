"""Resolve `addressed -> surface` for `send`.

Resolution precedence:
  1. Manifest `name` match (preferred — names are unique by collision
     check, and registration is the explicit identity contract).
  2. cmux tab `title` match. The title is cosmetic and can collide
     across workspaces; >1 hit returns `ambiguous`. 0 hits returns
     `unknown`. 1 hit cross-references the registry to recover the
     canonical manifest name if one exists.

Stale resolution:
  - When the matched manifest has `status="stale"`, the result kind is
    `stale` regardless of which path (name or tab) matched. The peer is
    expected to receive a fresh bootstrap so it can re-touch itself.
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
    # canonical_name is the manifest's name when one exists at the
    # resolved surface. None for live-by-tab-no-manifest.
    canonical_name: str | None = None
    # source describes which path matched. "name" | "tab_with_manifest"
    # | "tab_first_contact" | None.
    source: str | None = None
    # candidates is populated only for kind="ambiguous".
    candidates: list[dict] = field(default_factory=list)


def _stale(manifest: dict) -> bool:
    return manifest.get("status") == "stale"


def resolve_peer(addressed: str, manifests: list[dict],
                 surfaces: dict[str, dict]) -> ResolveResult:
    """`manifests` is the post-sweep registry list; `surfaces` is the
    surface_index keyed by surface_ref."""
    # 1. Manifest name match.
    name_matches = [m for m in manifests if m.get("name") == addressed]
    if len(name_matches) > 1:
        # Defensive — registration enforces uniqueness, but if the
        # invariant ever breaks we still want a sane response.
        return ResolveResult(
            kind="ambiguous",
            candidates=[
                {"ref": m.get("surface_ref"),
                 "workspace_ref": (
                     surfaces.get(m.get("surface_ref") or "", {})
                     .get("workspace_ref")),
                 "workspace_title": (
                     surfaces.get(m.get("surface_ref") or "", {})
                     .get("workspace_title", ""))}
                for m in name_matches
            ],
        )
    if name_matches:
        m = name_matches[0]
        s = surfaces.get(m.get("surface_ref") or "", {})
        kind = "stale" if _stale(m) else "live"
        return ResolveResult(
            kind=kind,
            surface_ref=m.get("surface_ref"),
            workspace_ref=s.get("workspace_ref"),
            workspace_title=s.get("workspace_title", ""),
            canonical_name=m.get("name"),
            source="name",
        )

    # 2. Tab title match across live surfaces.
    tab_matches = [s for s in surfaces.values()
                   if s.get("title") == addressed]
    if not tab_matches:
        return ResolveResult(kind="unknown")
    if len(tab_matches) > 1:
        return ResolveResult(
            kind="ambiguous",
            candidates=[
                {"ref": s["ref"],
                 "workspace_ref": s.get("workspace_ref"),
                 "workspace_title": s.get("workspace_title", "")}
                for s in tab_matches
            ],
        )
    s = tab_matches[0]
    by_surface = {m.get("surface_ref"): m for m in manifests}
    m = by_surface.get(s["ref"])
    if m is None:
        return ResolveResult(
            kind="live",
            surface_ref=s["ref"],
            workspace_ref=s.get("workspace_ref"),
            workspace_title=s.get("workspace_title", ""),
            canonical_name=None,
            source="tab_first_contact",
        )
    kind = "stale" if _stale(m) else "live"
    return ResolveResult(
        kind=kind,
        surface_ref=s["ref"],
        workspace_ref=s.get("workspace_ref"),
        workspace_title=s.get("workspace_title", ""),
        canonical_name=m.get("name"),
        source="tab_with_manifest",
    )
