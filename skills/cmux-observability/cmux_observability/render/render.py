"""Jinja2-based static HTML+JSON renderer for a Snapshot."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..model import Snapshot


_HERE = Path(__file__).parent


def _relative_time(dt: datetime) -> str:
    """Render a datetime as a short relative string: "14s ago", "3m ago",
    "2h ago", else ISO date. Compares against `datetime.now()` in the same
    tz-awareness as `dt` so subtraction never raises.
    """
    if dt is None:
        return ""
    now = datetime.now(dt.tzinfo) if dt.tzinfo is not None else datetime.now()
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{max(seconds, 0)}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return dt.date().isoformat()


def _truncated_summary(text: str | None, limit: int = 80) -> str:
    """T13 step 4 safety guard: trim a summary to the first newline OR `limit`
    characters, whichever comes first. Appends '…' when truncation occurred.

    Protects the surface-row layout against pathological multi-KB single-line
    summaries (the visible cell is CSS-truncated, but the rendered HTML still
    carries the full string until the browser's text-overflow kicks in).
    """
    if not text:
        return ""
    first_nl = text.find("\n")
    if first_nl == -1:
        cut = limit
    else:
        cut = min(first_nl, limit)
    if cut < len(text):
        return text[:cut] + "…"
    return text


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_HERE / "templates")),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True, lstrip_blocks=True,
    )
    env.filters["relative_time"] = _relative_time
    env.filters["truncated_summary"] = _truncated_summary
    return env


def _snapshot_to_json(snap: Snapshot) -> str:
    def default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        if hasattr(o, "__dict__"):
            return o.__dict__
        raise TypeError(f"non-serializable: {type(o)!r}")
    return json.dumps(snap, default=default, indent=2)


def render_snapshot(
    snapshot: Snapshot, out_dir: Path,
) -> tuple[Path, Path]:
    """Render snapshot.html and snapshot.json into `out_dir/snapshots/<iso>.{html,json}`."""
    snap_dir = out_dir if out_dir.name == "snapshots" else (out_dir / "snapshots")
    snap_dir.mkdir(parents=True, exist_ok=True)
    iso = snapshot.captured_at.strftime("%Y-%m-%dT%H-%M-%S")
    html_path = snap_dir / f"{iso}.html"
    json_path = snap_dir / f"{iso}.json"

    css = (_HERE / "style.css").read_text()
    js = (_HERE / "charts.js").read_text()

    tmpl = _env().get_template("snapshot.html.j2")
    html = tmpl.render(snapshot=snapshot, inline_css=css, inline_js=js)
    html_path.write_text(html)
    json_path.write_text(_snapshot_to_json(snapshot))
    return html_path, json_path
