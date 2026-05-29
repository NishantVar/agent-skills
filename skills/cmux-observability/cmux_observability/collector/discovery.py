"""$HOME-wide repo discovery.

Authoritative source: a deterministic `find` scanner with prune rules.
macOS `mdfind` may seed/accelerate, but Spotlight is never authoritative
because it can skip hidden folders or have partial indexes.

Cache: JSON file with `generated_at`, `mdfind_used`, `inputs`, `repos`. The
`inputs` block fingerprints the discovery config so a cache produced for
different `repo_paths` / `exclude` / `max_depth` / `use_mdfind_seed` is not
reused. TTL controlled by `DiscoveryConfig.cache_ttl_seconds`, evaluated
against the stored `generated_at` (not file mtime). `--rescan` (CLI) deletes
the file.
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


def _inputs_fingerprint(cfg: Config) -> dict:
    return {
        "repo_paths": list(cfg.productivity.repo_paths),
        "exclude": list(cfg.productivity.exclude),
        "max_depth": cfg.discovery.max_depth,
        "use_mdfind_seed": cfg.discovery.use_mdfind_seed,
    }


def _load_cache_if_valid(path: Path, cfg: Config) -> list[Path] | None:
    """Return cached repo paths only if the cache file exists, is well-formed
    JSON, carries an `inputs` block that matches the current config, and its
    `generated_at` is within `cache_ttl_seconds`. Otherwise return None so the
    caller rescans."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    generated_at = data.get("generated_at")
    if not isinstance(generated_at, (int, float)):
        return None
    if (time.time() - generated_at) >= cfg.discovery.cache_ttl_seconds:
        return None
    if data.get("inputs") != _inputs_fingerprint(cfg):
        return None
    repos = data.get("repos")
    if not isinstance(repos, list):
        return None
    return [Path(p) for p in repos]


def _save_cache(path: Path, repos: list[Path], mdfind_used: bool, cfg: Config) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "generated_at": time.time(),
        "mdfind_used": mdfind_used,
        "inputs": _inputs_fingerprint(cfg),
        "repos": [str(r) for r in repos],
    }, indent=2))


def _is_under(path: Path, roots: list[Path]) -> bool:
    """True iff `path` (after best-effort resolve) lies under any of `roots`."""
    try:
        rp = path.resolve()
    except (OSError, RuntimeError):
        rp = path
    for r in roots:
        try:
            rp.relative_to(r)
            return True
        except ValueError:
            continue
    return False


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


def _has_hard_prune_component(path: Path) -> bool:
    """True iff any component of `path` matches a `_HARD_PRUNES` entry.

    The `find`-scanner's `-prune` argv already drops these directories at
    the source. This helper applies the same filter to `mdfind` seed
    candidates and to post-`rev-parse` toplevels so the two discovery
    branches yield the same set of repos.
    """
    return any(part in _HARD_PRUNES for part in path.parts)


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

    if not force_rescan:
        cached = _load_cache_if_valid(cache, cfg)
        if cached is not None:
            return cached, failures

    allowed_roots = [_expand(p) for p in cfg.productivity.repo_paths]

    candidates: set[Path] = set()
    mdfind_used = False
    if cfg.discovery.use_mdfind_seed and sys.platform == "darwin":
        seeded = _run_mdfind_seed()
        if seeded:
            mdfind_used = True
            for s in seeded:
                if _is_under(s, allowed_roots) and not _has_hard_prune_component(s):
                    candidates.add(s)

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
        if _excluded(toplevel, cfg.productivity.exclude):
            continue
        if not _is_under(toplevel, allowed_roots):
            continue
        if _has_hard_prune_component(toplevel):
            continue
        repos.add(toplevel.resolve())

    out = sorted(repos)
    _save_cache(cache, out, mdfind_used, cfg)
    return out, failures
