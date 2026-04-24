#!/usr/bin/env python3
"""Send a file's contents to an already-running terminal surface.

Avoids shell argument length limits that truncate large "$(cat ...)" expansions.

Usage:
    python3 send_to_surface.py --surface surface:43 --file /tmp/prompt.txt
    python3 send_to_surface.py --surface %7 --file /tmp/prompt.txt --backend tmux
    python3 send_to_surface.py --surface surface:43 --file /tmp/prompt.txt --delay 3
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time


def detect_backend() -> str:
    """Auto-detect terminal backend by walking the process tree.

    Checks ancestor processes for cmux/tmux rather than just checking
    if the binary is installed, so we pick the backend we're actually inside.
    """
    try:
        pid = os.getpid()
        while pid > 1:
            result = subprocess.run(
                ["ps", "-o", "args=,ppid=", "-p", str(pid)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                break
            parts = result.stdout.strip().rsplit(None, 1)
            if len(parts) != 2:
                break
            comm, ppid = parts[0].lower(), int(parts[1])
            if "cmux" in comm:
                return "cmux"
            if "tmux" in comm:
                return "tmux"
            pid = ppid
    except Exception:
        pass

    # Fallback: check if binaries are installed (prefer cmux)
    if subprocess.run(["which", "cmux"], capture_output=True).returncode == 0:
        return "cmux"
    if subprocess.run(["which", "tmux"], capture_output=True).returncode == 0:
        return "tmux"
    return "unknown"


def send_cmux(surface_ref: str, text: str) -> int:
    """Send text to a cmux surface using set-buffer/paste-buffer to avoid truncation.

    cmux send passes text as a CLI arg which can truncate large messages.
    set-buffer + paste-buffer handles arbitrary sizes reliably.
    """
    result = subprocess.run(
        ["cmux", "set-buffer", "--name", "send_to_surface", "--", text],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error: cmux set-buffer failed: {result.stderr.strip()}", file=sys.stderr)
        return result.returncode

    result = subprocess.run(
        ["cmux", "paste-buffer", "--name", "send_to_surface",
         "--surface", surface_ref],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error: cmux paste-buffer failed: {result.stderr.strip()}", file=sys.stderr)
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
    """Send text to a tmux pane using load-buffer/paste-buffer.

    Avoids ARG_MAX limits that truncate large prompts when passed
    as arguments to tmux send-keys.
    """
    # Write text to a temp file, load into tmux buffer, paste into the target pane
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(text)
        tmp_path = f.name
    try:

        result = subprocess.run(
            ["tmux", "load-buffer", tmp_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"Error: tmux load-buffer failed: {result.stderr.strip()}", file=sys.stderr)
            return result.returncode

        result = subprocess.run(
            ["tmux", "paste-buffer", "-t", pane_ref],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"Error: tmux paste-buffer failed: {result.stderr.strip()}", file=sys.stderr)
            return result.returncode

        # Press Enter to submit the pasted text
        result = subprocess.run(
            ["tmux", "send-keys", "-t", pane_ref, "Enter"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"Error: tmux send-keys Enter failed: {result.stderr.strip()}", file=sys.stderr)
        return result.returncode
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


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
