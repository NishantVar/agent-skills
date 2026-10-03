"""Exact-target one-way delivery over cmux v2, without processes or registry.

The cmux CLI's set-buffer and rpc accept payloads only in argv. Use its
newline-delimited Unix socket protocol here to keep body text out of argv.
The stable cmux socket defaults need no pane or configuration discovery.
"""
from __future__ import annotations

import json
import os
import pwd
from pathlib import Path
import re
import socket
import stat
import time
import uuid


class CmuxError(RuntimeError):
    pass


def _socket_paths(socket_path: str | None) -> list[str]:
    if socket_path is not None:
        return [socket_path]
    # cmux CLI CLISocketPathResolver.stableImplicitDefaultPaths(), in order.
    # Resolve account home as cmux does, independently of a pane's environment.
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    state = home / ".local/state/cmux"
    return [str(state / "cmux.sock"), "/tmp/cmux.sock",
            str(state / f"cmux-{os.getuid()}.sock"),
            f"/tmp/cmux-{os.getuid()}.sock"]


def _connect(socket_path: str | None):
    for path in _socket_paths(socket_path):
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            info = os.stat(path)
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise OSError("not an owned cmux socket")
            connection.settimeout(5)
            connection.connect(path)
            return connection
        except OSError:
            connection.close()
    raise CmuxError("no reachable owned cmux socket")


def _rpc(stream, method: str, params: dict) -> dict:
    request_id = str(uuid.uuid4())
    request = {"id": request_id, "method": method, "params": params}
    stream.write((json.dumps(request) + "\n").encode("utf-8"))
    stream.flush()
    line = stream.readline(8 * 1024 * 1024)
    if not line.endswith(b"\n"):
        raise CmuxError("incomplete cmux response")
    response = json.loads(line)
    if not isinstance(response, dict) or response.get("id") != request_id:
        raise CmuxError("invalid cmux response")
    if response.get("ok") is not True:
        raise CmuxError("cmux rejected request")
    result = response.get("result")
    if not isinstance(result, dict):
        raise CmuxError("invalid cmux result")
    return result


def _target(tree: dict, workspace: str, peer_surface: str):
    # Never recover an absent pointer by title or use a focused target.
    for window in tree["windows"]:
        for ws in window["workspaces"]:
            if workspace not in (ws.get("ref"), ws.get("id")):
                continue
            for pane in ws["panes"]:
                for surf in pane["surfaces"]:
                    if peer_surface in (surf.get("ref"), surf.get("id")):
                        return window, ws, surf
    return None


def send_one_way(*, sender: str, peer_surface: str, workspace: str,
                 expected_title: str, message_file: str,
                 socket_path: str | None = None) -> dict:
    """Return only delivered / surface_missing / title_mismatch / error.

    A delivered result means cmux accepted the text and Enter, not that
    the receiving agent processed it. Transport failures may follow a
    partial paste; callers must not assume an error is safe to replay.
    """
    try:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", sender):
            raise ValueError("invalid sender")
        if not expected_title or socket_path == "":
            raise ValueError("missing input")
        for value, stem in ((peer_surface, "surface"), (workspace, "workspace")):
            if not re.fullmatch(stem + r":[0-9]+", value):
                uuid.UUID(value)  # Exact UUIDs are also accepted; no titles/indexes.
        with Path(message_file).open(encoding="utf-8", newline="") as body_file:
            body = body_file.read()
        if not body.strip():
            raise ValueError("empty body")
        with _connect(socket_path) as connection:
            with connection.makefile("rwb") as stream:
                tree = _rpc(stream, "system.tree", {"all_windows": True})
                target = _target(tree, workspace, peer_surface)
                if target is None:
                    return {"ok": False, "code": "surface_missing"}
                window, ws, surf = target
                if surf.get("title") != expected_title:
                    return {"ok": False, "code": "title_mismatch"}
                if surf.get("type") != "terminal":
                    raise ValueError("target is not a terminal")
                # Pin UUIDs from the checked snapshot, rather than recycled refs.
                route = {"window_id": window["id"], "workspace_id": ws["id"],
                         "surface_id": surf["id"]}
                for value in route.values():
                    if not isinstance(value, str):
                        raise ValueError("invalid route UUID")
                    uuid.UUID(value)
                text = f"[from: {sender} | one-way] {body}"
                for offset in range(0, len(text), 1000):
                    _rpc(stream, "surface.send_text",
                         {**route, "text": text[offset:offset + 1000]})
                    time.sleep(0.3)
                _rpc(stream, "surface.send_key", {**route, "key": "enter"})
        return {"ok": True, "code": "delivered"}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, CmuxError):
        # Do not echo response payloads, body text, or configuration into errors.
        return {"ok": False, "code": "error"}
