"""Peer resolution: workspace-scoped tab title match, live /
live_first_contact / stale / ambiguous / unknown."""

from __future__ import annotations

from p2plib import resolve, surface
from fake_cmux import FakeCmux


def _setup(tree_surfaces):
    fc = FakeCmux()
    for kw in tree_surfaces:
        fc.add(**kw)
    return surface.surface_index(fc.tree())


def test_live_by_tab_in_scope_with_manifest():
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "alpha"}])
    manifests = [{"title": "alpha", "surface_ref": "surface:1",
                  "workspace_ref": "ws:1",
                  "started_at": 1, "last_seen": 1}]
    r = resolve.resolve_peer("alpha", manifests, surfaces,
                             scope_workspace_ref="ws:1")
    assert r.kind == "live"
    assert r.source == "title_in_workspace"
    assert r.title == "alpha"
    assert r.surface_ref == "surface:1"
    assert r.workspace_ref == "ws:1"


def test_live_first_contact_when_no_manifest():
    """Tab exists in scope, no manifest for it — needs bootstrap."""
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "fresh"}])
    r = resolve.resolve_peer("fresh", [], surfaces,
                             scope_workspace_ref="ws:1")
    assert r.kind == "live_first_contact"
    assert r.surface_ref == "surface:1"
    assert r.title == "fresh"


def test_stale_when_manifest_marked_stale():
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "sleepy"}])
    manifests = [{"title": "sleepy", "surface_ref": "surface:1",
                  "workspace_ref": "ws:1",
                  "started_at": 1, "last_seen": 1, "status": "stale"}]
    r = resolve.resolve_peer("sleepy", manifests, surfaces,
                             scope_workspace_ref="ws:1")
    assert r.kind == "stale"
    assert r.title == "sleepy"


def test_out_of_scope_returns_ambiguous_with_candidates():
    """Caller scoped to ws:1 but the title exists in ws:2 — caller can
    opt out via --workspace."""
    surfaces = _setup([
        {"workspace_ref": "ws:1", "workspace_title": "Mine",
         "surface_ref": "surface:1", "title": "other"},
        {"workspace_ref": "ws:2", "workspace_title": "Theirs",
         "surface_ref": "surface:2", "title": "reviewer"},
    ])
    r = resolve.resolve_peer("reviewer", [], surfaces,
                             scope_workspace_ref="ws:1")
    assert r.kind == "ambiguous"
    refs = {c["ref"] for c in r.candidates}
    assert refs == {"surface:2"}
    assert r.candidates[0]["workspace_ref"] == "ws:2"


def test_unknown_when_title_nowhere():
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "other"}])
    r = resolve.resolve_peer("missing", [], surfaces,
                             scope_workspace_ref="ws:1")
    assert r.kind == "unknown"


def test_ambiguous_when_two_matches_in_same_scope():
    """Edge case: cmux normally enforces unique tab titles per workspace,
    but if two surfaces in the same workspace share a casefold-equal
    title we surface that rather than picking silently."""
    surfaces = _setup([
        {"workspace_ref": "ws:1", "workspace_title": "W",
         "surface_ref": "surface:1", "title": "Dup"},
        {"workspace_ref": "ws:1", "workspace_title": "W",
         "surface_ref": "surface:2", "title": "dup"},
    ])
    r = resolve.resolve_peer("dup", [], surfaces,
                             scope_workspace_ref="ws:1")
    assert r.kind == "ambiguous"
    refs = {c["ref"] for c in r.candidates}
    assert refs == {"surface:1", "surface:2"}


def test_global_scope_collapses_cross_workspace_to_ambiguous():
    """When called without a scope, same-title tabs in two workspaces
    are ambiguous — no silent picking."""
    surfaces = _setup([
        {"workspace_ref": "ws:A", "workspace_title": "A",
         "surface_ref": "surface:1", "title": "claude"},
        {"workspace_ref": "ws:B", "workspace_title": "B",
         "surface_ref": "surface:2", "title": "claude"},
    ])
    r = resolve.resolve_peer("claude", [], surfaces,
                             scope_workspace_ref=None)
    assert r.kind == "ambiguous"
    refs = {c["ref"] for c in r.candidates}
    assert refs == {"surface:1", "surface:2"}


def test_tab_title_match_is_case_insensitive():
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "CTest"}])
    r = resolve.resolve_peer("ctest", [], surfaces,
                             scope_workspace_ref="ws:1")
    assert r.kind == "live_first_contact"
    assert r.surface_ref == "surface:1"


def test_source_is_title_global_when_scope_none():
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "only"}])
    r = resolve.resolve_peer("only", [], surfaces,
                             scope_workspace_ref=None)
    assert r.kind == "live_first_contact"
    assert r.source == "title_global"
