"""MCP stdio dispatch: initialize / tools/list / tools/call. No chaining."""

from __future__ import annotations

import sys

from . import gateway, jsonrpc, registry

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "flux", "version": "0.1.0"}


def _result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle(req, *, scope, binaries_root, resolve_surface):
    """Return a response dict, or None for notifications."""
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        return _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        tools = [registry.public_tool(t) for t in registry.tools_for_scope(scope)]
        return _result(req_id, {"tools": tools})
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        allowed = {t["name"] for t in registry.tools_for_scope(scope)}
        if name not in allowed:
            return _error(req_id, -32602,
                          f"tool {name!r} not available in scope {scope!r}")
        raw = gateway.run_tool(
            registry.TOOLS[name], params.get("arguments") or {},
            binaries_root=binaries_root, resolve_surface=resolve_surface,
        )
        return _result(req_id, {"content": [{"type": "text", "text": raw}],
                                "isError": False})
    if req_id is not None:
        return _error(req_id, -32601, f"method not found: {method}")
    return None


def serve(stdin, stdout, *, scope, binaries_root=gateway.DEFAULT_BINARIES_ROOT,
          resolve_surface=gateway.default_resolve_surface):
    try:
        for req in jsonrpc.iter_requests(stdin):
            try:
                resp = handle(req, scope=scope, binaries_root=binaries_root,
                              resolve_surface=resolve_surface)
            except Exception as exc:  # noqa: BLE001
                jsonrpc.log(f"handler error: {exc!r}")
                resp = _error(req.get("id"), -32603, f"internal: {exc!r}")
            if resp is not None:
                jsonrpc.send(stdout, resp)
    except BrokenPipeError:
        # Client closed the pipe (session ended). Exit quietly.
        jsonrpc.log("stdout closed (client gone); exiting")


def main(scope):
    jsonrpc.log(f"started scope={scope} python={sys.executable}")
    serve(sys.stdin, sys.stdout, scope=scope)
    return 0
