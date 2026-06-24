"""Declarative tool table: MCP schema + how to build each binary's argv.

No I/O here. The gateway owns subprocessing, the temp file, and surface env.
`rel_binary` is resolved against the skills dir by the gateway so the same
table works in the repo and the installed (symlinked) layout.
"""

from __future__ import annotations

import shlex


def _p2p_argv(args, tmp_message_file):
    # The gateway has already written `message` to tmp_message_file.
    argv = ["send", "--message-file", tmp_message_file]
    if args.get("peer"):
        argv += ["--peer", args["peer"]]
    if args.get("peer_surface"):
        argv += ["--peer-surface", args["peer_surface"]]
    if args.get("my_title"):
        argv += ["--my-title", args["my_title"]]
    if args.get("bootstrap_suggested_title"):
        argv += ["--bootstrap-suggested-title", args["bootstrap_suggested_title"]]
    if args.get("workspace"):
        argv += ["--workspace", args["workspace"]]
    if args.get("one_way"):
        argv += ["--one-way"]
    return argv


def _afork_argv(args, tmp_message_file):
    argv = [args["runtime"]]
    if args.get("agent"):
        argv += [args["agent"]]
    for key, flag in (("permission", "--permission"), ("model", "--model"),
                      ("effort", "--effort"), ("title", "--title"),
                      ("cwd", "--cwd"), ("placement", "--placement")):
        if args.get(key):
            argv += [flag, args[key]]
    if args.get("allow_unenforced"):
        argv += ["--allow-unenforced"]
    return argv


def _tfork_argv(args, tmp_message_file):
    # Flags FIRST, then `--`, then the command tokens. The command string is a
    # shell command line; shlex.split reproduces the argv the caller's shell
    # would have produced (run_fork classifies token[0] and shlex.join's them).
    argv = []
    for key, flag in (("placement", "--placement"), ("anchor", "--anchor"),
                      ("workspace", "--workspace"), ("cwd", "--cwd"),
                      ("type_override", "--type"), ("title", "--title")):
        if args.get(key):
            argv += [flag, args[key]]
    argv += ["--"] + shlex.split(args["command"])
    return argv


TOOLS = {
    "p2p": {
        "name": "p2p",
        "description": (
            "Message a peer agent by its cmux tab title. The server writes the "
            "message body to a temp file and calls p2p's agent_msg.py verbatim; "
            "returns p2p's JSON (including peer_not_found / peer_ambiguous "
            "handoffs). Does not spawn or chain."
        ),
        "rel_binary": ("p2p", "agent_msg.py"),
        "build_argv": _p2p_argv,
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string",
                            "description": "Message body (sent verbatim)."},
                "peer": {"type": "string",
                         "description": "Destination peer's cmux tab title."},
                "peer_surface": {"type": "string",
                                 "description": "Route directly by surface ref (surface:N)."},
                "my_title": {"type": "string",
                             "description": "This agent's snake_case title (first send only)."},
                "bootstrap_suggested_title": {"type": "string",
                                              "description": "Title to register under when replying to an inline bootstrap."},
                "workspace": {"type": "string",
                              "description": "Scope the title lookup to another workspace (title, ref, or 'all')."},
                "one_way": {"type": "boolean",
                            "description": "Fire-and-forget; drops the reply request."},
            },
            "required": ["message"],
            "additionalProperties": False,
        },
    },
    "afork": {
        "name": "afork",
        "description": (
            "Prepare an agent fork command (does NOT fork). Runs afork.py and "
            "returns its JSON (ready_to_fork or a failure handoff) verbatim. "
            "The agent then passes the command to tfork."
        ),
        "rel_binary": ("afork", "afork.py"),
        "build_argv": _afork_argv,
        "inputSchema": {
            "type": "object",
            "properties": {
                "runtime": {"type": "string",
                            "enum": ["codex", "claude", "pi", "antigravity"],
                            "description": "Target coding-agent runtime."},
                "agent": {"type": "string",
                          "description": "Optional named agent definition."},
                "permission": {"type": "string"},
                "model": {"type": "string"},
                "effort": {"type": "string"},
                "title": {"type": "string",
                          "description": "cmux tab title for the forked agent."},
                "cwd": {"type": "string"},
                "placement": {"type": "string"},
                "allow_unenforced": {"type": "boolean"},
            },
            "required": ["runtime"],
            "additionalProperties": False,
        },
    },
    "tfork": {
        "name": "tfork",
        "description": (
            "Fork a new cmux terminal/agent pane running the given command. "
            "Runs fork_terminal.py and returns its JSON verbatim."
        ),
        "rel_binary": ("tfork", "fork_terminal.py"),
        "build_argv": _tfork_argv,
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string",
                            "description": "Shell command line to run in the new pane."},
                "placement": {"type": "string",
                              "description": "right|left|top|bottom|new-workspace."},
                "anchor": {"type": "string",
                           "description": "Surface ref or tab title to place next to."},
                "workspace": {"type": "string"},
                "cwd": {"type": "string"},
                "type_override": {"type": "string", "enum": ["agent", "command"]},
                "title": {"type": "string"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}

SCOPES = {
    "comms": ["p2p"],
    "orchestrator": ["p2p", "afork", "tfork"],
}


def tools_for_scope(scope):
    if scope not in SCOPES:
        raise ValueError(f"unknown scope: {scope!r} (expected {sorted(SCOPES)})")
    return [TOOLS[name] for name in SCOPES[scope]]


def public_tool(tool):
    """Strip internal keys before sending in a tools/list response."""
    return {k: tool[k] for k in ("name", "description", "inputSchema")}
