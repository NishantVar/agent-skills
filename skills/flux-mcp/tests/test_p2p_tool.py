import io
import json

from fluxmcplib import server


def _drive(requests, scope, binaries_root, surface="surface:7"):
    """Feed JSON-RPC requests through the server; return parsed responses."""
    stdin = io.StringIO("".join(json.dumps(r) + "\n" for r in requests))
    stdout = io.StringIO()
    server.serve(stdin, stdout, scope=scope, binaries_root=binaries_root,
                 resolve_surface=lambda: surface)
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line]


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}


def test_initialize_returns_protocol_and_server_info(fake_binaries):
    resp = _drive([INIT], "comms", fake_binaries)
    assert resp[0]["id"] == 1
    assert "protocolVersion" in resp[0]["result"]
    assert resp[0]["result"]["serverInfo"]["name"]


def test_tools_list_comms_scope(fake_binaries):
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    resp = _drive([INIT, req], "comms", fake_binaries)
    tools = resp[1]["result"]["tools"]
    assert [t["name"] for t in tools] == ["p2p"]
    assert "build_argv" not in tools[0] and "rel_binary" not in tools[0]


def test_tools_list_orchestrator_scope(fake_binaries):
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    resp = _drive([INIT, req], "orchestrator", fake_binaries)
    assert sorted(t["name"] for t in resp[1]["result"]["tools"]) == \
        ["afork", "p2p", "tfork"]


def test_tools_call_returns_binary_json_verbatim_in_content(fake_binaries):
    call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "p2p",
                       "arguments": {"message": "hello", "peer": "lead"}}}
    resp = _drive([INIT, call], "comms", fake_binaries)
    text = resp[1]["result"]["content"][0]["text"]
    rec = json.loads(text)
    assert rec["message_body"] == "hello"
    assert rec["env_AGENT_MSG_SURFACE_ID"] == "surface:7"


def test_call_to_out_of_scope_tool_is_rejected(fake_binaries):
    call = {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "tfork", "arguments": {"command": "ls"}}}
    resp = _drive([INIT, call], "comms", fake_binaries)
    assert "error" in resp[1]


def test_shell_magic_body_delivered_verbatim(fake_binaries):
    body = 'line1\n$(rm -rf /)\n`whoami`\n"quoted" \'single\''
    call = {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "p2p",
                       "arguments": {"message": body, "peer": "lead"}}}
    resp = _drive([INIT, call], "comms", fake_binaries)
    rec = json.loads(resp[1]["result"]["content"][0]["text"])
    assert rec["message_body"] == body
