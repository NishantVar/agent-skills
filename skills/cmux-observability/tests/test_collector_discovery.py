import json
import subprocess
import sys
import time
from pathlib import Path

from cmux_observability.collector.discovery import discover_repos
from cmux_observability.config import Config, DiscoveryConfig, ProductivityConfig


def _mk_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, capture_output=True)


def _mk_worktree_pointer(at: Path, real_repo: Path) -> None:
    """Simulate a worktree: `at/.git` is a file pointing into the real repo."""
    at.mkdir(parents=True)
    (at / ".git").write_text(f"gitdir: {real_repo / '.git' / 'worktrees' / 'wt'}\n")
    (real_repo / ".git" / "worktrees" / "wt").mkdir(parents=True)
    (real_repo / ".git" / "worktrees" / "wt" / "commondir").write_text("../..\n")
    (real_repo / ".git" / "worktrees" / "wt" / "gitdir").write_text(str(at / ".git") + "\n")
    (real_repo / ".git" / "worktrees" / "wt" / "HEAD").write_text("ref: refs/heads/wt\n")


def _cfg(home: Path, **overrides) -> Config:
    return Config(
        productivity=ProductivityConfig(
            repo_paths=[str(home)],
            exclude=overrides.get("exclude", []),
            author_emails=[],
        ),
        discovery=DiscoveryConfig(
            use_mdfind_seed=False,    # tests stay deterministic
            max_depth=6,
            cache_ttl_seconds=3600,
            cache_path=str(home / ".local" / "share" / "cmux-observability" / "repo_discovery.json"),
        ),
        summarizer=None,
        render=None,
    )


def test_discovery_cache_hit_skips_find_scanner(tmp_home, monkeypatch):
    cache_path = tmp_home / ".local" / "share" / "cmux-observability" / "repo_discovery.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "generated_at": time.time(),
        "mdfind_used": False,
        "inputs": {
            "repo_paths": [str(tmp_home)],
            "exclude": [],
            "max_depth": 6,
            "use_mdfind_seed": False,
        },
        "repos": [str(tmp_home / "fake_repo")],
    }))

    calls: list = []
    import cmux_observability.collector.discovery as discovery_mod
    monkeypatch.setattr(
        discovery_mod, "_run_find_scan", lambda *a, **kw: calls.append(("find", a, kw)) or [],
    )

    repos, failures = discover_repos(_cfg(tmp_home))
    assert calls == []                           # find scanner never invoked
    assert repos == [Path(str(tmp_home / "fake_repo"))]
    assert failures == []


def test_discovery_prunes_excluded_dirs(tmp_home):
    real = tmp_home / "projects" / "good"
    _mk_repo(real)
    _mk_repo(tmp_home / "Library" / "Caches" / "should_skip")
    _mk_repo(tmp_home / "node_modules" / "x" / "should_skip")
    _mk_repo(tmp_home / ".cache" / "z" / "should_skip")

    repos, failures = discover_repos(_cfg(tmp_home))
    assert real.resolve() in [r.resolve() for r in repos]
    for skip_dir_name in ("Library", "node_modules", ".cache"):
        bad = [r for r in repos if skip_dir_name in r.parts]
        assert bad == [], f"unexpected repo under pruned {skip_dir_name}: {bad}"


def test_discovery_handles_dot_git_file_worktrees(tmp_home):
    real = tmp_home / "projects" / "main_repo"
    _mk_repo(real)
    wt = tmp_home / "projects" / "feature_worktree"
    _mk_worktree_pointer(wt, real)

    repos, failures = discover_repos(_cfg(tmp_home))
    refs = {str(r) for r in repos}
    assert str(real.resolve()) in refs or str(real) in refs
    # The worktree's toplevel resolves to itself, not to `real`.
    assert any("feature_worktree" in str(r) for r in repos)


def test_mdfind_seed_outside_configured_roots_is_ignored(tmp_home, monkeypatch):
    inside_root = tmp_home / "projects"
    inside_repo = inside_root / "inside"
    _mk_repo(inside_repo)
    outside_repo = tmp_home / "elsewhere" / "outside"
    _mk_repo(outside_repo)

    import cmux_observability.collector.discovery as discovery_mod
    monkeypatch.setattr(sys, "platform", "darwin")
    # mdfind reports both inside-root and outside-root .git paths
    monkeypatch.setattr(
        discovery_mod, "_run_mdfind_seed",
        lambda: [inside_repo / ".git", outside_repo / ".git"],
    )
    # Disable the find scanner so mdfind is the only candidate source.
    monkeypatch.setattr(
        discovery_mod, "_run_find_scan", lambda root, depth: [],
    )

    cfg = Config(
        productivity=ProductivityConfig(
            repo_paths=[str(inside_root)],
            exclude=[],
            author_emails=[],
        ),
        discovery=DiscoveryConfig(
            use_mdfind_seed=True,
            max_depth=6,
            cache_ttl_seconds=3600,
            cache_path=str(tmp_home / ".local" / "share" / "cmux-observability" / "repo_discovery.json"),
        ),
        summarizer=None,
        render=None,
    )
    repos, failures = discover_repos(cfg)
    refs = [r.resolve() for r in repos]
    assert inside_repo.resolve() in refs
    assert outside_repo.resolve() not in refs


def test_cache_with_mismatched_inputs_triggers_rescan(tmp_home, monkeypatch):
    cache_path = tmp_home / ".local" / "share" / "cmux-observability" / "repo_discovery.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "generated_at": time.time(),
        "mdfind_used": False,
        "inputs": {
            "repo_paths": [str(tmp_home / "different_root")],
            "exclude": [],
            "max_depth": 6,
            "use_mdfind_seed": False,
        },
        "repos": [str(tmp_home / "cached_only")],
    }))

    calls: list = []
    import cmux_observability.collector.discovery as discovery_mod
    monkeypatch.setattr(
        discovery_mod, "_run_find_scan",
        lambda root, depth: calls.append((str(root), depth)) or [],
    )

    repos, failures = discover_repos(_cfg(tmp_home))
    assert calls != [], "find scanner should run when cached inputs do not match"
    assert all("cached_only" not in str(r) for r in repos)


def test_discovery_bad_dot_git_file_records_failure(tmp_home):
    """A `.git` file with an invalid `gitdir:` payload must NOT appear in
    `repos` and MUST produce a non-fatal `Failure(component='discovery')`
    targeted at the bad `.git` path. A sibling valid repo in the same scan
    must still surface — failure isolation, not scan abort.
    """
    good = tmp_home / "projects" / "good_repo"
    _mk_repo(good)

    bad_parent = tmp_home / "projects" / "bogus_worktree"
    bad_parent.mkdir(parents=True)
    bad_git = bad_parent / ".git"
    bad_git.write_text("gitdir: /nonexistent/path/that/cannot/resolve\n")

    repos, failures = discover_repos(_cfg(tmp_home))

    # Good repo still surfaces.
    assert any("good_repo" in str(r) for r in repos), repos
    # Bad candidate is not in repos.
    assert not any("bogus_worktree" in str(r) for r in repos), repos
    # Exactly one discovery Failure targeted at the bad .git path.
    bad_failures = [
        f for f in failures
        if f.component == "discovery" and str(bad_git) in (f.target or "")
    ]
    assert len(bad_failures) == 1, failures


def test_discovery_mdfind_seed_under_hard_pruned_dir_is_excluded(tmp_home, monkeypatch):
    """`mdfind` seed candidates whose path contains a `_HARD_PRUNES`
    component (e.g. `Library/`, `node_modules/`) must be dropped before
    reaching `rev-parse`, matching the `find`-scanner's `-prune`
    behavior. No repo under such a directory may appear in `repos`, and
    no `Failure` is emitted for the silently-skipped candidate (hard
    prunes are a normal filter, not an error).
    """
    pruned_repo = tmp_home / "Library" / "Application Support" / "leaky_repo"
    _mk_repo(pruned_repo)

    import cmux_observability.collector.discovery as discovery_mod
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        discovery_mod, "_run_mdfind_seed",
        lambda: [pruned_repo / ".git"],
    )
    # Disable the find scanner so mdfind is the only candidate source —
    # isolates the mdfind contract from `find`'s prune behavior.
    monkeypatch.setattr(
        discovery_mod, "_run_find_scan", lambda root, depth: [],
    )

    cfg = Config(
        productivity=ProductivityConfig(
            repo_paths=[str(tmp_home)],
            exclude=[],                        # user did NOT exclude Library
            author_emails=[],
        ),
        discovery=DiscoveryConfig(
            use_mdfind_seed=True,
            max_depth=6,
            cache_ttl_seconds=3600,
            cache_path=str(tmp_home / ".local" / "share" / "cmux-observability" / "repo_discovery.json"),
        ),
        summarizer=None,
        render=None,
    )
    repos, failures = discover_repos(cfg)
    assert not any("Library" in r.parts for r in repos), repos
    # Hard-prune skip is a normal filter, not a discovery failure.
    assert not any(
        f.component == "discovery" and "Library" in (f.target or "")
        for f in failures
    ), failures


def test_cache_with_stale_generated_at_triggers_rescan(tmp_home, monkeypatch):
    cache_path = tmp_home / ".local" / "share" / "cmux-observability" / "repo_discovery.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    # generated_at is well outside the 3600-second TTL even though the
    # file mtime is fresh (we just wrote it).
    cache_path.write_text(json.dumps({
        "generated_at": time.time() - 100000,
        "mdfind_used": False,
        "inputs": {
            "repo_paths": [str(tmp_home)],
            "exclude": [],
            "max_depth": 6,
            "use_mdfind_seed": False,
        },
        "repos": [str(tmp_home / "stale_only")],
    }))

    calls: list = []
    import cmux_observability.collector.discovery as discovery_mod
    monkeypatch.setattr(
        discovery_mod, "_run_find_scan",
        lambda root, depth: calls.append((str(root), depth)) or [],
    )

    repos, failures = discover_repos(_cfg(tmp_home))
    assert calls != [], "find scanner should run when generated_at is past TTL"
    assert all("stale_only" not in str(r) for r in repos)
