import json
import time
from pathlib import Path

from lib.manifest_aging import age_manifest, find_manifest_by_title


def _write_manifest(dir_: Path, surface_ref: str, title: str,
                    last_seen: int | None = None) -> Path:
    safe = surface_ref.replace(":", "_")
    path = dir_ / f"{safe}.json"
    path.write_text(json.dumps({
        "surface_ref": surface_ref,
        "workspace_ref": "workspace:1",
        "title": title,
        "started_at": int(time.time()),
        "last_seen": last_seen if last_seen is not None else int(time.time()),
    }))
    return path


def test_age_manifest_sets_last_seen_past_ttl(tmp_path: Path):
    mpath = _write_manifest(tmp_path, "surface:5", "bravo_renamed")
    age_manifest(mpath, ttl_seconds=1800, margin_seconds=60)
    rec = json.loads(mpath.read_text())
    assert int(time.time()) - rec["last_seen"] > 1800


def test_find_manifest_by_title(tmp_path: Path):
    _write_manifest(tmp_path, "surface:5", "bravo_renamed")
    _write_manifest(tmp_path, "surface:6", "worker_alpha")
    p = find_manifest_by_title(tmp_path, "bravo_renamed")
    assert p is not None
    rec = json.loads(p.read_text())
    assert rec["surface_ref"] == "surface:5"


def test_find_manifest_by_title_returns_none_when_missing(tmp_path: Path):
    _write_manifest(tmp_path, "surface:5", "bravo_renamed")
    assert find_manifest_by_title(tmp_path, "worker_delta") is None
