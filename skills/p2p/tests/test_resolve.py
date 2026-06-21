"""Peer resolution: workspace-scoped tab title match, live /
live_first_contact / ambiguous / unknown / renamed."""

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


def test_idle_peer_resolves_live_regardless_of_last_seen():
    """An idle peer is still live — no TTL-derived stale status."""
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "sleepy"}])
    manifests = [{"title": "sleepy", "surface_ref": "surface:1",
                  "workspace_ref": "ws:1",
                  "started_at": 1, "last_seen": 1}]
    r = resolve.resolve_peer("sleepy", manifests, surfaces,
                             scope_workspace_ref="ws:1")
    assert r.kind == "live"
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


def test_renamed_returns_candidate_with_former_and_current_titles():
    """No live current-title match but a live surface in scope has the
    addressed title in former_titles -> kind=renamed with the matched
    former title and the current cmux title."""
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "r1"}])
    manifests = [{"title": "r1", "former_titles": ["reviewer"],
                  "surface_ref": "surface:1", "workspace_ref": "ws:1",
                  "started_at": 1, "last_seen": 1}]
    r = resolve.resolve_peer("reviewer", manifests, surfaces,
                             scope_workspace_ref="ws:1")
    assert r.kind == "renamed"
    assert len(r.candidates) == 1
    c = r.candidates[0]
    assert c["ref"] == "surface:1"
    assert c["current_title"] == "r1"
    assert c["former_title"] == "reviewer"
    assert c["workspace_ref"] == "ws:1"


def test_renamed_match_is_case_insensitive():
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "r1"}])
    manifests = [{"title": "r1", "former_titles": ["Reviewer"],
                  "surface_ref": "surface:1", "workspace_ref": "ws:1",
                  "started_at": 1, "last_seen": 1}]
    r = resolve.resolve_peer("REVIEWER", manifests, surfaces,
                             scope_workspace_ref="ws:1")
    assert r.kind == "renamed"
    # The matched-former-title preserves the manifest's casing so the
    # human-readable message reads naturally.
    assert r.candidates[0]["former_title"] == "Reviewer"


def test_renamed_chain_returns_matched_intermediate_title():
    """Chain reviewer -> r1 -> reviewer_v2: addressing r1 returns r1
    as the matched former_title (not the earliest reviewer)."""
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "reviewer_v2"}])
    manifests = [{"title": "reviewer_v2",
                  "former_titles": ["reviewer", "r1"],
                  "surface_ref": "surface:1", "workspace_ref": "ws:1",
                  "started_at": 1, "last_seen": 1}]
    r = resolve.resolve_peer("r1", manifests, surfaces,
                             scope_workspace_ref="ws:1")
    assert r.kind == "renamed"
    assert r.candidates[0]["former_title"] == "r1"
    assert r.candidates[0]["current_title"] == "reviewer_v2"


def test_live_current_title_match_wins_over_rename():
    """Edge case #3 from the proposal: surface A renamed away (former
    title 'reviewer'), surface B then created with title 'reviewer'.
    Live current match must win over rename detection."""
    surfaces = _setup([
        {"workspace_ref": "ws:1", "workspace_title": "W",
         "surface_ref": "surface:1", "title": "r1"},
        {"workspace_ref": "ws:1", "workspace_title": "W",
         "surface_ref": "surface:2", "title": "reviewer"},
    ])
    manifests = [
        {"title": "r1", "former_titles": ["reviewer"],
         "surface_ref": "surface:1", "workspace_ref": "ws:1",
         "started_at": 1, "last_seen": 1},
        {"title": "reviewer", "surface_ref": "surface:2",
         "workspace_ref": "ws:1",
         "started_at": 1, "last_seen": 1},
    ]
    r = resolve.resolve_peer("reviewer", manifests, surfaces,
                             scope_workspace_ref="ws:1")
    assert r.kind == "live"
    assert r.surface_ref == "surface:2"


def test_renamed_scoped_to_caller_workspace():
    """Edge case #4: cross-workspace rename detection is out of scope.
    A renamed manifest in another workspace does NOT surface to a
    caller scoped to ws:1."""
    surfaces = _setup([{"workspace_ref": "ws:2", "workspace_title": "Other",
                        "surface_ref": "surface:1", "title": "r1"}])
    manifests = [{"title": "r1", "former_titles": ["reviewer"],
                  "surface_ref": "surface:1", "workspace_ref": "ws:2",
                  "started_at": 1, "last_seen": 1}]
    r = resolve.resolve_peer("reviewer", manifests, surfaces,
                             scope_workspace_ref="ws:1")
    assert r.kind == "unknown"


def test_not_in_workspace_when_registered_sibling_agent_present():
    """A registered agent ('alpha') is live in scope but the addressed
    title matches no tab — the title was a misname. Surface the sibling
    as a candidate instead of declaring the scope empty (which would
    push the caller toward a duplicate spawn)."""
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "alpha"}])
    manifests = [{"title": "alpha",
                  "surface_ref": "surface:1", "workspace_ref": "ws:1",
                  "started_at": 1, "last_seen": 1}]
    r = resolve.resolve_peer("missing", manifests, surfaces,
                             scope_workspace_ref="ws:1")
    assert r.kind == "not_in_workspace"
    assert len(r.candidates) == 1
    c = r.candidates[0]
    assert c["ref"] == "surface:1"
    assert c["title"] == "alpha"
    assert c["workspace_ref"] == "ws:1"


def test_unknown_when_only_self_is_live_in_scope():
    """The caller is the only registered agent in scope — there is no
    sibling to route to, so a title miss is genuinely unknown."""
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "me"}])
    manifests = [{"title": "me",
                  "surface_ref": "surface:1", "workspace_ref": "ws:1",
                  "started_at": 1, "last_seen": 1}]
    r = resolve.resolve_peer("missing", manifests, surfaces,
                             scope_workspace_ref="ws:1",
                             self_surface_ref="surface:1")
    assert r.kind == "unknown"


def test_not_in_workspace_excludes_out_of_scope_siblings():
    """Candidates are scoped: a registered agent in another workspace
    is NOT offered when the caller scoped to ws:1 (and ws:1 has its own
    sibling)."""
    surfaces = _setup([
        {"workspace_ref": "ws:1", "workspace_title": "Mine",
         "surface_ref": "surface:1", "title": "local"},
        {"workspace_ref": "ws:2", "workspace_title": "Theirs",
         "surface_ref": "surface:2", "title": "remote"},
    ])
    manifests = [
        {"title": "local", "surface_ref": "surface:1",
         "workspace_ref": "ws:1", "started_at": 1, "last_seen": 1},
        {"title": "remote", "surface_ref": "surface:2",
         "workspace_ref": "ws:2", "started_at": 1, "last_seen": 1},
    ]
    r = resolve.resolve_peer("missing", manifests, surfaces,
                             scope_workspace_ref="ws:1")
    assert r.kind == "not_in_workspace"
    refs = {c["ref"] for c in r.candidates}
    assert refs == {"surface:1"}


def test_source_is_title_global_when_scope_none():
    surfaces = _setup([{"workspace_ref": "ws:1", "workspace_title": "W",
                        "surface_ref": "surface:1", "title": "only"}])
    r = resolve.resolve_peer("only", [], surfaces,
                             scope_workspace_ref=None)
    assert r.kind == "live_first_contact"
    assert r.source == "title_global"


def test_window_scope_disambiguates_duplicate_title():
    """A window ref can scope title resolution when the same tab title
    appears in more than one cmux window."""
    surfaces = _setup([
        {"window_ref": "window:1", "workspace_ref": "ws:1",
         "workspace_title": "A", "surface_ref": "surface:1",
         "title": "worker"},
        {"window_ref": "window:2", "workspace_ref": "ws:2",
         "workspace_title": "B", "surface_ref": "surface:2",
         "title": "worker"},
    ])
    r = resolve.resolve_peer("worker", [], surfaces,
                             scope_workspace_ref=None,
                             scope_window_ref="window:2")
    assert r.kind == "live_first_contact"
    assert r.source == "title_in_window"
    assert r.surface_ref == "surface:2"
    assert r.workspace_ref == "ws:2"


def test_window_scope_candidates_include_window_ref():
    """When a title is outside the scoped window, the ambiguity
    candidates carry the destination window so callers can rerun with
    --window."""
    surfaces = _setup([
        {"window_ref": "window:1", "workspace_ref": "ws:1",
         "workspace_title": "A", "surface_ref": "surface:1",
         "title": "local"},
        {"window_ref": "window:2", "workspace_ref": "ws:2",
         "workspace_title": "B", "surface_ref": "surface:2",
         "title": "reviewer"},
    ])
    r = resolve.resolve_peer("reviewer", [], surfaces,
                             scope_workspace_ref=None,
                             scope_window_ref="window:1")
    assert r.kind == "ambiguous"
    assert r.candidates == [{
        "ref": "surface:2",
        "workspace_ref": "ws:2",
        "workspace_title": "B",
        "window_ref": "window:2",
        "title": "reviewer",
    }]


# ---------------- bounce_out_of_scope flag ----------------

def test_bounce_off_descends_instead_of_out_of_scope_ambiguous():
    """With bounce_out_of_scope=False, a title that exists only outside
    the scope no longer bounces to `ambiguous` — it falls through to the
    sibling/unknown path so a caller can keep cascading to a wider
    tier. The default (True) preserves the opt-in-via-scope bounce."""
    surfaces = _setup([
        {"workspace_ref": "ws:1", "workspace_title": "Mine",
         "surface_ref": "surface:1", "title": "other"},
        {"workspace_ref": "ws:2", "workspace_title": "Theirs",
         "surface_ref": "surface:2", "title": "reviewer"},
    ])
    r = resolve.resolve_peer("reviewer", [], surfaces,
                             scope_workspace_ref="ws:1",
                             bounce_out_of_scope=False)
    assert r.kind == "unknown"


# ---------------- locality cascade (resolve_peer_local) ----------------

def test_local_cascade_prefers_own_workspace():
    """Tier 1: a live match in the caller's own workspace wins even when
    the same title is also live in another workspace of the same window."""
    surfaces = _setup([
        {"window_ref": "window:1", "workspace_ref": "ws:1",
         "workspace_title": "Mine", "surface_ref": "surface:1",
         "title": "reviewer"},
        {"window_ref": "window:1", "workspace_ref": "ws:2",
         "workspace_title": "Theirs", "surface_ref": "surface:2",
         "title": "reviewer"},
    ])
    r = resolve.resolve_peer_local("reviewer", [], surfaces,
                                   caller_workspace_ref="ws:1",
                                   caller_window_ref="window:1")
    assert r.kind == "live_first_contact"
    assert r.surface_ref == "surface:1"
    assert r.source == "title_in_workspace"


def test_local_cascade_falls_back_to_caller_window():
    """Tier 2: title absent from own workspace but present in another
    workspace of the caller's window resolves there (title_in_window)."""
    surfaces = _setup([
        {"window_ref": "window:1", "workspace_ref": "ws:1",
         "workspace_title": "Mine", "surface_ref": "surface:1",
         "title": "local_only"},
        {"window_ref": "window:1", "workspace_ref": "ws:2",
         "workspace_title": "Theirs", "surface_ref": "surface:2",
         "title": "reviewer"},
    ])
    r = resolve.resolve_peer_local("reviewer", [], surfaces,
                                   caller_workspace_ref="ws:1",
                                   caller_window_ref="window:1")
    assert r.kind == "live_first_contact"
    assert r.surface_ref == "surface:2"
    assert r.source == "title_in_window"


def test_local_cascade_falls_back_to_other_windows():
    """Tier 3: title absent from own workspace and own window resolves in
    another window (title_global)."""
    surfaces = _setup([
        {"window_ref": "window:1", "workspace_ref": "ws:1",
         "workspace_title": "Mine", "surface_ref": "surface:1",
         "title": "local"},
        {"window_ref": "window:2", "workspace_ref": "ws:2",
         "workspace_title": "Far", "surface_ref": "surface:2",
         "title": "reviewer"},
    ])
    r = resolve.resolve_peer_local("reviewer", [], surfaces,
                                   caller_workspace_ref="ws:1",
                                   caller_window_ref="window:1")
    assert r.kind == "live_first_contact"
    assert r.surface_ref == "surface:2"
    assert r.source == "title_global"


def test_local_cascade_window_tier_ambiguous_when_multiple():
    """Two same-titled live tabs in the caller's window (different
    workspaces) → ambiguous; the cascade does not silently pick."""
    surfaces = _setup([
        {"window_ref": "window:1", "workspace_ref": "ws:1",
         "workspace_title": "Mine", "surface_ref": "surface:1",
         "title": "me"},
        {"window_ref": "window:1", "workspace_ref": "ws:2",
         "workspace_title": "A", "surface_ref": "surface:2",
         "title": "reviewer"},
        {"window_ref": "window:1", "workspace_ref": "ws:3",
         "workspace_title": "B", "surface_ref": "surface:3",
         "title": "reviewer"},
    ])
    r = resolve.resolve_peer_local("reviewer", [], surfaces,
                                   caller_workspace_ref="ws:1",
                                   caller_window_ref="window:1")
    assert r.kind == "ambiguous"
    refs = {c["ref"] for c in r.candidates}
    assert refs == {"surface:2", "surface:3"}


def test_local_cascade_own_workspace_rename_wins_over_window_live():
    """A renamed former-holder in the caller's OWN workspace (tier 1) is
    more local than a live current-title match in another workspace of
    the same window (tier 2). The cascade returns peer_renamed rather
    than silently routing to the farther live tab."""
    surfaces = _setup([
        {"window_ref": "window:1", "workspace_ref": "ws:1",
         "workspace_title": "Mine", "surface_ref": "surface:1",
         "title": "r1"},
        {"window_ref": "window:1", "workspace_ref": "ws:2",
         "workspace_title": "Theirs", "surface_ref": "surface:2",
         "title": "reviewer"},
    ])
    manifests = [
        {"title": "r1", "former_titles": ["reviewer"],
         "surface_ref": "surface:1", "workspace_ref": "ws:1",
         "started_at": 1, "last_seen": 1},
        {"title": "reviewer", "surface_ref": "surface:2",
         "workspace_ref": "ws:2", "started_at": 1, "last_seen": 1},
    ]
    r = resolve.resolve_peer_local("reviewer", manifests, surfaces,
                                   caller_workspace_ref="ws:1",
                                   caller_window_ref="window:1")
    assert r.kind == "renamed"
    assert len(r.candidates) == 1
    assert r.candidates[0]["ref"] == "surface:1"


def test_local_cascade_far_window_rename_does_not_beat_global_live():
    """A renamed former-holder in a NON-own-workspace tier (the caller's
    window) must NOT stop the cascade ahead of a live current-title match
    in a farther tier. Only an own-workspace (tier 1) rename outranks
    farther live matches; for wider tiers, live wins and the rename is
    only a fallback when nothing is live anywhere."""
    surfaces = _setup([
        {"window_ref": "window:1", "workspace_ref": "ws:1",
         "workspace_title": "Mine", "surface_ref": "surface:1",
         "title": "me"},
        {"window_ref": "window:1", "workspace_ref": "ws:2",
         "workspace_title": "Nearby", "surface_ref": "surface:2",
         "title": "r1"},
        {"window_ref": "window:2", "workspace_ref": "ws:3",
         "workspace_title": "Far", "surface_ref": "surface:3",
         "title": "reviewer"},
    ])
    manifests = [
        {"title": "me", "surface_ref": "surface:1",
         "workspace_ref": "ws:1", "started_at": 1, "last_seen": 1},
        {"title": "r1", "former_titles": ["reviewer"],
         "surface_ref": "surface:2", "workspace_ref": "ws:2",
         "started_at": 1, "last_seen": 1},
        {"title": "reviewer", "surface_ref": "surface:3",
         "workspace_ref": "ws:3", "started_at": 1, "last_seen": 1},
    ]
    r = resolve.resolve_peer_local("reviewer", manifests, surfaces,
                                   caller_workspace_ref="ws:1",
                                   caller_window_ref="window:1",
                                   self_surface_ref="surface:1")
    assert r.kind == "live"
    assert r.surface_ref == "surface:3"
    assert r.source == "title_global"


def test_local_cascade_far_window_rename_is_fallback_when_no_live():
    """When a non-own-workspace rename is the only signal (no live
    current-title match anywhere), it is still returned as peer_renamed."""
    surfaces = _setup([
        {"window_ref": "window:1", "workspace_ref": "ws:1",
         "workspace_title": "Mine", "surface_ref": "surface:1",
         "title": "me"},
        {"window_ref": "window:1", "workspace_ref": "ws:2",
         "workspace_title": "Nearby", "surface_ref": "surface:2",
         "title": "r1"},
    ])
    manifests = [
        {"title": "me", "surface_ref": "surface:1",
         "workspace_ref": "ws:1", "started_at": 1, "last_seen": 1},
        {"title": "r1", "former_titles": ["reviewer"],
         "surface_ref": "surface:2", "workspace_ref": "ws:2",
         "started_at": 1, "last_seen": 1},
    ]
    r = resolve.resolve_peer_local("reviewer", manifests, surfaces,
                                   caller_workspace_ref="ws:1",
                                   caller_window_ref="window:1",
                                   self_surface_ref="surface:1")
    assert r.kind == "renamed"
    assert r.candidates[0]["ref"] == "surface:2"


def test_local_cascade_miss_returns_own_workspace_siblings():
    """Title found nowhere live: the miss surfaces the caller's OWN
    workspace siblings as candidates (most-local retarget help)."""
    surfaces = _setup([
        {"window_ref": "window:1", "workspace_ref": "ws:1",
         "workspace_title": "Mine", "surface_ref": "surface:1",
         "title": "helper"},
        {"window_ref": "window:2", "workspace_ref": "ws:2",
         "workspace_title": "Far", "surface_ref": "surface:2",
         "title": "stranger"},
    ])
    manifests = [
        {"title": "helper", "surface_ref": "surface:1",
         "workspace_ref": "ws:1", "started_at": 1, "last_seen": 1},
        {"title": "stranger", "surface_ref": "surface:2",
         "workspace_ref": "ws:2", "started_at": 1, "last_seen": 1},
    ]
    r = resolve.resolve_peer_local("ghost", manifests, surfaces,
                                   caller_workspace_ref="ws:1",
                                   caller_window_ref="window:1")
    assert r.kind == "not_in_workspace"
    refs = {c["ref"] for c in r.candidates}
    assert refs == {"surface:1"}


def test_local_cascade_unknown_when_title_and_siblings_absent():
    """No matching title and no registered siblings anywhere → unknown."""
    surfaces = _setup([
        {"window_ref": "window:1", "workspace_ref": "ws:1",
         "workspace_title": "Mine", "surface_ref": "surface:1",
         "title": "me"},
    ])
    manifests = [{"title": "me", "surface_ref": "surface:1",
                  "workspace_ref": "ws:1", "started_at": 1,
                  "last_seen": 1}]
    r = resolve.resolve_peer_local("ghost", manifests, surfaces,
                                   caller_workspace_ref="ws:1",
                                   caller_window_ref="window:1",
                                   self_surface_ref="surface:1")
    assert r.kind == "unknown"
