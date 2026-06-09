"""First-touch / exclusive / orphan-reclaim ownership algorithm (spec §3.3).

All tests stub the cmux backend by passing a live-UUID set directly into the
pure ownership functions — no live cmux required.
"""

import ownership

A = "uuid-owner-A"
B = "uuid-owner-B"
T = "uuid-target-T"


def test_first_touch_claims_unowned():
    manifest = {}
    live = {A, T}
    res = ownership.resolve_ownership(T, A, live, manifest)
    assert res.status == "claimed"
    assert res.owner == A
    assert manifest[T]["owner_uuid"] == A
    assert "claimed_at" in manifest[T]


def test_second_touch_same_owner_passes():
    manifest = {}
    live = {A, T}
    ownership.resolve_ownership(T, A, live, manifest)  # first claim
    res = ownership.resolve_ownership(T, A, live, manifest)
    assert res.status == "already_mine"
    assert res.owner == A
    assert res.ok


def test_touch_by_different_owner_fails_closed():
    manifest = {}
    live = {A, B, T}
    ownership.resolve_ownership(T, A, live, manifest)  # A claims
    res = ownership.resolve_ownership(T, B, live, manifest)
    assert res.status == "owned_by_other"
    assert res.owner == A           # names the current (other) owner
    assert not res.ok
    assert manifest[T]["owner_uuid"] == A  # NOT stolen


def test_orphaned_owner_is_reclaimed():
    # A owns T, but A's surface is no longer in the live tree -> stale claim.
    manifest = {T: {"owner_uuid": A, "claimed_at": "2026-01-01T00:00:00+00:00"}}
    live = {B, T}  # A absent
    res = ownership.resolve_ownership(T, B, live, manifest)
    assert res.status == "reclaimed"
    assert res.owner == B
    assert manifest[T]["owner_uuid"] == B


def test_release_by_owner():
    manifest = {T: {"owner_uuid": A, "claimed_at": "x"}}
    live = {A, T}
    res = ownership.release(T, A, live, manifest)
    assert res.status == "released"
    assert T not in manifest


def test_release_of_orphan_succeeds():
    manifest = {T: {"owner_uuid": A, "claimed_at": "x"}}
    live = {B, T}  # A gone -> orphan; B may clear it
    res = ownership.release(T, B, live, manifest)
    assert res.status == "released"
    assert T not in manifest


def test_release_of_live_other_owner_refused():
    manifest = {T: {"owner_uuid": A, "claimed_at": "x"}}
    live = {A, B, T}
    res = ownership.release(T, B, live, manifest)
    assert res.status == "owned_by_other"
    assert T in manifest  # untouched


def test_owned_targets_only_live_and_mine():
    dead = "uuid-dead-target"
    other = "uuid-other-target"
    manifest = {
        T: {"owner_uuid": A, "claimed_at": "x"},
        dead: {"owner_uuid": A, "claimed_at": "x"},
        other: {"owner_uuid": B, "claimed_at": "x"},
    }
    live = {A, B, T, other}  # `dead` target not live
    got = ownership.owned_targets(A, live, manifest)
    assert got == [T]  # mine + live only; dead excluded, other-owner excluded


def test_persist_roundtrip(tmp_path):
    path = tmp_path / "owners.json"
    manifest = {T: {"owner_uuid": A, "claimed_at": "x"}}
    ownership.save(manifest, path)
    assert ownership.load(path) == manifest


def test_load_missing_returns_empty(tmp_path):
    assert ownership.load(tmp_path / "nope.json") == {}
