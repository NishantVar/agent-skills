import os
import subprocess

from cmux_observability.collector.git import commit_counts, productivity
from cmux_observability.config import Config, ProductivityConfig


def test_commit_counts_for_authorized_email(tmp_git_repo, fixed_now):
    counts = commit_counts(tmp_git_repo, authors=["alice@example.com"], now=fixed_now)
    assert counts["today"] == 1
    assert counts["week"] == 2
    assert counts["30d"] == 3


def test_commit_counts_excludes_non_authors(tmp_git_repo, fixed_now):
    """`git log --author` is a regex/email match. With multiple --author
    flags the semantics are OR; with a single author only that author's
    commits should be counted."""
    alice = commit_counts(tmp_git_repo, authors=["alice@example.com"], now=fixed_now)
    bob = commit_counts(tmp_git_repo, authors=["bob@example.com"], now=fixed_now)
    assert alice["week"] == 2          # alice: today + 3d ago
    assert bob["week"] == 1            # bob: 2d ago
    # Cross-author isolation: alice's window does not include bob's commit.
    assert alice["week"] + bob["week"] == 3


def test_commit_counts_empty_repo_returns_zeros(tmp_path, fixed_now):
    repo = tmp_path / "empty"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    counts = commit_counts(repo, authors=["alice@example.com"], now=fixed_now)
    assert counts == {"today": 0, "week": 0, "30d": 0}


def test_productivity_resolves_default_author_from_git_config(tmp_git_repo, fixed_now):
    cfg = Config(productivity=ProductivityConfig(
        repo_paths=[str(tmp_git_repo.parent)],
        exclude=[],
        author_emails=[],     # empty -> fall back to repo's git config
    ))
    prod = productivity([tmp_git_repo], cfg, now=fixed_now)
    assert prod.totals["today"] == 1
    assert prod.repos[0].path == str(tmp_git_repo)


def test_productivity_skips_repo_without_user_email(tmp_path, fixed_now):
    """When config has no explicit authors and the repo has no
    `git config user.email`, the repo is skipped (no commits counted).
    We do not invent a global author identity."""
    repo = tmp_path / "noauthor"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, capture_output=True)
    # Commit using env-only identity; do NOT run `git config user.email`.
    env = os.environ.copy()
    env["GIT_AUTHOR_EMAIL"] = "carol@example.com"
    env["GIT_AUTHOR_NAME"] = "Carol"
    env["GIT_COMMITTER_EMAIL"] = "carol@example.com"
    env["GIT_COMMITTER_NAME"] = "Carol"
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, env=env, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "carol"], cwd=repo, check=True, env=env, capture_output=True)

    cfg = Config(productivity=ProductivityConfig(
        repo_paths=[str(repo.parent)],
        exclude=[],
        author_emails=[],
    ))
    prod = productivity([repo], cfg, now=fixed_now)
    assert prod.repos == []
    assert prod.totals == {"today": 0, "week": 0, "30d": 0}
