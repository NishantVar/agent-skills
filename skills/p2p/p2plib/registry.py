"""Per-surface manifest registry.

One JSON file per surface at REGISTRY/<safe_surface_ref>.json. All
mutating operations run under an fcntl exclusive lock on REGISTRY/.lock
so concurrent agents serialize.

Manifest shape:
    {surface_ref, workspace_ref, title, started_at, last_seen, status?}

`title` is the cmux tab title at registration time and the single
routing identifier. (workspace_ref, title) is the unique routing key;
collisions are rejected at register-time via title_collision.

Sweep behavior:
  - surface_ref absent from `cmux tree --all` -> delete file (eager).
  - surface live but `last_seen` older than TTL -> mark status="stale",
    keep file (title stays held; agent can revive by touching).
  - surface live but the surface's CURRENT cmux title no longer matches
    manifest.title (user renamed the tab outside of p2p) -> in-place
    rewrite: set `title` to the current cmux title and append the
    prior title to `former_titles` (creating the list if absent). The
    manifest is NOT reaped; the rename history powers the
    `peer_renamed` handoff so peers addressing the old title get a
    bridge to the new one (resolve.py scans former_titles on miss).

Legacy compatibility: manifests written by the old `name`-based code
are read transparently — a missing `title` field falls back to `name`.
New writes never emit `name`.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import sys
import time
from pathlib import Path

REGISTRY = Path.home() / ".cmux" / "agents" / "by-surface"
LOCK_PATH = REGISTRY / ".lock"
TTL_SECONDS = 30 * 60


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
    not a stale signal). Logs to stderr and skips.

    Legacy `name` field is promoted to `title` in the returned dict
    (does not rewrite the file)."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return None
    except OSError as exc:
        print(f"warning: cannot read {path}: {exc}", file=sys.stderr)
        return None
    try:
        m = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"warning: skipping corrupt manifest {path}: {exc}",
              file=sys.stderr)
        return None
    if "title" not in m and "name" in m:
        m["title"] = m["name"]
    return m


def _iter_manifest_files():
    if not REGISTRY.exists():
        return
    for path in REGISTRY.glob("*.json"):
        yield path


def sweep_locked(live_set: set[str], surfaces: dict[str, dict] | None = None,
                 now: float | None = None) -> list[dict]:
    """Sweep inside the lock. Returns the post-sweep manifest list.

    When `surfaces` is supplied (surface_index map) and the surface's
    current cmux title differs from `manifest.title`, the manifest is
    rewritten in place: `title` becomes the current cmux title and the
    prior title is appended to `former_titles`. The manifest is NOT
    unlinked — the rename history is what powers `peer_renamed`.

    Empty current titles (`""`) are ignored — they're a surface_index
    miss, not a real rename. Don't clobber a registered title with "".
    """
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
        mutated = False
        if surfaces is not None:
            surf = surfaces.get(ref) or {}
            current_title = surf.get("title", "")
            # Legacy-manifest promotion: pre-refactor manifests carry
            # only `name`+`surface_ref`+`started_at`. Fill in workspace_ref
            # from the live surface index so the resolver's
            # workspace-scoped former_titles scan can see this manifest.
            # Without this, legacy renamed surfaces silently fail
            # peer_renamed detection. We also drop the legacy `name`
            # field once `title` is in place — single-identifier refactor.
            if "workspace_ref" not in m:
                ws_ref = surf.get("workspace_ref")
                if ws_ref:
                    m["workspace_ref"] = ws_ref
                    mutated = True
            if "title" not in m and "name" in m:
                m["title"] = m["name"]
                mutated = True
            if "name" in m and m.get("title"):
                m.pop("name", None)
                mutated = True
            if current_title and current_title != m.get("title"):
                # Tab renamed outside p2p. Promote rename into the
                # manifest so peer_renamed can bridge addressers of
                # the prior title to the new one.
                former = list(m.get("former_titles") or [])
                old_title = m.get("title")
                if old_title and old_title not in former:
                    former.append(old_title)
                m["title"] = current_title
                m["former_titles"] = former
                mutated = True
        last_seen = m.get("last_seen") or m.get("started_at") or 0
        if now - last_seen > TTL_SECONDS:
            if m.get("status") != "stale":
                m["status"] = "stale"
                mutated = True
        else:
            if m.get("status") == "stale":
                m.pop("status", None)
                mutated = True
        if mutated:
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


def register(title: str, surface_ref: str, workspace_ref: str | None,
             live_set: set[str],
             surfaces: dict[str, dict] | None = None
             ) -> tuple[dict | None, dict | None]:
    """Register `title` for `surface_ref`. Returns (manifest, error).

    Error is a dict with kind="title_collision" | "not_in_cmux", or
    None on success. The caller wraps it into the handoff JSON.

    Collision is scoped to (workspace_ref, title): two tabs in
    different workspaces can share a title.
    """
    if surface_ref not in live_set:
        return None, {"kind": "not_in_cmux", "surface": surface_ref}

    with registry_lock():
        # Sweep first so we make decisions against fresh state. Pass
        # surfaces so renamed-outside-p2p manifests get reaped before
        # we collision-check.
        manifests = sweep_locked(live_set, surfaces=surfaces)
        for m in manifests:
            if m.get("title") != title:
                continue
            if m.get("workspace_ref") != workspace_ref:
                # Same title in a different workspace is fine.
                continue
            if m.get("surface_ref") == surface_ref:
                # Already ours — refresh in place.
                m["last_seen"] = int(time.time())
                m.pop("status", None)
                _atomic_write(manifest_path(surface_ref), m)
                return m, None
            return None, {"kind": "title_collision", "title": title,
                          "workspace_ref": workspace_ref,
                          "holder_surface": m.get("surface_ref")}
        now = int(time.time())
        data = {
            "title": title,
            "surface_ref": surface_ref,
            "workspace_ref": workspace_ref,
            "started_at": now,
            "last_seen": now,
        }
        _atomic_write(manifest_path(surface_ref), data)
        return data, None


def all_manifests(live_set: set[str],
                  surfaces: dict[str, dict] | None = None) -> list[dict]:
    """Convenience: take the lock, sweep, return post-sweep manifests."""
    with registry_lock():
        return sweep_locked(live_set, surfaces=surfaces)


def would_collide(title: str, surface_ref: str,
                  workspace_ref: str | None,
                  live_set: set[str],
                  surfaces: dict[str, dict] | None = None) -> str | None:
    """Probe whether `register(title, surface_ref, workspace_ref)` would
    fail with title_collision. Returns the holder's surface_ref on
    conflict, or None if `register` would succeed.

    Mirrors the (workspace_ref, title) check inside `register` but does
    NOT create a manifest for `title`. It does run a normal sweep
    (same as every other lock-taking operation), so it may write
    stale-status changes, legacy promotions, and rename promotions to
    OTHER manifests — that's expected for any caller already on this
    code path. A future caller that needs a pure side-effect-free
    probe would need a non-mutating sweep helper.

    Note: there's a brief TOCTOU window between this probe and a
    subsequent `register` call — another agent could claim the title
    in between. The collision check inside `register` is the
    authoritative backstop; this probe only avoids the common
    already-held case. Callers performing other side effects (e.g.,
    cmux tab rename) between the probe and `register` must roll those
    side effects back if `register` later returns title_collision.
    """
    with registry_lock():
        manifests = sweep_locked(live_set, surfaces=surfaces)
        for m in manifests:
            if m.get("title") != title:
                continue
            if m.get("workspace_ref") != workspace_ref:
                continue
            if m.get("surface_ref") == surface_ref:
                continue  # our own existing manifest, not a conflict
            return m.get("surface_ref")
        return None
