"""Two-tier sweep, _touch_self heartbeat, (workspace, title) collision,
title-mismatch stale trigger, legacy `name` compat, corrupt-manifest
handling, fcntl serialization."""

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


def test_sweep_reaps_when_tab_title_mismatch(tmp_registry):
    """Tab renamed outside of p2p: manifest.title no longer matches the
    surface's current cmux title, so the identity is dead — file is
    unlinked even though the surface is still live."""
    p = registry.manifest_path("surface:1")
    _write(p, {"title": "old_name", "surface_ref": "surface:1",
               "workspace_ref": "ws:1",
               "started_at": 1, "last_seen": int(time.time())})
    out = registry.all_manifests(
        live_set={"surface:1"},
        surfaces=_surface_index([("surface:1", "ws:1", "renamed_by_user")]))
    assert not p.exists()
    assert out == []


def test_sweep_keeps_manifest_when_no_surface_index_provided(tmp_registry):
    """When `surfaces` is None, the title-mismatch check is skipped —
    callers that don't have a fresh surface_index don't trigger reaping."""
    p = registry.manifest_path("surface:1")
    _write(p, {"title": "keepme", "surface_ref": "surface:1",
               "workspace_ref": "ws:1",
               "started_at": 1, "last_seen": int(time.time())})
    out = registry.all_manifests(live_set={"surface:1"})
    assert p.exists()
    assert out[0]["title"] == "keepme"


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
