"""End-to-end integration smoke for the pure view layer.

Spawns the CLI in a real subprocess against a fake $HOME, pipes a watchdog
capture envelope into `collect` (observability no longer reads cmux), and walks
`collect` → `finalize` (and the full 5-step contract) asserting the
operator-facing artifacts. No daemons, no servers, no watch loops.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


def _resolve_interpreter() -> str:
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
    raise RuntimeError("no suitable python on PATH (need >=3.11 with jinja2)")


def _child_env(fake_home: Path) -> dict[str, str]:
    return {
        "HOME": str(fake_home),
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": str(SKILL_ROOT),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }


def _fake_home(tmp_path: Path) -> Path:
    fake_home = tmp_path / "home"
    (fake_home / ".local" / "share" / "cmux-observability").mkdir(parents=True)
    (fake_home / ".local" / "state" / "cmux-observability").mkdir(parents=True)
    (fake_home / ".config" / "cmux-observability").mkdir(parents=True)
    return fake_home


def _run_cli(py: str, args: list[str], *, env: dict[str, str],
             stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [py, "-m", "cmux_observability.cli", *args],
        env=env, input=stdin, capture_output=True, text=True,
    )


# --- envelope helpers ------------------------------------------------------

def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _envelope(*, workspaces=None, agents=None, captures=None, failures=None,
              cmux_version: str | None = "0.64.10") -> str:
    return json.dumps({
        "capture_schema_version": 1,
        "captured_at": "2026-05-27T12:00:00+00:00",
        "host": "laptop",
        "cmux_version": cmux_version,
        "scope": "all",
        "workspaces": workspaces or [],
        "agents": agents or [],
        "captures": captures or [],
        "failures": failures or [],
    })


def _ws(ref, surfaces):
    return {"ref": ref, "title": f"WS {ref}", "window_ref": "window:1",
            "surfaces": surfaces}


def _sfc(ref, ws_ref, *, title="tab", is_agent=False):
    return {"ref": ref, "pane_ref": f"pane:{ref.split(':')[-1]}",
            "workspace_ref": ws_ref, "kind": "terminal", "title": title,
            "tty": None, "cwd": None, "cpu_pct": None, "mem_bytes": None,
            "is_agent": is_agent}


def _agent(ref, ws_ref, *, state="running"):
    return {"surface_ref": ref, "workspace_ref": ws_ref, "type": "claude_code",
            "type_source": "cmux_tag", "type_confidence": 1.0, "state": state,
            "state_source": "cmux_tag", "pid": 4242}


def _cap(ref, text):
    return {"surface_ref": ref, "redacted_scrollback": text,
            "screen_hash": _hash(text), "redactions_applied": []}


# --- tests -----------------------------------------------------------------

def test_no_cmux_collect_then_finalize(tmp_path: Path) -> None:
    """A degraded envelope (cmux_version null + a component='cmux' failure)
    ingests cleanly, renders the 'cmux unavailable' banner, and preserves the
    failure through finalize."""
    py = _resolve_interpreter()
    fake_home = _fake_home(tmp_path)
    env = _child_env(fake_home)

    envelope = _envelope(
        cmux_version=None,
        failures=[{"component": "cmux", "target": None,
                   "message": "cmux binary not on PATH", "fatal": False}],
    )
    cp = _run_cli(py, ["collect"], env=env, stdin=envelope)
    assert cp.returncode == 0, f"stderr={cp.stderr}\nstdout={cp.stdout}"
    payload = json.loads(cp.stdout)

    assert payload["ok"] is True
    assert payload["pending_summaries"] == []
    cmux_failures = [f for f in payload["snapshot_preview"]["failures"]
                     if f["component"] == "cmux"]
    assert cmux_failures, payload["snapshot_preview"]["failures"]

    run_id = payload["run_id"]
    runstate_file = (fake_home / ".local" / "state" / "cmux-observability"
                     / f"run-{run_id}.json")
    assert runstate_file.is_file()
    assert json.loads(runstate_file.read_text())["run_id"] == run_id

    cp = _run_cli(py, ["finalize", "--run-id", run_id, "--no-open"], env=env)
    assert cp.returncode == 0, f"stderr={cp.stderr}\nstdout={cp.stdout}"
    final = json.loads(cp.stdout)
    assert final["ok"] is True

    html = Path(final["html"]).read_text()
    assert "unavailable" in html.lower()
    final_cmux_failures = [f for f in final["failures"]
                           if f["component"] == "cmux"]
    assert final_cmux_failures, final["failures"]
    assert not runstate_file.exists()       # discarded after finalize


def test_partial_failure_read_screen_renders_no_screen_access(
    tmp_path: Path,
) -> None:
    """An agent the watchdog couldn't read (read_screen failure, no capture)
    renders with the no-summary fallback."""
    py = _resolve_interpreter()
    fake_home = _fake_home(tmp_path)
    env = _child_env(fake_home)

    envelope = _envelope(
        workspaces=[_ws("workspace:1", [_sfc("surface:1", "workspace:1", is_agent=True)])],
        agents=[_agent("surface:1", "workspace:1", state="running")],
        captures=[],            # read failed → no capture
        failures=[{"component": "read_screen", "target": "surface:1",
                   "message": "cmux read-screen exited 1", "fatal": False}],
    )
    cp = _run_cli(py, ["collect"], env=env, stdin=envelope)
    assert cp.returncode == 0, f"stderr={cp.stderr}\nstdout={cp.stdout}"
    payload = json.loads(cp.stdout)
    run_id = payload["run_id"]

    assert payload["snapshot_preview"]["agents_total"] >= 1
    rs_failures = [f for f in payload["snapshot_preview"]["failures"]
                   if f["component"] == "read_screen"]
    assert rs_failures

    cp = _run_cli(py, ["finalize", "--run-id", run_id, "--no-open"], env=env)
    assert cp.returncode == 0, f"stderr={cp.stderr}\nstdout={cp.stdout}"
    final = json.loads(cp.stdout)
    html = Path(final["html"]).read_text().lower()
    assert ("no summary" in html) or ("no screen access" in html)


def test_partial_failure_no_git_renders_no_repos(tmp_path: Path) -> None:
    """`collect --rescan` + `finalize` must not crash when $HOME has no repos."""
    py = _resolve_interpreter()
    fake_home = _fake_home(tmp_path)
    env = _child_env(fake_home)

    envelope = _envelope(
        workspaces=[_ws("workspace:1", [_sfc("surface:1", "workspace:1")])],
    )
    cp = _run_cli(py, ["collect", "--rescan"], env=env, stdin=envelope)
    assert cp.returncode == 0, f"stderr={cp.stderr}\nstdout={cp.stdout}"
    run_id = json.loads(cp.stdout)["run_id"]

    cp = _run_cli(py, ["finalize", "--run-id", run_id, "--no-open"], env=env)
    assert cp.returncode == 0, f"stderr={cp.stderr}\nstdout={cp.stdout}"
    Path(json.loads(cp.stdout)["html"]).read_text()


def test_full_pipeline_with_summaries_and_themes(tmp_path: Path) -> None:
    """5-step JSON contract end-to-end: collect (envelope) → record-summaries →
    themes-payload → record-themes → finalize. Agent-authored summary + theme
    land in the rendered HTML."""
    py = _resolve_interpreter()
    fake_home = _fake_home(tmp_path)
    env = _child_env(fake_home)

    envelope = _envelope(
        workspaces=[_ws("workspace:1",
                        [_sfc("surface:1", "workspace:1", title="claude_code", is_agent=True)])],
        agents=[_agent("surface:1", "workspace:1", state="running")],
        captures=[_cap("surface:1", "❯ run the tests\nctx:42%\n")],
    )
    cp = _run_cli(py, ["collect"], env=env, stdin=envelope)
    assert cp.returncode == 0, f"stderr={cp.stderr}\nstdout={cp.stdout}"
    payload = json.loads(cp.stdout)
    run_id = payload["run_id"]
    pending = payload.get("pending_summaries", [])
    assert pending, "expected at least one pending summary from the envelope"

    summaries = {"summaries": [{
        "surface_ref": p["surface_ref"],
        "summary": "writing tests for the parser",
        "state_hint": p["cmux_state"],
        "needs_input_reason": None,
        "confidence": 0.85,
    } for p in pending]}
    cp = _run_cli(py, ["record-summaries", "--run-id", run_id], env=env,
                  stdin=json.dumps(summaries))
    assert cp.returncode == 0, f"stderr={cp.stderr}\nstdout={cp.stdout}"

    cp = _run_cli(py, ["themes-payload", "--run-id", run_id], env=env)
    assert cp.returncode == 0, f"stderr={cp.stderr}\nstdout={cp.stdout}"
    tp = json.loads(cp.stdout)
    if tp.get("omit"):
        themes = {"themes": []}
    else:
        themes = {"themes": [{
            "label": "parser work",
            "member_refs": [p["surface_ref"] for p in pending],
            "why": "all agents are running parser-related work",
            "confidence": 0.8,
        }]}
    cp = _run_cli(py, ["record-themes", "--run-id", run_id], env=env,
                  stdin=json.dumps(themes))
    assert cp.returncode == 0, f"stderr={cp.stderr}\nstdout={cp.stdout}"

    cp = _run_cli(py, ["finalize", "--run-id", run_id, "--no-open"], env=env)
    assert cp.returncode == 0, f"stderr={cp.stderr}\nstdout={cp.stdout}"
    final = json.loads(cp.stdout)
    html = Path(final["html"]).read_text()
    assert "writing tests for the parser" in html
    if not tp.get("omit"):
        assert "parser work" in html
