"""Driver-side helper: age a p2p surface manifest's last_seen past TTL.

The p2p registry lives at ~/.cmux/agents/by-surface/<safe>.json. Aging
a manifest's last_seen forces p2p's sweep_locked to mark it status=stale
on the next read. Used only by the sim driver for the stale-manifest
disruption (sim spec §6 step 6). Scoped to manifests of sim-owned panes.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DEFAULT_REGISTRY = Path.home() / ".cmux" / "agents" / "by-surface"


def find_manifest_by_title(registry_dir: Path, title: str) -> Path | None:
    """Return the manifest file whose `title` field matches, or None."""
    if not registry_dir.exists():
        return None
    for path in registry_dir.glob("*.json"):
        try:
            rec = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if rec.get("title") == title:
            return path
    return None


def age_manifest(manifest_path: Path, *,
                 ttl_seconds: int = 1800,
                 margin_seconds: int = 60) -> None:
    """Rewrite manifest_path so last_seen is older than (now - ttl - margin)."""
    rec = json.loads(manifest_path.read_text())
    aged_ts = int(time.time()) - ttl_seconds - margin_seconds
    rec["last_seen"] = aged_ts
    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec))
    os.replace(tmp, manifest_path)
