"""argparse entrypoint for the skill. Five subcommands, one shared run_id.

  cmux-observability collect          --run-id <id>
  cmux-observability record-summaries --run-id <id> [stdin=json]
  cmux-observability themes-payload   --run-id <id>
  cmux-observability record-themes    --run-id <id> [stdin=json]
  cmux-observability finalize         --run-id <id> [--no-open]

`--config` is registered on every subparser (post-subcommand position)
so operators can write `collect --config <path>`. `HOME`-derived dirs
are resolved lazily inside helpers — see `_data_dir()`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import runstate
from .collector.classify import classify_from_scrollback
from .collector.cmux import (
    CmuxUnavailable,
    cmux_version,
    fetch_top,
    fetch_tree,
    read_screen,
)
from .collector.discovery import discover_repos
from .collector.git import productivity
from .config import Config, default_config_path, load
from .errors import Failure
from .model import Agent, HistoryPoint, HistorySeries
from .normalize import normalize
from .persist import append_snapshot, connect, migrate
from .render.render import render_snapshot
from .summarize_io import (
    pending_for_agent,
    record_from_agent,
    record_themes_from_agent,
    themes_payload,
)


def _data_dir() -> Path:
    """Resolve the data dir lazily so tests/agents can monkeypatch $HOME."""
    home = os.environ.get("HOME", os.path.expanduser("~"))
    return Path(home) / ".local" / "share" / "cmux-observability"


def _emit(payload: dict) -> int:
    json.dump(payload, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


def _load_config(args: argparse.Namespace) -> Config:
    path = Path(args.config) if args.config else default_config_path()
    return load(path)


def cmd_collect(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    failures: list[Failure] = []

    try:
        workspaces = fetch_tree()
        top = fetch_top()
        version = cmux_version()
    except CmuxUnavailable as e:
        workspaces, top, version = [], None, None
        failures.append(Failure(
            component="cmux", target=None, message=str(e), fatal=False,
        ))

    if top is None:
        from .collector.cmux import TopResult
        top = TopResult()

    snap = normalize(
        workspaces=workspaces, top=top,
        host=os.uname().nodename, cmux_version=version,
        now=datetime.now(timezone.utc),
    )

    # Productivity (best-effort; failures attached non-fatally).
    try:
        repos, disc_failures = discover_repos(cfg, force_rescan=args.rescan)
        snap.productivity = productivity(repos, cfg)
        failures.extend(disc_failures)
    except Exception as e:                      # noqa: BLE001
        failures.append(Failure(
            component="discovery", target=None, message=str(e), fatal=False,
        ))

    # Read scrollback for all running/needs-input agents.
    screens: dict[str, str] = {}
    lines = (cfg.summarizer.read_screen_lines if cfg.summarizer else 150)
    lines = max(1, min(300, lines))
    for a in snap.agents:
        if a.state in ("running", "needs_input"):
            try:
                screens[a.surface_ref] = read_screen(
                    a.surface_ref,
                    workspace_ref=a.workspace_ref,
                    lines=lines,
                )
            except CmuxUnavailable as e:
                failures.append(Failure(
                    component="read_screen", target=a.surface_ref,
                    message=str(e), fatal=False,
                ))

    # Heuristic fallback: for terminal surfaces not yet attached to an agent,
    # read scrollback and ask the classifier. Tagged surfaces are untouched
    # (cmux_tag wins on precedence — they're already in snap.agents).
    agent_refs = {a.surface_ref for a in snap.agents}
    for w in snap.workspaces:
        for s in w.surfaces:
            if s.ref in agent_refs or s.kind != "terminal":
                continue
            try:
                tail = read_screen(
                    s.ref, workspace_ref=w.ref, lines=lines,
                )
            except CmuxUnavailable as e:
                failures.append(Failure(
                    component="read_screen", target=s.ref,
                    message=str(e), fatal=False,
                ))
                continue
            kind, confidence = classify_from_scrollback(tail)
            if kind is None:
                continue
            s.is_agent = True
            screens[s.ref] = tail
            snap.agents.append(Agent(
                surface_ref=s.ref,
                workspace_ref=w.ref,
                type=kind,
                type_source="heuristic",
                type_confidence=confidence,
                state="unknown",
                state_source="heuristic",
                pid=None,
            ))

    snap.failures = failures

    data_dir = _data_dir()
    db_path = data_dir / "observability.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        migrate(conn)
        pv = (cfg.summarizer.prompt_version if cfg.summarizer else 1)
        pending = pending_for_agent(snap, conn, screens, prompt_version=pv)

    screen_hashes = {p["surface_ref"]: p["screen_hash"] for p in pending}
    redactions_by_surface = {
        p["surface_ref"]: p["redactions_applied"] for p in pending
    }

    run_id = args.run_id or runstate.new_run_id()
    runstate.write(run_id, snap, screen_hashes=screen_hashes,
                   redactions_by_surface=redactions_by_surface)

    return _emit({
        "ok": True, "run_id": run_id,
        "pending_summaries": pending,
        "snapshot_preview": {
            "agents_total": len(snap.agents),
            "workspaces_total": len(snap.workspaces),
            "failures": [f.__dict__ for f in failures],
        },
    })


def cmd_record_summaries(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    snap, screen_hashes, redactions_by_surface = runstate.read(args.run_id)
    payload = json.loads(sys.stdin.read() or "{}")

    data_dir = _data_dir()
    db_path = data_dir / "observability.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        migrate(conn)
        pv = (cfg.summarizer.prompt_version if cfg.summarizer else 1)
        new_failures = record_from_agent(
            payload, snap, conn,
            prompt_version=pv,
            screen_hashes=screen_hashes,
            redactions_by_surface=redactions_by_surface,
        )
    snap.failures.extend(new_failures)
    runstate.write(args.run_id, snap,
                   screen_hashes=screen_hashes,
                   redactions_by_surface=redactions_by_surface)
    return _emit({"ok": True, "failures": [f.__dict__ for f in new_failures]})


def cmd_themes_payload(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    snap, _h, _r = runstate.read(args.run_id)
    summaries_enabled = bool(cfg.summarizer and cfg.summarizer.enabled)
    result = themes_payload(snap, summaries_enabled=summaries_enabled)
    # `result` is already the envelope: {payload, omit, reason?}.
    return _emit({"ok": True, **result})


def cmd_record_themes(args: argparse.Namespace) -> int:
    snap, screen_hashes, redactions_by_surface = runstate.read(args.run_id)
    payload = json.loads(sys.stdin.read() or "{}")
    new_failures = record_themes_from_agent(payload, snap)
    snap.failures.extend(new_failures)
    runstate.write(args.run_id, snap,
                   screen_hashes=screen_hashes,
                   redactions_by_surface=redactions_by_surface)
    return _emit({"ok": True, "failures": [f.__dict__ for f in new_failures]})


def cmd_finalize(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    snap, _h, _r = runstate.read(args.run_id)

    data_dir = _data_dir()
    db_path = data_dir / "observability.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        migrate(conn)
        # attach history (last 100 points)
        rows = conn.execute(
            "SELECT captured_at, agents_total, agents_running,"
            " agents_needs_input, by_type_json"
            " FROM snapshots ORDER BY id DESC LIMIT 100"
        ).fetchall()
        if rows:
            pts = [
                HistoryPoint(
                    captured_at=datetime.fromisoformat(r[0]),
                    agents_total=r[1], agents_running=r[2],
                    agents_needs_input=r[3],
                    by_type=json.loads(r[4]),
                )
                for r in reversed(rows)
            ]
            snap.history = HistorySeries(points=pts)
        html_path, json_path = render_snapshot(snap, data_dir)
        append_snapshot(conn, snap, json_path=str(json_path))

    _retain(data_dir / "snapshots", cfg.render.retention if cfg.render else 100)

    if cfg.render and cfg.render.open_browser and not args.no_open:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        try:
            subprocess.Popen([opener, str(html_path)],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            pass

    runstate.discard(args.run_id)
    return _emit({
        "ok": True,
        "html": str(html_path),
        "json": str(json_path),
        "failures": [f.__dict__ for f in snap.failures],
    })


def _retain(snap_dir: Path, keep: int) -> None:
    if not snap_dir.exists():
        return
    files = sorted(
        [p for p in snap_dir.iterdir() if p.suffix in (".html", ".json")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    # Each snapshot has 2 files; keep `keep` pairs.
    for p in files[keep * 2:]:
        try:
            p.unlink()
        except OSError:
            pass


def _add_config_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", default=None, help="Path to config TOML")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cmux-observability")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("collect")
    _add_config_arg(pc)
    pc.add_argument("--run-id", help="Provide to resume; new id minted if omitted")
    pc.add_argument("--rescan", action="store_true")
    pc.set_defaults(func=cmd_collect)

    ps = sub.add_parser("record-summaries")
    _add_config_arg(ps)
    ps.add_argument("--run-id", required=True)
    ps.set_defaults(func=cmd_record_summaries)

    pt = sub.add_parser("themes-payload")
    _add_config_arg(pt)
    pt.add_argument("--run-id", required=True)
    pt.set_defaults(func=cmd_themes_payload)

    pr = sub.add_parser("record-themes")
    _add_config_arg(pr)
    pr.add_argument("--run-id", required=True)
    pr.set_defaults(func=cmd_record_themes)

    pf = sub.add_parser("finalize")
    _add_config_arg(pf)
    pf.add_argument("--run-id", required=True)
    pf.add_argument("--no-open", action="store_true")
    pf.set_defaults(func=cmd_finalize)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
