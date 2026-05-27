"""Jinja2-based static HTML+JSON renderer for a Snapshot."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..model import Snapshot


_HERE = Path(__file__).parent


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_HERE / "templates")),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True, lstrip_blocks=True,
    )


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
