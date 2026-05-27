"""Git commit counting per repo, per time window."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from ..config import Config
from ..model import Productivity, RepoStats


_WINDOWS = ("today", "week", "30d")


def _window_start(window: str, now: datetime) -> datetime:
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if window == "today":
        return midnight
    if window == "week":
        return midnight - timedelta(days=7)
    if window == "30d":
        return midnight - timedelta(days=30)
    raise ValueError(f"unknown window: {window!r}")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False, text=True, capture_output=True,
    )


def _resolve_default_authors(repo: Path) -> list[str]:
    """Read repo-local `user.email`. Returns [] if the repo has no per-repo
    identity — the caller skips the repo rather than inventing a global
    author (Reviewer T6 instruction #3)."""
    cp = _git(repo, "config", "--local", "user.email")
    email = cp.stdout.strip()
    return [email] if email else []


def commit_counts(
    repo: Path, authors: list[str], *, now: datetime | None = None,
) -> dict[str, int]:
    now = now or datetime.now()
    counts: dict[str, int] = {}
    for w in _WINDOWS:
        start = _window_start(w, now)
        args = ["log", f"--since-as-filter={start.isoformat()}", "--pretty=oneline"]
        # `git log --author` accepts repeated flags with OR semantics.
        for a in authors:
            args.extend(["--author", a])
        cp = _git(repo, *args)
        if cp.returncode != 0:
            counts[w] = 0
            continue
        counts[w] = sum(1 for line in cp.stdout.splitlines() if line.strip())
    return counts


def _last_commit_at(repo: Path) -> datetime | None:
    cp = _git(repo, "log", "-1", "--pretty=%cI")
    if cp.returncode != 0:
        return None
    line = cp.stdout.strip()
    if not line:
        return None
    try:
        return datetime.fromisoformat(line)
    except ValueError:
        return None


def productivity(
    repos: list[Path], cfg: Config, *, now: datetime | None = None,
) -> Productivity:
    authors = list(cfg.productivity.author_emails)
    repo_stats: list[RepoStats] = []
    totals = {w: 0 for w in _WINDOWS}
    for r in repos:
        repo_authors = authors or _resolve_default_authors(r)
        if not repo_authors:
            # No explicit config and no `git config user.email`: skip.
            continue
        counts = commit_counts(r, repo_authors, now=now)
        repo_stats.append(RepoStats(
            path=str(r),
            name=r.name,
            commits=counts,
            last_commit_at=_last_commit_at(r),
        ))
        for w, n in counts.items():
            totals[w] += n
    return Productivity(repos=repo_stats, totals=totals)
