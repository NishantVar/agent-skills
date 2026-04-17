#!/usr/bin/env python3
"""General-purpose terminal output reader with sentinel parsing.

Reads screen content from cmux or tmux surfaces and extracts
structured responses delimited by sentinel markers.
"""

import argparse
import json
import re
import subprocess
import sys
import time


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


def infer_backend(surface_ref: str) -> str:
    """Infer backend from surface ref format."""
    if surface_ref.startswith("surface:"):
        return "cmux"
    if surface_ref.startswith("%"):
        return "tmux"
    return "cmux"


def read_screen(surface_ref: str, backend: str, lines: int = 500) -> str | None:
    """Read terminal screen content from the given surface."""
    try:
        if backend == "cmux":
            result = subprocess.run(
                ["cmux", "read-screen", "--surface", surface_ref],
                capture_output=True, text=True,
            )
        elif backend == "tmux":
            result = subprocess.run(
                ["tmux", "capture-pane", "-p", "-t", surface_ref, "-S", f"-{lines}"],
                capture_output=True, text=True,
            )
        else:
            return None
    except FileNotFoundError:
        return None

    if result.returncode != 0:
        return None
    return result.stdout


def parse_output(text: str, start_marker: str, end_marker: str, sentinel_id: str | None,
                 blocked_start: str | None = None, blocked_end: str | None = None,
                 idle_marker: str | None = None, lines: int = 500) -> dict:
    """Parse terminal output for sentinel-marked blocks.

    Args:
        text: Raw terminal output (may contain ANSI codes).
        start_marker: Start sentinel marker (e.g. "TEAM_RESPONSE_START").
        end_marker: End sentinel marker (e.g. "TEAM_RESPONSE_END").
        sentinel_id: Specific sentinel ID to match (e.g. "TEAM_MSG_3"),
                     or None to match the marker alone (no ID suffix).
        blocked_start: Optional blocked state start marker.
        blocked_end: Optional blocked state end marker.
        idle_marker: Optional idle marker (single line, not a block).
        lines: Number of raw lines to return on fallback.

    Returns:
        Dict with "status" key: response_found, blocked, idle, no_sentinel.
    """
    clean = strip_ansi(text)

    def _find_block(s_marker, e_marker, sid):
        if sid:
            pattern = (
                re.escape(s_marker) + r"\s+" + re.escape(sid) + r"\s*\n"
                r"(.*?)\n\s*"
                + re.escape(e_marker) + r"\s+" + re.escape(sid)
            )
        else:
            pattern = (
                re.escape(s_marker) + r"\s*\n"
                r"(.*?)\n\s*"
                + re.escape(e_marker)
            )
        match = re.search(pattern, clean, re.DOTALL)
        return match.group(1).strip() if match else None

    # Check for response (highest priority)
    content = _find_block(start_marker, end_marker, sentinel_id)
    if content is not None:
        result = {"status": "response_found", "content": content}
        if sentinel_id:
            result["sentinelId"] = sentinel_id
        return result

    # Check for blocked
    if blocked_start and blocked_end:
        content = _find_block(blocked_start, blocked_end, sentinel_id)
        if content is not None:
            result = {"status": "blocked", "content": content}
            if sentinel_id:
                result["sentinelId"] = sentinel_id
            return result

    # Check for idle (single line marker)
    if idle_marker and sentinel_id:
        idle_pattern = re.escape(idle_marker) + r"\s+" + re.escape(sentinel_id)
        if re.search(idle_pattern, clean):
            return {"status": "idle", "sentinelId": sentinel_id}

    # Fallback: return raw last N lines
    last_lines = "\n".join(clean.strip().split("\n")[-lines:])
    return {"status": "no_sentinel", "lastLines": last_lines}


def single_read(surface, backend, start_marker, end_marker, sentinel_id,
                blocked_start=None, blocked_end=None, idle_marker=None,
                lines=500) -> dict:
    """Perform a single screen read and parse."""
    if backend == "auto":
        backend = infer_backend(surface)

    text = read_screen(surface, backend, lines)
    if text is None:
        return {"status": "error", "message": f"Failed to read from {surface} via {backend}"}

    return parse_output(
        text, start_marker, end_marker, sentinel_id,
        blocked_start=blocked_start, blocked_end=blocked_end,
        idle_marker=idle_marker, lines=lines,
    )


def poll_read(surface, backend, start_marker, end_marker, sentinel_id,
              blocked_start=None, blocked_end=None, idle_marker=None,
              lines=500, interval=5, max_attempts=120) -> dict:
    """Poll the terminal until a sentinel is found or timeout."""
    for attempt in range(1, max_attempts + 1):
        result = single_read(
            surface, backend, start_marker, end_marker, sentinel_id,
            blocked_start=blocked_start, blocked_end=blocked_end,
            idle_marker=idle_marker, lines=lines,
        )
        if result["status"] in ("response_found", "blocked", "idle", "error"):
            return result
        time.sleep(interval)

    # Final attempt after loop
    result = single_read(
        surface, backend, start_marker, end_marker, sentinel_id,
        blocked_start=blocked_start, blocked_end=blocked_end,
        idle_marker=idle_marker, lines=lines,
    )
    if result["status"] in ("response_found", "blocked", "idle"):
        return result
    return {
        "status": "timeout",
        "attempts": max_attempts,
        "lastLines": result.get("lastLines", ""),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Read terminal output and parse sentinel-marked responses"
    )
    parser.add_argument("--surface", required=True,
                        help="Surface ref (e.g. surface:42, %%7)")
    parser.add_argument("--backend", default="auto", choices=["auto", "cmux", "tmux"])
    parser.add_argument("--start-marker", required=True,
                        help="Sentinel start marker")
    parser.add_argument("--end-marker", required=True,
                        help="Sentinel end marker")
    parser.add_argument("--sentinel-id", default=None,
                        help="Specific sentinel ID to look for")
    parser.add_argument("--blocked-start", default=None,
                        help="Blocked state start marker")
    parser.add_argument("--blocked-end", default=None,
                        help="Blocked state end marker")
    parser.add_argument("--idle-marker", default=None,
                        help="Idle marker (single line)")
    parser.add_argument("--lines", type=int, default=500,
                        help="Lines of raw output on fallback (default: 500)")
    parser.add_argument("--poll", action="store_true",
                        help="Enable poll mode")
    parser.add_argument("--interval", type=int, default=5,
                        help="Seconds between polls (default: 5)")
    parser.add_argument("--max-attempts", type=int, default=120,
                        help="Max poll attempts (default: 120)")
    args = parser.parse_args()

    kwargs = dict(
        surface=args.surface, backend=args.backend,
        start_marker=args.start_marker, end_marker=args.end_marker,
        sentinel_id=args.sentinel_id,
        blocked_start=args.blocked_start, blocked_end=args.blocked_end,
        idle_marker=args.idle_marker, lines=args.lines,
    )

    if args.poll:
        result = poll_read(**kwargs, interval=args.interval,
                           max_attempts=args.max_attempts)
    else:
        result = single_read(**kwargs)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("status") != "error" else 1)


if __name__ == "__main__":
    main()
