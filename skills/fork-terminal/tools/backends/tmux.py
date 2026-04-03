"""tmux backend — split pane in current tmux session."""

import os
import shlex
import subprocess


def fork(command: str, cwd: str, split_direction: str) -> str:
    """Split a new tmux pane and run the command.

    Args:
        split_direction: "right" for vertical split (-h), "bottom" for horizontal split (-v).
    """
    if not os.environ.get("TMUX"):
        return "Error: not inside a tmux session. Start tmux first or use a different backend."

    flag = "-h" if split_direction == "right" else "-v"

    try:
        safe_cwd = shlex.quote(cwd)
        shell_command = f"cd {safe_cwd} && {command}; exec $SHELL"
        result = subprocess.run(
            ["tmux", "split-window", flag, "-P", "-F", "#{pane_id}", "sh", "-c", shell_command],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return f"Error: tmux split-window failed: {result.stderr.strip()}"
        pane_id = result.stdout.strip()
        ref_info = f" [ref={pane_id}]" if pane_id else ""
        return f"tmux pane split ({split_direction}): OK{ref_info}"
    except FileNotFoundError:
        return "Error: tmux is not installed or not in PATH"
    except Exception as e:
        return f"Error: {str(e)}"
