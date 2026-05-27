import json
import subprocess
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
