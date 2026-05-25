"""Peer resolution: manifest name → tab title → ambiguity → unknown,
plus stale-pass-through and canonical-name recovery."""

from __future__ import annotations

from p2plib import resolve, surface
from fake_cmux import FakeCmux


def _setup(tree_surfaces):
    fc = FakeCmux()
    for kw in tree_surfaces:
        fc.add(**kw)
    return surface.surface_index(fc.tree())


def test_live_by_manifest_name():
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "anything"}])
    manifests = [{"name": "alpha", "surface_ref": "surface:1",
                  "started_at": 1, "last_seen": 1}]
    r = resolve.resolve_peer("alpha", manifests, surfaces)
    assert r.kind == "live"
    assert r.source == "name"
    assert r.canonical_name == "alpha"
    assert r.surface_ref == "surface:1"
    assert r.workspace_ref == "ws:1"


def test_live_by_tab_no_manifest():
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "fresh-tab"}])
    r = resolve.resolve_peer("fresh-tab", [], surfaces)
    assert r.kind == "live"
    assert r.source == "tab_first_contact"
    assert r.canonical_name is None
    assert r.surface_ref == "surface:1"


def test_live_by_tab_with_manifest_uses_canonical():
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "any-title"}])
    manifests = [{"name": "canonical_name", "surface_ref": "surface:1",
                  "started_at": 1, "last_seen": 1}]
    r = resolve.resolve_peer("any-title", manifests, surfaces)
    assert r.kind == "live"
    assert r.source == "tab_with_manifest"
    assert r.canonical_name == "canonical_name"


def test_stale_by_name():
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "x"}])
    manifests = [{"name": "stale_one", "surface_ref": "surface:1",
                  "started_at": 1, "last_seen": 1, "status": "stale"}]
    r = resolve.resolve_peer("stale_one", manifests, surfaces)
    assert r.kind == "stale"
    assert r.canonical_name == "stale_one"


def test_stale_by_tab_recovers_canonical():
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "tab_x"}])
    manifests = [{"name": "real_name", "surface_ref": "surface:1",
                  "started_at": 1, "last_seen": 1, "status": "stale"}]
    r = resolve.resolve_peer("tab_x", manifests, surfaces)
    assert r.kind == "stale"
    assert r.canonical_name == "real_name"  # canonical, not "tab_x"


def test_ambiguous_tab_across_workspaces():
    surfaces = _setup([
        {"workspace_ref": "ws:A", "workspace_title": "A",
         "surface_ref": "surface:1", "title": "claude"},
        {"workspace_ref": "ws:B", "workspace_title": "B",
         "surface_ref": "surface:2", "title": "claude"},
    ])
    r = resolve.resolve_peer("claude", [], surfaces)
    assert r.kind == "ambiguous"
    refs = {c["ref"] for c in r.candidates}
    assert refs == {"surface:1", "surface:2"}


def test_unknown_peer():
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "other"}])
    r = resolve.resolve_peer("missing", [], surfaces)
    assert r.kind == "unknown"


def test_tab_title_match_is_case_insensitive():
    """`--peer CTest` must reach a tab titled `ctest`. Tab titles are
    user-typed cosmetic strings; casing should not be a routing key."""
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "ctest"}])
    r = resolve.resolve_peer("CTest", [], surfaces)
    assert r.kind == "live"
    assert r.source == "tab_first_contact"
    assert r.surface_ref == "surface:1"


def test_tab_titles_differing_only_in_case_are_ambiguous():
    """Two tabs whose titles casefold to the same string must be flagged
    ambiguous, not silently picked."""
    surfaces = _setup([
        {"workspace_ref": "ws:A", "workspace_title": "A",
         "surface_ref": "surface:1", "title": "ctest"},
        {"workspace_ref": "ws:B", "workspace_title": "B",
         "surface_ref": "surface:2", "title": "CTest"},
    ])
    r = resolve.resolve_peer("ctest", [], surfaces)
    assert r.kind == "ambiguous"
    refs = {c["ref"] for c in r.candidates}
    assert refs == {"surface:1", "surface:2"}


def test_name_match_wins_over_tab_match():
    """When a tab title equals one name and a different agent's
    manifest name equals the same string, the manifest name path wins
    (names are explicit identity, tab titles are cosmetic)."""
    surfaces = _setup([
        {"workspace_ref": "ws:1", "workspace_title": "W",
         "surface_ref": "surface:1", "title": "claude"},  # tab match
        {"workspace_ref": "ws:1", "workspace_title": "W",
         "surface_ref": "surface:2", "title": "other"},   # name match
    ])
    manifests = [{"name": "claude", "surface_ref": "surface:2",
                  "started_at": 1, "last_seen": 1}]
    r = resolve.resolve_peer("claude", manifests, surfaces)
    assert r.surface_ref == "surface:2"
    assert r.source == "name"
