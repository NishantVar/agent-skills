#!/usr/bin/env -S uv run
"""Fork a new terminal — dispatches to pluggable backends."""

import os
import platform
import shutil
import subprocess
import sys


def resolve_direction(split_direction: str, backend: str) -> str:
    """Resolve split direction. Defaults to 'right' if not specified."""
    if split_direction in ("right", "bottom"):
        return split_direction
    return "right"


def detect_backend() -> str:
    """Auto-detect terminal backend by walking the process tree."""
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

    # On platforms where native isn't supported, prefer an installed multiplexer
    if platform.system() not in ("Darwin", "Windows"):
        if shutil.which("tmux"):
            return "tmux"
        if shutil.which("cmux"):
            return "cmux"

    return "native"


def resolve_plan_dir() -> str:
    """Find the best directory to save plan files.

    Priority: Obsidian Vault → ~/.claude/plans/ → /tmp/claude-plans/
    """
    vault = os.environ.get("OBSIDIAN_VAULT")
    candidates = []
    if vault:
        candidates.append(os.path.join(vault, "Claude", "plans"))
    candidates += [
        os.path.expanduser("~/.claude/plans"),
        "/tmp/claude-plans",
    ]
    for d in candidates:
        if os.path.isdir(d):
            return d
    # Create the first writable candidate
    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            return d
        except OSError:
            continue
    return "/tmp"


def save_plan(content: str, name: str | None = None) -> str:
    """Save plan content to a file and return the path."""
    import re
    from datetime import datetime

    plan_dir = resolve_plan_dir()

    if not name:
        # Extract name from first heading or use timestamp
        match = re.search(r"^#\s+(.+)", content, re.MULTILINE)
        if match:
            slug = re.sub(r"[^a-z0-9]+", "-", match.group(1).lower()).strip("-")[:50]
            name = f"{datetime.now().strftime('%Y-%m-%d')}-{slug}.md"
        else:
            name = f"plan-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.md"

    path = os.path.join(plan_dir, name)
    with open(path, "w") as f:
        f.write(content)
    return path


def fork_terminal(command: str, backend: str = "auto", split_direction: str = "auto", delayed_input: str | None = None, delayed_input_file: str | None = None, delay_seconds: float = 5.0) -> str:
    """Fork a terminal using the specified backend.

    Args:
        delayed_input: Text to send to the surface after the command starts (after delay_seconds).
        delayed_input_file: Path to a file whose contents to send (alternative to delayed_input).
        delay_seconds: Seconds to wait before sending delayed input (default 5).
    """
    if backend == "auto":
        backend = detect_backend()

    cwd = os.getcwd()
    direction = resolve_direction(split_direction, backend)

    # Import the backend module from backends/ directory
    backends_dir = os.path.join(os.path.dirname(__file__), "backends")
    sys.path.insert(0, os.path.dirname(__file__))
    try:
        import importlib
        module = importlib.import_module(f"backends.{backend}")
    except ModuleNotFoundError:
        return f"Error: unknown backend '{backend}'. Valid: native, tmux, cmux"
    finally:
        sys.path.pop(0)

    # Resolve delayed input from file if specified
    input_text = delayed_input
    if delayed_input_file and not input_text:
        try:
            with open(os.path.expanduser(delayed_input_file), "r") as f:
                input_text = f.read().strip()
        except Exception as e:
            return f"Error reading delayed input file: {e}"

    return module.fork(command, cwd, direction, delayed_input=input_text, delay_seconds=delay_seconds)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fork a terminal session")
    parser.add_argument("command", nargs="+", help="Command to run")
    parser.add_argument("--backend", default="auto")
    parser.add_argument("--split", default="auto", choices=["auto", "right", "bottom"])
    parser.add_argument("--delayed-input", default=None, help="Text to send after command starts")
    parser.add_argument("--delayed-input-file", default=None, help="File whose contents to send after command starts")
    parser.add_argument("--delay", type=float, default=5.0, help="Seconds to wait before sending delayed input")
    parser.add_argument("--save-plan", default=None, help="Plan file to save and use as delayed input. Copies to plan dir, uses as prompt.")
    parser.add_argument("--save-plan-content", default=None, help="Raw plan content to save and use as delayed input")
    args = parser.parse_args()

    # Handle --save-plan: copy existing plan file to plan dir, use as delayed input
    delayed_file = args.delayed_input_file
    if args.save_plan:
        src = os.path.expanduser(args.save_plan)
        if not os.path.isfile(src):
            print(f"Error: plan file not found: {src}")
            sys.exit(1)
        with open(src, "r") as f:
            content = f.read()
        saved_path = save_plan(content)
        print(f"Plan saved to: {saved_path}")
        delayed_file = saved_path
    elif args.save_plan_content:
        saved_path = save_plan(args.save_plan_content)
        print(f"Plan saved to: {saved_path}")
        delayed_file = saved_path

    # Build the prompt that wraps the plan file
    delayed_input = args.delayed_input
    if delayed_file and not delayed_input:
        delayed_input = f"Read and execute the plan at {delayed_file}. Do NOT commit."

    output = fork_terminal(
        " ".join(args.command),
        backend=args.backend,
        split_direction=args.split,
        delayed_input=delayed_input,
        delay_seconds=args.delay,
    )
    print(output)
