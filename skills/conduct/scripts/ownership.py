"""Ownership manifest — UUID-keyed, advisory-locked.

Manifest lives at ``~/.conduct/owners.json``:

    { target_uuid: { "owner_uuid": ..., "claimed_at": <iso8601> } }

Implements the implicit first-touch / exclusive / orphan-reclaim algorithm
(spec §3.3), run on EVERY verb (status included). The whole read-decide-write
runs under an advisory file lock (``fcntl.flock`` on a sidecar ``.lock`` file)
so two concurrent first-touches cannot both win.

``resolve_ownership`` is the one decision function. It returns a small result
object the caller acts on; it never touches cmux directly — the live UUID set
is passed in by the caller (which owns the cmux seam).
"""

from __future__ import annotations

import datetime
import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

CONDUCT_DIR = Path(os.path.expanduser("~")) / ".conduct"
MANIFEST_PATH = CONDUCT_DIR / "owners.json"
LOCK_PATH = CONDUCT_DIR / "owners.lock"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _ensure_dir() -> None:
    CONDUCT_DIR.mkdir(parents=True, exist_ok=True)


@contextmanager
def manifest_lock(path: Optional[Path] = None):
    """Advisory exclusive lock guarding the whole read-decide-write cycle.
    Resolves the lock path at call time so tests can repoint the manifest."""
    path = LOCK_PATH if path is None else path
    _ensure_dir()
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def load(path: Optional[Path] = None) -> dict:
    path = MANIFEST_PATH if path is None else path
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(manifest: dict, path: Optional[Path] = None) -> None:
    path = MANIFEST_PATH if path is None else path
    _ensure_dir()
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)  # atomic within the lock


class OwnershipResult:
    """Outcome of a first-touch decision.

    status: "claimed" | "already_mine" | "reclaimed" | "owned_by_other"
    owner:  the current owner UUID (the OTHER owner when owned_by_other).
    """

    def __init__(self, status: str, owner: Optional[str]):
        self.status = status
        self.owner = owner

    @property
    def ok(self) -> bool:
        return self.status != "owned_by_other"


def resolve_ownership(target_uuid: str, caller_uuid: str,
                      live_uuids: set,
                      manifest: dict) -> OwnershipResult:
    """The first-touch algorithm (spec §3.3). MUTATES ``manifest`` in place on a
    claim/reclaim; the caller persists it. Must run under ``manifest_lock``.

    - unowned OR owner orphaned (owner ∉ live tree) -> first-touch CLAIM.
    - already mine -> pass.
    - live-owned by someone else -> owned_by_other (fail closed, no steal).
    """
    entry = manifest.get(target_uuid)
    if entry is None:
        manifest[target_uuid] = {"owner_uuid": caller_uuid,
                                 "claimed_at": _now_iso()}
        return OwnershipResult("claimed", caller_uuid)

    owner = entry.get("owner_uuid")
    if owner not in live_uuids:  # recorded owner's pane is gone -> stale
        manifest[target_uuid] = {"owner_uuid": caller_uuid,
                                 "claimed_at": _now_iso()}
        return OwnershipResult("reclaimed", caller_uuid)

    if owner == caller_uuid:
        return OwnershipResult("already_mine", caller_uuid)

    return OwnershipResult("owned_by_other", owner)


def release(target_uuid: str, caller_uuid: str, live_uuids: set,
            manifest: dict) -> OwnershipResult:
    """Drop the caller's claim on ``target_uuid``. Only the current owner (or a
    caller reclaiming an orphan) may release. MUTATES ``manifest``.

    status: "released" | "not_owned" (nothing to drop) | "owned_by_other".
    """
    entry = manifest.get(target_uuid)
    if entry is None:
        return OwnershipResult("not_owned", None)
    owner = entry.get("owner_uuid")
    if owner == caller_uuid or owner not in live_uuids:
        del manifest[target_uuid]
        return OwnershipResult("released", caller_uuid)
    return OwnershipResult("owned_by_other", owner)


def owned_targets(caller_uuid: str, live_uuids: set,
                  manifest: dict) -> list:
    """The caller's owned set among LIVE surfaces — the universe for `--all`
    and `status --all` (spec §4). Orphaned-owner entries are ignored live."""
    out = []
    for target_uuid, entry in manifest.items():
        if target_uuid not in live_uuids:
            continue  # dead target — not in the live owned set
        owner = entry.get("owner_uuid")
        if owner == caller_uuid and owner in live_uuids:
            out.append(target_uuid)
    return out
