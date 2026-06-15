"""Run a wrapped skill binary and return its stdout verbatim.

Side effects live here: surface resolution, the p2p temp file, the subprocess.
The server passes `binaries_root` (the skills dir) and `resolve_surface` so
tests can inject a fake binary tree and a deterministic surface.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import jsonrpc

# Resolve the real skills dir through any install symlink. This file is
# skills/flux-mcp/fluxmcplib/gateway.py → parents[2] is skills/.
DEFAULT_BINARIES_ROOT = Path(__file__).resolve().parents[2]


def default_resolve_surface():
    """Resolve the caller's cmux surface via p2p's surface module (spec §5)."""
    p2p_dir = DEFAULT_BINARIES_ROOT / "p2p"
    sys.path.insert(0, str(p2p_dir))
    from p2plib import surface  # noqa: E402
    return surface.my_surface()


def run_tool(tool, args, *, binaries_root=DEFAULT_BINARIES_ROOT,
             resolve_surface=default_resolve_surface, timeout=60):
    """Subprocess `tool`'s binary with `args`; return its stdout (str) verbatim.

    Never raises on a binary handoff: a non-zero exit whose stdout is the
    binary's JSON handoff is returned verbatim (the contract is "the binary's
    JSON, success or handoff"). Only a missing-binary / empty-output failure
    produces a synthesized error object.
    """
    skill, fname = tool["rel_binary"]
    binary = Path(binaries_root) / skill / fname

    surface = None
    try:
        surface = resolve_surface()
    except Exception as exc:  # noqa: BLE001 — never let identity break a call
        jsonrpc.log(f"surface resolution failed: {exc!r}")

    env = dict(os.environ)
    if surface:
        env["AGENT_MSG_SURFACE_ID"] = surface
        env["TFORK_SURFACE_ID"] = surface
    else:
        jsonrpc.log("no surface resolved; binary will self-resolve")

    tmpdir = None
    try:
        tmp_message_file = None
        if tool["name"] == "p2p":
            tmpdir = tempfile.mkdtemp(prefix="flux-mcp-p2p-")
            tmp_message_file = os.path.join(tmpdir, "message.txt")
            with open(tmp_message_file, "w") as fh:
                fh.write(args["message"])
        argv = tool["build_argv"](args, tmp_message_file)
        try:
            proc = subprocess.run(
                ["python3", str(binary), *argv],
                capture_output=True, text=True, env=env, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            jsonrpc.log(f"{fname} timed out after {timeout}s")
            return json.dumps({
                "ok": False, "code": "gateway_timeout",
                "human_message": f"{fname} timed out after {timeout}s.",
            })
        except OSError as exc:
            jsonrpc.log(f"could not spawn {fname}: {exc!r}")
            return json.dumps({
                "ok": False, "code": "gateway_spawn_failed",
                "human_message": f"could not run {fname}: {exc}",
            })
        if proc.stdout.strip():
            return proc.stdout  # verbatim — success OR handoff
        # No stdout → real failure; surface stderr for debugging.
        jsonrpc.log(f"{fname} produced no stdout (rc={proc.returncode}): "
                    f"{proc.stderr.strip()[:500]}")
        return json.dumps({
            "ok": False, "code": "gateway_subprocess_failed",
            "human_message": f"{fname} exited rc={proc.returncode} with no JSON output.",
            "stderr": proc.stderr.strip()[:2000],
        })
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
