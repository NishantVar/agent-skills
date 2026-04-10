"""Native terminal backend — AppleScript (macOS), cmd.exe (Windows)."""

import platform
import shlex
import subprocess
import tempfile
import threading
import time


def _escape_cwd(cwd: str) -> str:
    """Shell-escape cwd for safe interpolation."""
    return shlex.quote(cwd)


def _send_delayed_input_macos(delayed_input: str, delay_seconds: float) -> None:
    """Send delayed input to the frontmost Terminal window via AppleScript."""
    time.sleep(delay_seconds)
    # Write input to a temp file and use osascript to type it keystroke-by-keystroke
    # We use 'keystroke' to simulate typing into the active Terminal window
    escaped = delayed_input.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        'tell application "Terminal"\n'
        "  activate\n"
        f'  delay 0.5\n'
        "end tell\n"
        'tell application "System Events"\n'
        '  tell process "Terminal"\n'
        f'    keystroke "{escaped}"\n'
        '    keystroke return\n'
        "  end tell\n"
        "end tell"
    )
    subprocess.run(["osascript", "-e", script], capture_output=True, text=True)


def fork(command: str, cwd: str, split_direction: str, delayed_input: str | None = None, delay_seconds: float = 5.0) -> str:
    """Open a new native terminal window and run the command.

    split_direction is ignored — native always opens a new window.
    """
    system = platform.system()
    safe_cwd = _escape_cwd(cwd)

    if system == "Darwin":
        shell_command = f"cd {safe_cwd} && {command}"
        escaped_shell_command = shell_command.replace("\\", "\\\\").replace('"', '\\"')
        try:
            result = subprocess.run(
                ["osascript", "-e", f'tell application "Terminal" to do script "{escaped_shell_command}"'],
                capture_output=True,
                text=True,
            )

            if delayed_input:
                thread = threading.Thread(
                    target=_send_delayed_input_macos,
                    args=(delayed_input, delay_seconds),
                    daemon=True,
                )
                thread.start()
                thread.join(timeout=delay_seconds + 10)

            return f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}\nreturn_code: {result.returncode}"
        except Exception as e:
            return f"Error: {str(e)}"

    elif system == "Windows":
        full_command = f'cd /d "{cwd}" && {command}'
        subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", full_command], shell=True)
        return "Windows terminal launched"

    else:
        return f"Error: native backend not supported on {system}"
