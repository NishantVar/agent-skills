"""SQLite persistence for snapshots, per-agent observations, and the
summary cache."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

from .model import Snapshot


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  captured_at TEXT NOT NULL,
  schema_version INTEGER NOT NULL,
  agents_total INTEGER NOT NULL,
  agents_running INTEGER NOT NULL,
  agents_needs_input INTEGER NOT NULL,
  by_type_json TEXT NOT NULL,
  workspaces_total INTEGER NOT NULL,
  surfaces_total INTEGER NOT NULL,
  themes_json TEXT,
  json_path TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
  surface_ref TEXT NOT NULL,
  workspace_ref TEXT NOT NULL,
  type TEXT NOT NULL,
  state TEXT NOT NULL,
  summary_text TEXT
);

CREATE TABLE IF NOT EXISTS summary_cache (
  surface_ref TEXT NOT NULL,
  screen_hash TEXT NOT NULL,
  prompt_version INTEGER NOT NULL,
  summary_json TEXT NOT NULL,
  cached_at TEXT NOT NULL,
  PRIMARY KEY (surface_ref, screen_hash, prompt_version)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_captured ON snapshots(captured_at);
CREATE INDEX IF NOT EXISTS idx_observations_snapshot ON agent_observations(snapshot_id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def append_snapshot(
    conn: sqlite3.Connection, snapshot: Snapshot, *, json_path: str,
) -> int:
    agents = snapshot.agents
    by_type = Counter(a.type for a in agents if a.type != "unknown_agent")
    running = sum(1 for a in agents if a.state == "running")
    needs   = sum(1 for a in agents if a.state == "needs_input")
    themes_json = (
        json.dumps([t.__dict__ for t in snapshot.themes]) if snapshot.themes else None
    )
    surfaces_total = sum(len(w.surfaces) for w in snapshot.workspaces)

    cur = conn.execute(
        """
        INSERT INTO snapshots (
          captured_at, schema_version,
          agents_total, agents_running, agents_needs_input,
          by_type_json, workspaces_total, surfaces_total,
          themes_json, json_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot.captured_at.isoformat(),
            snapshot.schema_version,
            len(agents),
            running,
            needs,
            json.dumps(dict(by_type)),
            len(snapshot.workspaces),
            surfaces_total,
            themes_json,
            json_path,
        ),
    )
    snapshot_id = cur.lastrowid or 0
    for a in agents:
        conn.execute(
            """
            INSERT INTO agent_observations (
              snapshot_id, surface_ref, workspace_ref, type, state, summary_text
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id, a.surface_ref, a.workspace_ref,
                a.type, a.state, a.summary.text if a.summary else None,
            ),
        )
    conn.commit()
    return snapshot_id
