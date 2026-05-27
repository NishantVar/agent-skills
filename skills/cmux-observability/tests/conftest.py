"""Shared pytest fixtures."""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from datetime import datetime, timedelta
from pathlib import Path

import pytest


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake $HOME with the three XDG-ish subtrees we use."""
    home = tmp_path / "home"
    (home / ".local" / "share" / "cmux-observability" / "snapshots").mkdir(parents=True)
    (home / ".local" / "state" / "cmux-observability").mkdir(parents=True)
    (home / ".config" / "cmux-observability").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    return home


def _run(cwd: Path, *args: str) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """A git repo with three commits by `alice@example.com` and one by
    `bob@example.com`, spaced across today, this week, and 30d windows."""
    repo = tmp_path / "tmp_repo"
    repo.mkdir()
    _run(repo, "git", "init", "-q", "-b", "main")
    _run(repo, "git", "config", "user.email", "alice@example.com")
    _run(repo, "git", "config", "user.name", "Alice")

    def commit(at: datetime, msg: str, email: str = "alice@example.com",
               name: str = "Alice") -> None:
        env = os.environ.copy()
        when = at.strftime("%Y-%m-%dT%H:%M:%S")
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
        env["GIT_AUTHOR_EMAIL"] = email
        env["GIT_COMMITTER_EMAIL"] = email
        env["GIT_AUTHOR_NAME"] = name
        env["GIT_COMMITTER_NAME"] = name
        (repo / "f.txt").write_text(msg)
        subprocess.run(["git", "add", "."], cwd=repo, check=True, env=env,
                       capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", msg], cwd=repo, check=True,
                       env=env, capture_output=True)

    now = datetime.now()
    commit(now - timedelta(hours=2), "today-commit-by-alice")
    commit(now - timedelta(days=3), "week-commit-by-alice")
    commit(now - timedelta(days=20), "month-commit-by-alice")
    commit(now - timedelta(days=2), "this-week-bob",
           email="bob@example.com", name="Bob")
    return repo


@pytest.fixture
def fake_cmux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Install a fake `cmux` binary that returns fixture contents per
    subcommand. Tests parameterize per scenario by setting env vars before
    asking the helper to invoke cmux."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cmux = bin_dir / "cmux"
    cmux.write_text(textwrap.dedent("""\
        #!/usr/bin/env bash
        # Dispatch on first arg; CMUX_FIXTURE_<SUBCMD> env vars name the
        # fixture file to print. CMUX_FAIL=<subcmd>:<exit> forces a failure.
        sub="$1"; shift
        if [ -n "$CMUX_FAIL" ]; then
          want="${CMUX_FAIL%%:*}"; rc="${CMUX_FAIL##*:}"
          [ "$want" = "$sub" ] && exit "$rc"
        fi
        var="CMUX_FIXTURE_${sub//-/_}"
        var=$(echo "$var" | tr '[:lower:]' '[:upper:]')
        path="${!var}"
        [ -n "$path" ] && cat "$path" || echo ""
    """))
    cmux.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return bin_dir
