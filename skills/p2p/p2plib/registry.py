"""Per-surface manifest registry.

One JSON file per surface at REGISTRY/<safe_surface_ref>.json. All
mutating operations run under an fcntl exclusive lock on REGISTRY/.lock
so concurrent agents serialize.

Two-tier staleness:
  - surface_ref absent from `cmux tree --all` -> delete file (eager).
  - surface live but `last_seen` older than TTL -> mark status="stale",
    keep file (name stays held; agent can revive by touching).

`touch_self` is the heartbeat: any CLI invocation calls it once at
startup. It writes `last_seen=now`, clears `status: stale` if present,
and is a no-op when the agent isn't registered yet.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import sys
import time
from pathlib import Path

REGISTRY = Path.home() / ".cmux" / "agents" / "by-surface"
LOCK_PATH = REGISTRY / ".lock"
TTL_SECONDS = 30 * 60
NAME_RE = re.compile(r"[a-z][a-z0-9_]*")


def _ensure_registry() -> None:
    REGISTRY.mkdir(parents=True, exist_ok=True)


def manifest_path(surface_ref: str) -> Path:
    safe = surface_ref.replace(":", "_")
    return REGISTRY / f"{safe}.json"


@contextlib.contextmanager
def registry_lock():
    _ensure_registry()
    LOCK_PATH.touch(exist_ok=True)
    fd = os.open(str(LOCK_PATH), os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    payload = json.dumps(data, indent=2)
    with open(tmp, "w") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _read_manifest(path: Path) -> dict | None:
    """Read one manifest file. Returns None on missing/corrupt — does
    NOT unlink corrupt files (that's an atomic-write violation signal,
    not a stale signal). Logs to stderr and skips."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return None
    except OSError as exc:
        print(f"warning: cannot read {path}: {exc}", file=sys.stderr)
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"warning: skipping corrupt manifest {path}: {exc}",
              file=sys.stderr)
        return None


def _iter_manifest_files():
    if not REGISTRY.exists():
        return
    for path in REGISTRY.glob("*.json"):
        yield path


def sweep_locked(live_set: set[str], now: float | None = None) -> list[dict]:
    """Two-tier sweep inside the lock. Returns the post-sweep manifest list."""
    now = time.time() if now is None else now
    survivors: list[dict] = []
    for path in list(_iter_manifest_files()):
        m = _read_manifest(path)
        if m is None:
            continue
        ref = m.get("surface_ref")
        if not ref or ref not in live_set:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            continue
        last_seen = m.get("last_seen") or m.get("started_at") or 0
        if now - last_seen > TTL_SECONDS:
            if m.get("status") != "stale":
                m["status"] = "stale"
                _atomic_write(path, m)
        else:
            if m.get("status") == "stale":
                m.pop("status", None)
                _atomic_write(path, m)
        survivors.append(m)
    return survivors


def touch_self(surface_ref: str | None) -> None:
    """Heartbeat. Idempotent. No-op when not registered or no surface.

    Revives status=stale in place by clearing the field; bumps
    last_seen. Never creates a manifest.
    """
    if not surface_ref:
        return
    path = manifest_path(surface_ref)
    with registry_lock():
        if not path.exists():
            return
        m = _read_manifest(path)
        if m is None:
            return
        m["last_seen"] = int(time.time())
        if m.get("status") == "stale":
            m.pop("status", None)
        _atomic_write(path, m)


def get_self(surface_ref: str | None) -> dict | None:
    if not surface_ref:
        return None
    path = manifest_path(surface_ref)
    if not path.exists():
        return None
    return _read_manifest(path)


def register(name: str, surface_ref: str,
             live_set: set[str]) -> tuple[dict | None, dict | None]:
    """Register `name` for `surface_ref`. Returns (manifest, error).

    Error is a dict with kind="bad_name_format" | "name_collision" |
    "name_collision_stale" | "not_in_cmux", or None on success. The
    caller wraps it into the handoff JSON.
    """
    if not NAME_RE.fullmatch(name):
        return None, {"kind": "bad_name_format", "name": name}
    if surface_ref not in live_set:
        return None, {"kind": "not_in_cmux", "surface": surface_ref}

    with registry_lock():
        # Sweep first so we make decisions against fresh state.
        manifests = sweep_locked(live_set)
        for m in manifests:
            if m.get("name") != name:
                continue
            if m.get("surface_ref") == surface_ref:
                # Already ours — refresh in place.
                m["last_seen"] = int(time.time())
                m.pop("status", None)
                _atomic_write(manifest_path(surface_ref), m)
                return m, None
            kind = ("name_collision_stale"
                    if m.get("status") == "stale" else "name_collision")
            return None, {"kind": kind, "name": name,
                          "holder_surface": m.get("surface_ref")}
        now = int(time.time())
        data = {
            "name": name,
            "surface_ref": surface_ref,
            "started_at": now,
            "last_seen": now,
        }
        _atomic_write(manifest_path(surface_ref), data)
        return data, None


def all_manifests(live_set: set[str]) -> list[dict]:
    """Convenience: take the lock, sweep, return post-sweep manifests."""
    with registry_lock():
        return sweep_locked(live_set)
