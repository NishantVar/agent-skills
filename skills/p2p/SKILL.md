---
name: p2p
description: 'P2P messaging between cmux agents using inline-prompt transport over cmux set-buffer/paste-buffer. Per-surface manifest routing; fire-and-forget.'
---

## Parameters

- **my_name**:
  Stable short name this agent should be registered under. Lowercase snake_case. If empty, pick a name from the agent's role and confirm with the user when ambiguous.
  Default: "".
- **peer_name**: Name of the peer to spawn, connect to, or send a message to. Default: "".
- **peer_tab**: Cmux tab title to search for when the peer is identified by tab rather than by a previously-registered name. Default: "".
- **message**: Optional message body. For spawn or connect, becomes the first message sent. For a plain send, the full content. Default: "".

## Instructions

### Context

- **transport-model**

  Communication uses `cmux set-buffer` + `cmux paste-buffer` so messages of any size go through without shell ARG_MAX truncation. Sending is fire-and-forget: replies arrive in this agent's terminal as fresh `[from: <peer_name>] ...` user-turn lines and are picked up on the agentic CLI's next turn — there is no polling and no synchronous wait.

- **registry-model**

  Each agent's identity lives in a per-surface manifest at `~/.cmux/agents/by-surface/<surface_ref>.json` containing `{name, surface_ref, started_at}`. The cmux tab title is renamed cosmetically to match, but it is not the authoritative routing key. Stale manifests (whose surface_ref no longer appears in `cmux tree --all`) are reaped lazily by any agent that enumerates the registry — no daemon or cleanup hook is required.

- **bootstrap-protocol**

  Bootstrap messages are tagged `[p2p-bootstrap]` and carry `peer_name=`, `peer_surface=`, optional `suggested_name=`, and an optional `First message from <name>: ...` line. A receiving agent reads the tag in its prompt or scrollback, invokes this skill, registers itself, and is then reachable.

### Steps

1. Run `python3 ~/.claude/skills/p2p/tools/agent_msg.py whoami`. If it exits 0 the agent is already registered; the JSON on stdout has the current name. Remember the name and end this block. If whoami exits non-zero, choose a short, lowercase, snake_case name for this agent. Prefer the user-supplied {my_name} when non-empty. Otherwise pick one that reflects the agent's role (`reviewer`, `planner`, `worker_a`); confirm with the user when the role is ambiguous. Run `python3 ~/.claude/skills/p2p/tools/agent_msg.py register --name <chosen_name>`. The helper writes the per-surface manifest, renames the cmux tab cosmetically, and exits 0 on success. On a name-collision error, pick a different name and retry.
2. Decide which of the following applies and follow only that path:
   If The current user prompt or recent scrollback contains a literal `[p2p-bootstrap]` tag — a peer is opening a connection and expects this agent to register itself and acknowledge:
   a. Run `python3 ~/.claude/skills/p2p/tools/agent_msg.py parse-incoming`. The helper scans the agent's most recent scrollback for the bootstrap block and prints `{peer_name, peer_surface, suggested_name}` as JSON. If the helper exits non-zero, abort and report that no bootstrap was found. The peer is already registered on its own side (it must have been, to send the bootstrap), so no additional registration is needed for the peer. `ensure_self_registered` has already handled this side. If the bootstrap text included a `First message from <peer_name>: ...` line, surface that message to the user verbatim (with the `[from: <peer_name>]` framing) and ask whether to reply. If there is no first message, just confirm the connection is live and report the peer's name.
   If The user wants to launch a brand-new agent in a new cmux surface and begin a conversation with it:
   a. Follow the spawn-new-peer procedure.
   If The user wants to start talking to an agent already running in cmux, identified by its tab title or by a previously-registered name:
   a. Follow the connect-to-existing-peer procedure.
   If The user wants this agent to send a message to a peer it is already connected to (or wants to reply to a `[from: <name>] ...` line in the conversation):
   a. Identify the destination peer name. Prefer {peer_name} when supplied. Otherwise read the most recent `[from: <name>] ...` line in the conversation and treat that name as the destination. Write the message body to a temp file (for example `/tmp/agent-msg-out-<peer>.txt`) to side-step any shell quoting concerns. Then run `python3 ~/.claude/skills/p2p/tools/agent_msg.py send --peer <peer_name> --message-file <path>`. The helper looks the peer up in the manifest registry, prefixes the body with `[from: <my_name>]`, and delivers via set-buffer/paste-buffer. Do not wait for a reply. Any reply arrives later as a fresh `[from: <peer_name>] ...` user-turn line and will be picked up naturally on the agent's next turn.
   If The user wants to see what peers this agent is currently aware of:
   a. Run `python3 ~/.claude/skills/p2p/tools/agent_msg.py list-peers`. The helper sweeps stale manifests (surface no longer in cmux) and prints the live peer list as JSON: `[{name, surface_ref, started_at}, ...]`. Summarize the result for the user — peer names and their cmux surfaces.
   Otherwise:
   a. Ask the user to clarify: are they trying to spawn a new peer, connect to an existing one, send a message to a known peer, or list known peers?

### Constraints

- **Require:** Pick exactly one short, lowercase, snake_case name on the first invocation and keep it for the lifetime of this agent. Never rename mid-session — peers route by the manifest's `name` field, so changing it makes you unreachable under your old name.
- **Require:** Every outgoing message must carry a `[from: <my_name>]` prefix. Always send through `agent_msg.py send` so the prefix is applied and the cmux set-buffer / paste-buffer transport is used. Never `cmux send` raw text directly to a peer surface.
- **Avoid:** Routing is by the per-surface manifest's `name` field, not the cmux tab title. Always re-resolve a peer through `agent_msg.py resolve` (or by reading the registry) before sending — a renamed or stale tab title must never be trusted as the routing key.

### Procedure: spawn-new-peer

1. Decide which agentic CLI the new peer will run (Claude Code, Codex, Gemini). Confirm with the user when not stated. Pick a short snake_case name for the new peer; prefer {peer_name} when supplied.
2. Generate the bootstrap payload: `python3 ~/.claude/skills/p2p/tools/agent_msg.py bootstrap-payload --target-name <peer_name>` plus `--message <first_message>` when the user wants to send an opening line ({message} carries it). Write the helper's stdout to a temp file such as `/tmp/agent-msg-bootstrap-<peer_name>.txt`.
3. Hand the spawn itself off to the fork-terminal skill. Pass `--delayed-input-file <bootstrap_file>` and `--delay 5` so the new agent's first user-turn prompt is the bootstrap text. Let fork-terminal pick the launcher (claude/codex/gemini) per its own rules.
4. Do not wait for the new peer to come up. The new peer will register itself, parse the bootstrap, and reply when ready. Replies arrive in this agent's terminal as fresh `[from: <peer_name>] ...` user-turn lines.

### Procedure: connect-to-existing-peer

1. Resolve the target surface. Run `python3 ~/.claude/skills/p2p/tools/agent_msg.py resolve --peer <name_or_tab> --fallback-tab`. The helper first checks the manifest registry by name; if no match, it falls back to matching the cmux tab title. Capture the surface_ref it prints. Prefer {peer_name} over {peer_tab} when both are present, falling back to {peer_tab} otherwise.
2. Compose the optional opening line from the user's request. {message} carries it when supplied.
3. Run `python3 ~/.claude/skills/p2p/tools/agent_msg.py bootstrap --peer-surface <surface_ref>` plus `--message <opening_line>` when applicable. The helper sends the tagged bootstrap into the target surface via set-buffer/paste-buffer. The target agent's coding CLI will see it as a user-turn prompt; it is expected to invoke this skill, register itself, and reply.
4. If the target was matched only by tab title (not by an existing manifest), tell the user that the target agent has not been seen on the messaging registry before — it will need to invoke this skill to participate, which the bootstrap text instructs it to do.

