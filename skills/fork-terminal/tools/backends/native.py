"""Native terminal backend — AppleScript (macOS), cmd.exe (Windows)."""

import platform
import shlex
import subprocess


def _escape_cwd(cwd: str) -> str:
    """Shell-escape cwd for safe interpolation."""
    return shlex.quote(cwd)


def fork(command: str, cwd: str, split_direction: str) -> str:
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
            return f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}\nreturn_code: {result.returncode}"
        except Exception as e:
            return f"Error: {str(e)}"

    elif system == "Windows":
        full_command = f'cd /d "{cwd}" && {command}'
        subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", full_command], shell=True)
        return "Windows terminal launched"

    else:
        return f"Error: native backend not supported on {system}"
