"""Two-tier sweep, _touch_self heartbeat, collision semantics,
corrupt-manifest handling, fcntl serialization."""

from __future__ import annotations

import json
import multiprocessing
import time

from p2plib import registry


def _write(path, data):
    path.write_text(json.dumps(data))


def test_sweep_deletes_when_surface_gone(tmp_registry):
    p = registry.manifest_path("surface:1")
    _write(p, {"name": "gone", "surface_ref": "surface:1",
               "started_at": 1, "last_seen": int(time.time())})
    registry.all_manifests(live_set=set())  # no live surfaces
    assert not p.exists()


def test_sweep_marks_stale_when_ttl_expired_but_keeps_file(tmp_registry):
    p = registry.manifest_path("surface:1")
    old = int(time.time()) - registry.TTL_SECONDS - 5
    _write(p, {"name": "idle", "surface_ref": "surface:1",
               "started_at": old, "last_seen": old})
    out = registry.all_manifests(live_set={"surface:1"})
    assert p.exists()
    assert out[0]["status"] == "stale"
    on_disk = json.loads(p.read_text())
    assert on_disk["status"] == "stale"


def test_sweep_clears_stale_when_fresh_again(tmp_registry):
    """A previously stale manifest whose last_seen got refreshed should
    have status removed on the next sweep."""
    p = registry.manifest_path("surface:1")
    _write(p, {"name": "back", "surface_ref": "surface:1",
               "started_at": 1, "last_seen": int(time.time()),
               "status": "stale"})
    out = registry.all_manifests(live_set={"surface:1"})
    assert "status" not in out[0]
    assert "status" not in json.loads(p.read_text())


def test_touch_self_revives_stale_keeps_name(tmp_registry):
    p = registry.manifest_path("surface:9")
    _write(p, {"name": "sleeper", "surface_ref": "surface:9",
               "started_at": 1, "last_seen": 1, "status": "stale"})
    registry.touch_self("surface:9")
    m = json.loads(p.read_text())
    assert m["name"] == "sleeper"
    assert "status" not in m
    assert m["last_seen"] >= int(time.time()) - 5


def test_touch_self_noop_when_unregistered(tmp_registry):
    registry.touch_self("surface:42")  # must not raise, must not create file
    assert not registry.manifest_path("surface:42").exists()


def test_touch_self_noop_when_surface_unknown(tmp_registry):
    registry.touch_self(None)  # noqa


def test_register_collision_live(tmp_registry):
    p = registry.manifest_path("surface:1")
    _write(p, {"name": "alpha", "surface_ref": "surface:1",
               "started_at": 1, "last_seen": int(time.time())})
    m, err = registry.register("alpha", "surface:2",
                               live_set={"surface:1", "surface:2"})
    assert m is None
    assert err["kind"] == "name_collision"
    assert err["holder_surface"] == "surface:1"


def test_register_collision_stale(tmp_registry):
    p = registry.manifest_path("surface:1")
    old = int(time.time()) - registry.TTL_SECONDS - 60
    _write(p, {"name": "alpha", "surface_ref": "surface:1",
               "started_at": old, "last_seen": old})
    m, err = registry.register("alpha", "surface:2",
                               live_set={"surface:1", "surface:2"})
    assert m is None
    assert err["kind"] == "name_collision_stale"


def test_register_idempotent_for_self(tmp_registry):
    m1, _ = registry.register("solo", "surface:1",
                              live_set={"surface:1"})
    m2, err = registry.register("solo", "surface:1",
                                live_set={"surface:1"})
    assert err is None
    assert m2["name"] == m1["name"] == "solo"
    assert m2["last_seen"] >= m1["last_seen"]


def test_register_bad_name_format(tmp_registry):
    _, err = registry.register("Bad-Name", "surface:1",
                               live_set={"surface:1"})
    assert err["kind"] == "bad_name_format"
    _, err = registry.register("9starts", "surface:1",
                               live_set={"surface:1"})
    assert err["kind"] == "bad_name_format"


def test_register_not_in_cmux(tmp_registry):
    _, err = registry.register("ghost", "surface:999", live_set=set())
    assert err["kind"] == "not_in_cmux"


def test_corrupt_manifest_skip_not_unlink(tmp_registry, capsys):
    p = registry.manifest_path("surface:5")
    p.write_text("{ not valid json")
    # Sweep must skip without deleting the file.
    out = registry.all_manifests(live_set={"surface:5"})
    assert p.exists(), "corrupt files must be preserved, not unlinked"
    assert out == []
    err = capsys.readouterr().err
    assert "skipping corrupt manifest" in err


def _child_register(args):
    reg_path, name, surface_ref = args
    # Re-point registry to the shared tmp directory inside the child.
    from p2plib import registry as r
    from pathlib import Path
    r.REGISTRY = Path(reg_path)
    r.LOCK_PATH = Path(reg_path) / ".lock"
    return r.register(name, surface_ref,
                      live_set={"surface:1", "surface:2",
                                "surface:3", "surface:4"})


def test_concurrent_register_serializes(tmp_registry):
    """Two concurrent registers for the SAME name must serialize: only
    one wins, the other sees the existing manifest as a collision."""
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
    assert collisions[0][1]["kind"] == "name_collision"
