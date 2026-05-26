"""Sweep, _touch_self heartbeat, (workspace, title) collision,
title-mismatch in-place rename promotion (with former_titles list),
legacy `name` compat, corrupt-manifest handling, fcntl serialization."""

from __future__ import annotations

import json
import multiprocessing
import time

from p2plib import registry


def _write(path, data):
    path.write_text(json.dumps(data))


def _surface_index(items):
    """items: list of (surface_ref, workspace_ref, title)."""
    return {
        ref: {"ref": ref, "workspace_ref": ws, "title": t,
              "workspace_title": "", "tty": ""}
        for ref, ws, t in items
    }


def test_sweep_deletes_when_surface_gone(tmp_registry):
    p = registry.manifest_path("surface:1")
    _write(p, {"title": "gone", "surface_ref": "surface:1",
               "workspace_ref": "ws:1",
               "started_at": 1, "last_seen": int(time.time())})
    registry.all_manifests(live_set=set())
    assert not p.exists()


def test_sweep_marks_stale_when_ttl_expired_but_keeps_file(tmp_registry):
    p = registry.manifest_path("surface:1")
    old = int(time.time()) - registry.TTL_SECONDS - 5
    _write(p, {"title": "idle", "surface_ref": "surface:1",
               "workspace_ref": "ws:1",
               "started_at": old, "last_seen": old})
    out = registry.all_manifests(
        live_set={"surface:1"},
        surfaces=_surface_index([("surface:1", "ws:1", "idle")]))
    assert p.exists()
    assert out[0]["status"] == "stale"
    on_disk = json.loads(p.read_text())
    assert on_disk["status"] == "stale"


def test_sweep_clears_stale_when_fresh_again(tmp_registry):
    p = registry.manifest_path("surface:1")
    _write(p, {"title": "back", "surface_ref": "surface:1",
               "workspace_ref": "ws:1",
               "started_at": 1, "last_seen": int(time.time()),
               "status": "stale"})
    out = registry.all_manifests(
        live_set={"surface:1"},
        surfaces=_surface_index([("surface:1", "ws:1", "back")]))
    assert "status" not in out[0]
    assert "status" not in json.loads(p.read_text())


def test_sweep_promotes_rename_in_place(tmp_registry):
    """Tab renamed outside p2p while surface is still live: manifest is
    rewritten in place, NOT unlinked. title becomes the current cmux
    title; prior title is appended to former_titles. This is what
    powers the peer_renamed handoff so peers addressing the old title
    get a bridge to the new one."""
    p = registry.manifest_path("surface:1")
    _write(p, {"title": "reviewer", "surface_ref": "surface:1",
               "workspace_ref": "ws:1",
               "started_at": 1, "last_seen": int(time.time())})
    out = registry.all_manifests(
        live_set={"surface:1"},
        surfaces=_surface_index([("surface:1", "ws:1", "r1")]))
    assert p.exists()
    m = out[0]
    assert m["title"] == "r1"
    assert m["former_titles"] == ["reviewer"]
    on_disk = json.loads(p.read_text())
    assert on_disk["title"] == "r1"
    assert on_disk["former_titles"] == ["reviewer"]


def test_sweep_rename_chain_appends_to_former_titles(tmp_registry):
    """Second rename after a first one extends former_titles rather
    than overwriting it. Rename chain (reviewer -> r1 -> reviewer_v2)
    keeps every intermediate name reachable as a peer_renamed
    candidate."""
    p = registry.manifest_path("surface:1")
    _write(p, {"title": "r1", "former_titles": ["reviewer"],
               "surface_ref": "surface:1", "workspace_ref": "ws:1",
               "started_at": 1, "last_seen": int(time.time())})
    out = registry.all_manifests(
        live_set={"surface:1"},
        surfaces=_surface_index([("surface:1", "ws:1", "reviewer_v2")]))
    assert out[0]["title"] == "reviewer_v2"
    assert out[0]["former_titles"] == ["reviewer", "r1"]


def test_sweep_keeps_manifest_when_no_surface_index_provided(tmp_registry):
    """When `surfaces` is None, the rename-promotion path is skipped —
    callers that don't have a fresh surface_index leave the manifest
    untouched."""
    p = registry.manifest_path("surface:1")
    _write(p, {"title": "keepme", "surface_ref": "surface:1",
               "workspace_ref": "ws:1",
               "started_at": 1, "last_seen": int(time.time())})
    out = registry.all_manifests(live_set={"surface:1"})
    assert p.exists()
    assert out[0]["title"] == "keepme"
    assert "former_titles" not in out[0]


def test_sweep_skips_empty_current_title(tmp_registry):
    """A surface_index entry with title=='' is a snapshot miss, not a
    real rename. Don't clobber the registered title with empty."""
    p = registry.manifest_path("surface:1")
    _write(p, {"title": "real", "surface_ref": "surface:1",
               "workspace_ref": "ws:1",
               "started_at": 1, "last_seen": int(time.time())})
    out = registry.all_manifests(
        live_set={"surface:1"},
        surfaces=_surface_index([("surface:1", "ws:1", "")]))
    assert out[0]["title"] == "real"
    assert "former_titles" not in out[0]


def test_sweep_promotes_legacy_manifest_workspace_ref(tmp_registry):
    """QA-E regression: legacy manifests (no workspace_ref) get the
    field filled in from the live surface index on sweep. Without this,
    the resolver's workspace-scoped former_titles scan silently skips
    them and peer_renamed never fires for legacy renamed surfaces.

    Also verifies the legacy `name` field is dropped once `title` is
    in place — single-identifier refactor."""
    p = registry.manifest_path("surface:576")
    _write(p, {"name": "btest", "surface_ref": "surface:576",
               "started_at": int(time.time())})
    out = registry.all_manifests(
        live_set={"surface:576"},
        surfaces=_surface_index([("surface:576", "workspace:49", "btest")]))
    assert len(out) == 1
    assert out[0]["workspace_ref"] == "workspace:49"
    assert out[0]["title"] == "btest"
    assert "name" not in out[0]
    on_disk = json.loads(p.read_text())
    assert on_disk["workspace_ref"] == "workspace:49"
    assert on_disk["title"] == "btest"
    assert "name" not in on_disk


def test_sweep_promotes_legacy_manifest_with_rename(tmp_registry):
    """QA-E end-to-end: legacy manifest + cmux rename. Sweep must
    write workspace_ref AND promote the rename in the same pass —
    former_titles ends up with the legacy `name` value so the resolver
    can bridge addressers of the old title to the new one."""
    p = registry.manifest_path("surface:576")
    _write(p, {"name": "btest", "surface_ref": "surface:576",
               "started_at": int(time.time())})
    out = registry.all_manifests(
        live_set={"surface:576"},
        surfaces=_surface_index(
            [("surface:576", "workspace:49", "btest_v2")]))
    assert out[0]["workspace_ref"] == "workspace:49"
    assert out[0]["title"] == "btest_v2"
    assert out[0]["former_titles"] == ["btest"]
    assert "name" not in out[0]


def test_sweep_reaps_legacy_manifest_when_surface_orphan(tmp_registry):
    """QA-E sub-decision: a legacy manifest whose surface is no longer
    live gets reaped on sweep, NOT half-promoted. The reap check
    happens before promotion, so this should already hold — guard
    against regression."""
    p = registry.manifest_path("surface:576")
    _write(p, {"name": "btest", "surface_ref": "surface:576",
               "started_at": 1})
    out = registry.all_manifests(
        live_set=set(),
        surfaces=_surface_index([]))
    assert not p.exists()
    assert out == []


def test_sweep_reaps_when_surface_gone_even_with_former_titles(tmp_registry):
    """Surface absent from live_set still wins over the no-reap rule —
    a renamed-then-closed surface drops cleanly. The whole
    former_titles history goes with the manifest."""
    p = registry.manifest_path("surface:1")
    _write(p, {"title": "current", "former_titles": ["reviewer", "r1"],
               "surface_ref": "surface:1", "workspace_ref": "ws:1",
               "started_at": 1, "last_seen": int(time.time())})
    out = registry.all_manifests(
        live_set=set(),
        surfaces=_surface_index([]))
    assert not p.exists()
    assert out == []


def test_touch_self_revives_stale_keeps_title(tmp_registry):
    p = registry.manifest_path("surface:9")
    _write(p, {"title": "sleeper", "surface_ref": "surface:9",
               "workspace_ref": "ws:1",
               "started_at": 1, "last_seen": 1, "status": "stale"})
    registry.touch_self("surface:9")
    m = json.loads(p.read_text())
    assert m["title"] == "sleeper"
    assert "status" not in m
    assert m["last_seen"] >= int(time.time()) - 5


def test_touch_self_noop_when_unregistered(tmp_registry):
    registry.touch_self("surface:42")
    assert not registry.manifest_path("surface:42").exists()


def test_touch_self_noop_when_surface_unknown(tmp_registry):
    registry.touch_self(None)


def test_register_collision_same_workspace_same_title(tmp_registry):
    p = registry.manifest_path("surface:1")
    _write(p, {"title": "alpha", "surface_ref": "surface:1",
               "workspace_ref": "ws:1",
               "started_at": 1, "last_seen": int(time.time())})
    surfaces = _surface_index([
        ("surface:1", "ws:1", "alpha"),
        ("surface:2", "ws:1", "anything"),
    ])
    m, err = registry.register("alpha", "surface:2", "ws:1",
                               live_set={"surface:1", "surface:2"},
                               surfaces=surfaces)
    assert m is None
    assert err["kind"] == "title_collision"
    assert err["holder_surface"] == "surface:1"
    assert err["workspace_ref"] == "ws:1"


def test_register_no_collision_across_workspaces(tmp_registry):
    """Same title in DIFFERENT workspaces is fine — routing key is
    (workspace_ref, title)."""
    p = registry.manifest_path("surface:1")
    _write(p, {"title": "alpha", "surface_ref": "surface:1",
               "workspace_ref": "ws:A",
               "started_at": 1, "last_seen": int(time.time())})
    surfaces = _surface_index([
        ("surface:1", "ws:A", "alpha"),
        ("surface:2", "ws:B", "alpha"),
    ])
    m, err = registry.register("alpha", "surface:2", "ws:B",
                               live_set={"surface:1", "surface:2"},
                               surfaces=surfaces)
    assert err is None
    assert m["title"] == "alpha"
    assert m["workspace_ref"] == "ws:B"


def test_register_idempotent_for_self(tmp_registry):
    surfaces = _surface_index([("surface:1", "ws:1", "solo")])
    m1, _ = registry.register("solo", "surface:1", "ws:1",
                              live_set={"surface:1"}, surfaces=surfaces)
    m2, err = registry.register("solo", "surface:1", "ws:1",
                                live_set={"surface:1"}, surfaces=surfaces)
    assert err is None
    assert m2["title"] == m1["title"] == "solo"
    assert m2["last_seen"] >= m1["last_seen"]


def test_register_not_in_cmux(tmp_registry):
    _, err = registry.register("ghost", "surface:999", "ws:1",
                               live_set=set())
    assert err["kind"] == "not_in_cmux"


def test_legacy_name_field_promoted_to_title_on_read(tmp_registry):
    """Old code wrote `name`; new reads treat that as `title`. The file
    is NOT rewritten (mutation is opt-in via touch/register)."""
    p = registry.manifest_path("surface:1")
    _write(p, {"name": "legacy_one", "surface_ref": "surface:1",
               "workspace_ref": "ws:1",
               "started_at": 1, "last_seen": int(time.time())})
    out = registry.all_manifests(live_set={"surface:1"})
    assert len(out) == 1
    assert out[0]["title"] == "legacy_one"
    # File on disk still has `name`.
    on_disk = json.loads(p.read_text())
    assert "name" in on_disk
    assert "title" not in on_disk


def test_corrupt_manifest_skip_not_unlink(tmp_registry, capsys):
    p = registry.manifest_path("surface:5")
    p.write_text("{ not valid json")
    out = registry.all_manifests(live_set={"surface:5"})
    assert p.exists(), "corrupt files must be preserved, not unlinked"
    assert out == []
    err = capsys.readouterr().err
    assert "skipping corrupt manifest" in err


def _child_register(args):
    reg_path, title, surface_ref = args
    from p2plib import registry as r
    from pathlib import Path
    r.REGISTRY = Path(reg_path)
    r.LOCK_PATH = Path(reg_path) / ".lock"
    return r.register(title, surface_ref, "ws:1",
                      live_set={"surface:1", "surface:2"})


def test_concurrent_register_serializes(tmp_registry):
    """Two concurrent registers for the SAME (workspace, title) must
    serialize: one wins, the other sees a title_collision."""
    args = [
        (str(tmp_registry), "race", "surface:1"),
        (str(tmp_registry), "race", "surface:2"),
    ]
    with multiprocessing.Pool(2) as pool:
        results = pool.map(_child_register, args)
    successes = [r for r in results if r[1] is None]
    collisions = [r for r in results if r[1] is not None]
    assert len(successes) == 1
    assert len(collisions) == 1
    assert collisions[0][1]["kind"] == "title_collision"
