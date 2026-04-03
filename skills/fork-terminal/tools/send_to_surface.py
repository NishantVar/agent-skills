#!/usr/bin/env python3
"""Send a file's contents to an already-running terminal surface.

Avoids shell argument length limits that truncate large "$(cat ...)" expansions.

Usage:
    python3 send_to_surface.py --surface surface:43 --file /tmp/prompt.txt
    python3 send_to_surface.py --surface %7 --file /tmp/prompt.txt --backend tmux
    python3 send_to_surface.py --surface surface:43 --file /tmp/prompt.txt --delay 3
"""

import argparse
import subprocess
import sys
import time


def detect_backend() -> str:
    """Detect cmux > tmux based on environment."""
    result = subprocess.run(["which", "cmux"], capture_output=True)
    if result.returncode == 0:
        return "cmux"
    result = subprocess.run(["which", "tmux"], capture_output=True)
    if result.returncode == 0:
        return "tmux"
    return "unknown"


def send_cmux(surface_ref: str, text: str) -> int:
    """Send text to a cmux surface, then press Enter to submit."""
    result = subprocess.run(
        ["cmux", "send", "--surface", surface_ref, text],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error: cmux send failed: {result.stderr.strip()}", file=sys.stderr)
        return result.returncode
    # Press Enter to submit (pasted content doesn't auto-submit in interactive CLIs)
    enter_result = subprocess.run(
        ["cmux", "send-key", "--surface", surface_ref, "Enter"],
        capture_output=True,
        text=True,
    )
    if enter_result.returncode != 0:
        print(f"Error: cmux send-key Enter failed: {enter_result.stderr.strip()}", file=sys.stderr)
    return enter_result.returncode


def send_tmux(pane_ref: str, text: str) -> int:
    """Send text to a tmux pane."""
    result = subprocess.run(
        ["tmux", "send-keys", "-t", pane_ref, text, "Enter"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error: tmux send-keys failed: {result.stderr.strip()}", file=sys.stderr)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a file to a terminal surface")
    parser.add_argument("--surface", required=True, help="Surface ref (e.g. surface:43 or %%7)")
    parser.add_argument("--file", required=True, help="Path to file whose contents to send")
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds to wait before sending (default: 0)")
    parser.add_argument("--backend", choices=["auto", "cmux", "tmux"], default="auto")
    args = parser.parse_args()

    # Read prompt file
    try:
        with open(args.file, "r") as f:
            content = f.read()
    except OSError as e:
        print(f"Error reading file {args.file}: {e}", file=sys.stderr)
        return 1

    if not content.strip():
        print("Error: file is empty", file=sys.stderr)
        return 1

    # Resolve backend
    backend = args.backend if args.backend != "auto" else detect_backend()

    # Optional delay
    if args.delay > 0:
        time.sleep(args.delay)

    # Send
    if backend == "cmux":
        return send_cmux(args.surface, content)
    elif backend == "tmux":
        return send_tmux(args.surface, content)
    else:
        print("Error: no supported backend found (cmux or tmux)", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
