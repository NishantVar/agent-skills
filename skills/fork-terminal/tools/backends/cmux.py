"""cmux backend — split surface in cmux terminal."""

import re
import shlex
import subprocess
import threading
import time


def _parse_surface_ref(output: str) -> str | None:
    """Parse surface ref (e.g. 'surface:42') from cmux output."""
    match = re.search(r"(surface:\d+)", output)
    return match.group(1) if match else None


def _send_delayed_input(surface_ref: str | None, text: str, delay: float) -> None:
    """Wait for the command to start, then send text to the surface."""
    time.sleep(delay)
    send_cmd = ["cmux", "send"]
    if surface_ref:
        send_cmd += ["--surface", surface_ref]
    send_cmd.append(text)
    subprocess.run(send_cmd, capture_output=True, text=True)
    
    # Wait before hitting enter to avoid race conditions in interactive CLIs
    time.sleep(0.5)
    
    # Press Enter explicitly via send-key (more reliable than trailing newline)
    enter_cmd = ["cmux", "send-key"]
    if surface_ref:
        enter_cmd += ["--surface", surface_ref]
    enter_cmd.append("enter")
    subprocess.run(enter_cmd, capture_output=True, text=True)


def fork(command: str, cwd: str, split_direction: str, delayed_input: str | None = None, delay_seconds: float = 5.0) -> str:
    """Split a new cmux surface and run the command.

    Args:
        split_direction: "right" or "bottom".
        delayed_input: Text to send after the command starts (e.g., a prompt for an interactive CLI).
        delay_seconds: Seconds to wait before sending delayed input.
    """
    direction = "right" if split_direction == "right" else "down"

    try:
        # Create the split
        result = subprocess.run(
            ["cmux", "new-split", direction],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return f"Error: cmux new-split failed: {result.stderr.strip()}"

        # Parse the new surface ref to target the send
        surface_ref = _parse_surface_ref(result.stdout)

        # Send the command to the new surface (cd + command)
        safe_cwd = shlex.quote(cwd)
        full_command = f"cd {safe_cwd} && {command}\n"
        send_cmd = ["cmux", "send"]
        if surface_ref:
            send_cmd += ["--surface", surface_ref]
        send_cmd.append(full_command)

        send_result = subprocess.run(
            send_cmd,
            capture_output=True,
            text=True,
        )
        if send_result.returncode != 0:
            return f"cmux split created but send failed: {send_result.stderr.strip()}"

        # Schedule delayed input if requested
        if delayed_input:
            thread = threading.Thread(
                target=_send_delayed_input,
                args=(surface_ref, delayed_input, delay_seconds),
            )
            thread.start()
            thread.join(timeout=delay_seconds + 10)

        ref_info = f" [ref={surface_ref}]" if surface_ref else ""
        delayed_info = f" [delayed input sent after {delay_seconds}s]" if delayed_input else ""
        return f"cmux surface split ({split_direction}): OK{ref_info}{delayed_info}"
    except FileNotFoundError:
        return "Error: cmux is not installed or not in PATH"
    except Exception as e:
        return f"Error: {str(e)}"
