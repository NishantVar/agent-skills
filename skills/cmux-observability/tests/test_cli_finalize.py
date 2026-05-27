"""No-cmux end-to-end integration smoke (T13).

Spawns the CLI in a real subprocess against a fake $HOME and a $PATH that
excludes `cmux`, then walks `collect` -> `finalize` and asserts the
operator-facing artifacts (HTML/JSON, runstate, failures) behave under the
degraded condition. There are no daemons, no servers, no watch loops here:
T13 is strictly the subprocess CLI flow.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


def _resolve_interpreter() -> str:
    """Pick a Python interpreter the same way SKILL.md prescribes:
    first match wins among `python3`, `python`; both must import jinja2
    and satisfy `sys.version_info >= (3, 11)`. Returns the absolute path
    of the chosen interpreter; raises if none qualifies.

    Explicit (not `sys.executable`) per reviewer Amendment 1.
    """
    probe = (
        "import sys, jinja2;"
        "sys.exit(0 if sys.version_info >= (3, 11) else 1)"
    )
    for cand in ("python3", "python"):
        path = shutil.which(cand)
        if not path:
            continue
        rc = subprocess.run(
            [path, "-c", probe], capture_output=True, text=True
        ).returncode
        if rc == 0:
            return path
    raise RuntimeError(
        "no suitable python on PATH (need >=3.11 with jinja2)"
    )


def _child_env(fake_home: Path, fake_bin: Path) -> dict[str, str]:
    """A minimal child env: PATH excludes `cmux`, HOME points to the fake
    tree, PYTHONPATH lets the subprocess import `cmux_observability`."""
    env = {
        "HOME": str(fake_home),
        # Empty bin dir guarantees cmux is unfindable even if the parent
        # had one earlier on PATH.
        "PATH": f"{fake_bin}{os.pathsep}/usr/bin:/bin",
        "PYTHONPATH": str(SKILL_ROOT),
        # Keep the child quiet/portable.
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }
    return env


def _run_cli(py: str, args: list[str], *, env: dict[str, str],
             stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [py, "-m", "cmux_observability.cli", *args],
        env=env, input=stdin, capture_output=True, text=True,
    )


def test_no_cmux_collect_then_finalize(tmp_path: Path) -> None:
    py = _resolve_interpreter()

    fake_home = tmp_path / "home"
    (fake_home / ".local" / "share" / "cmux-observability").mkdir(parents=True)
    (fake_home / ".local" / "state" / "cmux-observability").mkdir(parents=True)
    (fake_home / ".config" / "cmux-observability").mkdir(parents=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    env = _child_env(fake_home, fake_bin)

    # Sanity: the child env must not be able to find `cmux`.
    assert shutil.which("cmux", path=env["PATH"]) is None, (
        "Test setup is wrong: cmux is reachable from the child env's PATH"
    )

    # ---- collect ---------------------------------------------------------
    cp = _run_cli(py, ["collect"], env=env)
    assert cp.returncode == 0, f"stderr={cp.stderr}\nstdout={cp.stdout}"
    payload = json.loads(cp.stdout)

    assert payload["ok"] is True
    assert payload["pending_summaries"] == []
    failures = payload["snapshot_preview"]["failures"]
    cmux_failures = [f for f in failures if f["component"] == "cmux"]
    assert cmux_failures, (
        f"expected at least one component='cmux' failure, got: {failures}"
    )

    run_id = payload["run_id"]
    runstate_dir = fake_home / ".local" / "state" / "cmux-observability"
    runstate_file = runstate_dir / f"run-{run_id}.json"
    assert runstate_file.is_file(), (
        f"runstate file missing under fake HOME: {runstate_file}"
    )
    # Well-formed JSON.
    runstate_blob = json.loads(runstate_file.read_text())
    assert runstate_blob["run_id"] == run_id

    # Nothing escaped to the real $HOME.
    real_state = Path(os.path.expanduser("~/.local/state/cmux-observability"))
    if real_state.exists():
        assert not (real_state / f"run-{run_id}.json").exists(), (
            "runstate leaked to the real $HOME"
        )

    # ---- finalize --------------------------------------------------------
    cp = _run_cli(py, ["finalize", "--run-id", run_id, "--no-open"], env=env)
    assert cp.returncode == 0, f"stderr={cp.stderr}\nstdout={cp.stdout}"
    final = json.loads(cp.stdout)
    assert final["ok"] is True

    html_path = Path(final["html"])
    json_path = Path(final["json"])

    data_root = fake_home / ".local" / "share" / "cmux-observability"
    snapshots_dir = data_root / "snapshots"
    assert html_path.suffix == ".html"
    assert json_path.suffix == ".json"
    assert html_path.is_file(), f"HTML missing: {html_path}"
    assert json_path.is_file(), f"JSON missing: {json_path}"
    # Both artifacts must live under the fake HOME's snapshots dir.
    assert str(html_path).startswith(str(snapshots_dir)), (
        f"HTML not under fake HOME: {html_path}"
    )
    assert str(json_path).startswith(str(snapshots_dir)), (
        f"JSON not under fake HOME: {json_path}"
    )

    html = html_path.read_text()
    assert "cmux unavailable" in html.lower(), (
        "HTML missing the 'cmux unavailable' banner string"
    )

    # cmux failure preserved through finalize (cleanest in the final envelope).
    final_cmux_failures = [
        f for f in final["failures"] if f["component"] == "cmux"
    ]
    assert final_cmux_failures, (
        f"cmux failure not preserved through finalize: {final['failures']}"
    )

    # Runstate is discarded after finalize.
    assert not runstate_file.exists(), (
        f"runstate file should be discarded after finalize: {runstate_file}"
    )


def test_partial_failure_read_screen_renders_no_screen_access(
    tmp_home: Path, fake_cmux, fixture_dir: Path,
) -> None:
    """When `cmux read-screen` fails for a running surface, `collect` records a
    non-fatal Failure(component="read_screen", target=ref) and `finalize` still
    renders the dashboard with the no-summary fallback for that row."""
    py = _resolve_interpreter()

    env = os.environ.copy()
    env["HOME"] = str(tmp_home)
    env["PYTHONPATH"] = str(SKILL_ROOT)
    env["CMUX_FIXTURE_TREE"] = str(fixture_dir / "cmux_tree_with_tagged_ws.txt")
    env["CMUX_FIXTURE_TOP"] = str(fixture_dir / "cmux_top_with_tags.txt")
    env["CMUX_FAIL"] = "read-screen:1"

    cp = _run_cli(py, ["collect"], env=env)
    assert cp.returncode == 0, f"stderr={cp.stderr}\nstdout={cp.stdout}"
    payload = json.loads(cp.stdout)
    run_id = payload["run_id"]

    # The aligned fixture must yield at least one agent and at least one
    # read_screen failure — otherwise the partial-failure path is not
    # exercised (pending_summaries is naturally empty here because
    # read-screen failed for every running surface, so there's nothing to
    # summarise; the failures list is the load-bearing signal).
    assert payload["snapshot_preview"]["agents_total"] >= 1, (
        f"expected ≥1 agent from aligned with-tags fixture; got payload={payload}"
    )
    read_screen_failures = [
        f for f in payload["snapshot_preview"]["failures"]
        if f["component"] == "read_screen"
    ]
    assert read_screen_failures, (
        "expected ≥1 component='read_screen' failure from CMUX_FAIL; "
        f"got failures={payload['snapshot_preview']['failures']}"
    )

    cp = _run_cli(py, ["finalize", "--run-id", run_id, "--no-open"], env=env)
    assert cp.returncode == 0, f"stderr={cp.stderr}\nstdout={cp.stdout}"
    final = json.loads(cp.stdout)
    html = Path(final["html"]).read_text().lower()
    # Either "(no summary)" or "(no screen access)" satisfies the contract:
    # the row must render *something* for the missing-summary case.
    assert ("no summary" in html) or ("no screen access" in html), (
        "agent row missing both fallback literals"
    )


def test_partial_failure_no_git_renders_no_repos(
    tmp_home: Path, fake_cmux, fixture_dir: Path,
) -> None:
    """`collect --rescan` + `finalize` must not crash when $HOME contains no
    git repositories. The productivity section may render as totals-zero or
    be absent entirely; neither path should error."""
    py = _resolve_interpreter()

    env = os.environ.copy()
    env["HOME"] = str(tmp_home)
    env["PYTHONPATH"] = str(SKILL_ROOT)
    env["CMUX_FIXTURE_TREE"] = str(fixture_dir / "cmux_tree_basic.txt")
    env["CMUX_FIXTURE_TOP"] = str(fixture_dir / "cmux_top_no_tags.txt")

    cp = _run_cli(py, ["collect", "--rescan"], env=env)
    assert cp.returncode == 0, f"stderr={cp.stderr}\nstdout={cp.stdout}"
    run_id = json.loads(cp.stdout)["run_id"]

    cp = _run_cli(py, ["finalize", "--run-id", run_id, "--no-open"], env=env)
    assert cp.returncode == 0, f"stderr={cp.stderr}\nstdout={cp.stdout}"
    final = json.loads(cp.stdout)
    # Reading the rendered HTML must not raise; content is permissive.
    Path(final["html"]).read_text()
