import json

from fluxmcplib import gateway, registry


def _run(tool_name, args, binaries_root, surface="surface:42"):
    out = gateway.run_tool(
        registry.TOOLS[tool_name], args,
        binaries_root=binaries_root,
        resolve_surface=lambda: surface,
    )
    return out


def test_returns_binary_stdout_verbatim(fake_binaries):
    raw = _run("p2p", {"message": "hi", "peer": "lead"}, fake_binaries)
    rec = json.loads(raw)
    assert rec["argv"][0] == "send"
    assert "--peer" in rec["argv"] and "lead" in rec["argv"]


def test_injects_resolved_surface_into_both_env_vars(fake_binaries):
    rec = json.loads(_run("p2p", {"message": "hi", "peer": "lead"},
                          fake_binaries, surface="surface:99"))
    assert rec["env_AGENT_MSG_SURFACE_ID"] == "surface:99"
    assert rec["env_TFORK_SURFACE_ID"] == "surface:99"


def test_no_surface_injects_neither(fake_binaries):
    out = gateway.run_tool(
        registry.TOOLS["p2p"], {"message": "hi", "peer": "lead"},
        binaries_root=fake_binaries, resolve_surface=lambda: None,
    )
    rec = json.loads(out)
    assert rec["env_AGENT_MSG_SURFACE_ID"] is None
    assert rec["env_TFORK_SURFACE_ID"] is None


def test_server_owns_p2p_message_tempfile(fake_binaries):
    rec = json.loads(_run("p2p", {"message": "the body", "peer": "x"},
                          fake_binaries))
    assert rec["message_body"] == "the body"
    mf = rec["argv"][rec["argv"].index("--message-file") + 1]
    assert mf not in ("the body", "x")


def test_tfork_command_is_shlex_split_after_dashdash(fake_binaries):
    rec = json.loads(_run("tfork",
                          {"command": "claude --model opus -p 'hi there'"},
                          fake_binaries))
    argv = rec["argv"]
    i = argv.index("--")
    assert argv[i + 1:] == ["claude", "--model", "opus", "-p", "hi there"]


def test_afork_positionals_then_flags(fake_binaries):
    rec = json.loads(_run("afork",
                          {"runtime": "codex", "agent": "reviewer",
                           "permission": "read-only"},
                          fake_binaries))
    assert rec["argv"][:2] == ["codex", "reviewer"]
    assert "--permission" in rec["argv"]
