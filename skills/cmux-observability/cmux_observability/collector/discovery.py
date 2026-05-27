"""$HOME-wide repo discovery.

Authoritative source: a deterministic `find` scanner with prune rules.
macOS `mdfind` may seed/accelerate, but Spotlight is never authoritative
because it can skip hidden folders or have partial indexes.

Cache: JSON file with `generated_at`, `mdfind_used`, `repos`. TTL controlled
by `DiscoveryConfig.cache_ttl_seconds`. `--rescan` (CLI) deletes the file.
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from ..config import Config
from ..errors import Failure


_HARD_PRUNES = (
    "node_modules", ".venv", "venv", ".cache", "Library", ".Trash",
    ".npm", ".cargo", ".pnpm", ".pyenv", "target", "build", "dist",
)


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()


def _cache_path(cfg: Config) -> Path:
    return _expand(cfg.discovery.cache_path)


def _cache_fresh(path: Path, ttl: int) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < ttl


def _load_cache(path: Path) -> list[Path]:
    data = json.loads(path.read_text())
    return [Path(p) for p in data.get("repos", [])]


def _save_cache(path: Path, repos: list[Path], mdfind_used: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "generated_at": time.time(),
        "mdfind_used": mdfind_used,
        "repos": [str(r) for r in repos],
    }, indent=2))


def _run_mdfind_seed() -> list[Path]:
    if sys.platform != "darwin":
        return []
    try:
        cp = subprocess.run(
            ["mdfind", 'kMDItemFSName == ".git"'],
            check=False, text=True, capture_output=True,
        )
    except FileNotFoundError:
        return []
    if cp.returncode != 0:
        return []
    out: list[Path] = []
    for line in cp.stdout.splitlines():
        line = line.strip()
        if line:
            out.append(Path(line))
    return out


def _run_find_scan(root: Path, max_depth: int) -> list[Path]:
    """Run `find <root> -maxdepth N -type d ( prunes ) -prune -o ( -name .git ) -print`.

    Returns `.git` directories AND `.git` files (worktree pointers)."""
    prune_args: list[str] = []
    for i, name in enumerate(_HARD_PRUNES):
        if i:
            prune_args.append("-o")
        prune_args += ["-name", name]

    cmd = [
        "find", str(root),
        "-maxdepth", str(max_depth),
        "(", "-type", "d", "(", *prune_args, ")", "-prune", ")",
        "-o", "(", "-name", ".git", ")", "-print",
    ]
    try:
        cp = subprocess.run(cmd, check=False, text=True, capture_output=True)
    except FileNotFoundError:
        return []
    return [Path(line) for line in cp.stdout.splitlines() if line.strip()]


def _excluded(path: Path, patterns: list[str]) -> bool:
    s = str(path)
    return any(fnmatch.fnmatch(s, os.path.expanduser(p)) for p in patterns)


def _normalize_via_rev_parse(dot_git: Path) -> tuple[Path | None, str | None]:
    """Given a `.git` path (file or dir), return the working-tree top via
    `git -C <parent> rev-parse --show-toplevel`. Returns (None, err) on failure."""
    parent = dot_git.parent
    try:
        cp = subprocess.run(
            ["git", "-C", str(parent), "rev-parse", "--show-toplevel"],
            check=False, text=True, capture_output=True,
        )
    except FileNotFoundError as e:
        return None, str(e)
    if cp.returncode != 0:
        return None, cp.stderr.strip() or f"exit {cp.returncode}"
    out = cp.stdout.strip()
    return (Path(out) if out else None), None


def discover_repos(
    cfg: Config, force_rescan: bool = False,
) -> tuple[list[Path], list[Failure]]:
    failures: list[Failure] = []
    cache = _cache_path(cfg)

    if not force_rescan and _cache_fresh(cache, cfg.discovery.cache_ttl_seconds):
        return _load_cache(cache), failures

    candidates: set[Path] = set()
    mdfind_used = False
    if cfg.discovery.use_mdfind_seed and sys.platform == "darwin":
        seeded = _run_mdfind_seed()
        if seeded:
            mdfind_used = True
            candidates.update(seeded)

    for root_str in cfg.productivity.repo_paths:
        root = _expand(root_str)
        if not root.exists():
            failures.append(Failure(
                component="discovery", target=str(root),
                message="root does not exist",
            ))
            continue
        candidates.update(_run_find_scan(root, cfg.discovery.max_depth))

    repos: set[Path] = set()
    for c in candidates:
        if _excluded(c, cfg.productivity.exclude):
            continue
        toplevel, err = _normalize_via_rev_parse(c)
        if toplevel is None:
            failures.append(Failure(
                component="discovery", target=str(c),
                message=err or "rev-parse failed",
            ))
            continue
        # exclude can also match the resolved toplevel
        if _excluded(toplevel, cfg.productivity.exclude):
            continue
        repos.add(toplevel.resolve())

    out = sorted(repos)
    _save_cache(cache, out, mdfind_used)
    return out, failures
