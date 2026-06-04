"""Deterministic generator for the shared golden capture envelope.

Run with `python3 tests/gen_golden.py` to (re)write the golden fixture in BOTH
skills. The golden is the watchdog→observability contract: watchdog asserts its
capture layer produces it; observability asserts it ingests with zero cmux calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import capture as cap


def build() -> dict:
    # Two workspaces: one with a tagged claude agent + a browser surface, one
    # with an untagged terminal whose scrollback is codex (heuristic promote).
    workspaces = [
        cap.CapWorkspace(
            ref="workspace:1", title="Capture Demo", window_ref="window:1",
            surfaces=[
                cap.CapSurface(ref="surface:1", pane_ref="pane:1",
                               workspace_ref="workspace:1", kind="terminal",
                               title="claude_code worker", tty="ttys001"),
                cap.CapSurface(ref="surface:2", pane_ref="pane:2",
                               workspace_ref="workspace:1", kind="browser",
                               title="cmux docs"),
            ],
        ),
        cap.CapWorkspace(
            ref="workspace:2", title="Heuristic WS", window_ref="window:1",
            surfaces=[
                cap.CapSurface(ref="surface:3", pane_ref="pane:3",
                               workspace_ref="workspace:2", kind="terminal",
                               title="some-tab", tty="ttys003"),
            ],
        ),
    ]
    top = cap.TopResult(
        tags_by_workspace={
            "workspace:1": [cap.TagLine(kind="claude_code", state="Running", pid=4242)],
        },
        stats_by_surface={
            "surface:1": cap.SurfaceStats(cpu_pct=1.5, mem_bytes=512 * 1024 * 1024),
        },
    )

    # Tagged claude surface shows a needs_input prompt → scrollback overrides
    # cmux_tag=running and emits a state_classifier failure. Plus a token to
    # exercise redaction metadata.
    claude_needs_input = (
        "❯ run the tests\n"
        "ctx:42%\n"
        "Do you want to proceed?\n"
        "  1. yes\n"
        "  2. no\n"
        "token sk-ABCDEFGHIJKLMNOPQRSTUVWX\n"
    )
    codex_running = (
        "› working on the parser\n"
        "• Working (3s • esc to interrupt)\n"
        "Context 51% left\n"
        "─ Worked for 0m 3s\n"
        "codex\n"
    )

    def reader(surface_ref, workspace_ref):
        return {
            "surface:1": claude_needs_input,
            "surface:3": codex_running,
        }.get(surface_ref, "")

    agents, captures, failures = cap.classify_surfaces(
        workspaces=workspaces, top=top, read_screen=reader,
    )
    return cap.build_envelope(
        workspaces=workspaces, agents=agents, captures=captures, failures=failures,
        host="golden-host", cmux_version="cmux 0.64.10",
        captured_at="2026-06-04T00:00:00+00:00", scope="all",
    )


GOLDEN_PATHS = [
    Path(__file__).resolve().parent / "fixtures" / "golden_snapshot.json",
    Path(__file__).resolve().parents[2]
    / "cmux-observability" / "tests" / "fixtures" / "golden_snapshot.json",
]


if __name__ == "__main__":
    env = build()
    blob = json.dumps(env, indent=2, sort_keys=True) + "\n"
    for p in GOLDEN_PATHS:
        p.write_text(blob)
        print(f"wrote {p}")
