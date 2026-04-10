"""tmux backend — split pane in current tmux session."""

import os
import shlex
import subprocess
import tempfile
import threading
import time


def _send_delayed_input(pane_id: str, text: str, delay: float) -> None:
    """Wait for the command to start, then send text to the tmux pane.

    Uses load-buffer/paste-buffer to avoid ARG_MAX limits on large prompts.
    """
    time.sleep(delay)
    # Write text to a temp file, load into tmux buffer, paste into the target pane
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(text)
        tmp_path = f.name
    try:
        subprocess.run(
            ["tmux", "load-buffer", tmp_path],
            capture_output=True, text=True,
        )
        subprocess.run(
            ["tmux", "paste-buffer", "-t", pane_id],
            capture_output=True, text=True,
        )
        # Press Enter to submit the pasted text
        subprocess.run(
            ["tmux", "send-keys", "-t", pane_id, "Enter"],
            capture_output=True, text=True,
        )
    finally:
        os.unlink(tmp_path)


def fork(command: str, cwd: str, split_direction: str, delayed_input: str | None = None, delay_seconds: float = 5.0) -> str:
    """Split a new tmux pane and run the command.

    Args:
        split_direction: "right" for vertical split (-h), "bottom" for horizontal split (-v).
        delayed_input: Text to send after the command starts (e.g., a prompt for an interactive CLI).
        delay_seconds: Seconds to wait before sending delayed input.
    """
    if not os.environ.get("TMUX"):
        return "Error: not inside a tmux session. Start tmux first or use a different backend."

    flag = "-h" if split_direction == "right" else "-v"

    try:
        shell = os.environ.get("SHELL") or "/bin/sh"
        safe_cwd = shlex.quote(cwd)
        safe_shell = shlex.quote(shell)
        shell_command = f"cd {safe_cwd} && {command}; exec {safe_shell} -li"
        result = subprocess.run(
            ["tmux", "split-window", flag, "-P", "-F", "#{pane_id}", shell, "-lic", shell_command],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return f"Error: tmux split-window failed: {result.stderr.strip()}"
        pane_id = result.stdout.strip()

        # Schedule delayed input if requested
        if delayed_input and pane_id:
            thread = threading.Thread(
                target=_send_delayed_input,
                args=(pane_id, delayed_input, delay_seconds),
            )
            thread.start()
            thread.join(timeout=delay_seconds + 10)

        ref_info = f" [ref={pane_id}]" if pane_id else ""
        delayed_info = f" [delayed input sent after {delay_seconds}s]" if delayed_input else ""
        return f"tmux pane split ({split_direction}): OK{ref_info}{delayed_info}"
    except FileNotFoundError:
        return "Error: tmux is not installed or not in PATH"
    except Exception as e:
        return f"Error: {str(e)}"
