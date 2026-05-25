---
name: p2p
description: >-
  P2P messaging between cmux agents: one verb (`send`) for first contact,
  follow-up, and reply. Routes by per-surface manifest; returns a handoff
  JSON object when a peer needs to be spawned or another skill must run.
---

## Parameters

- **my_name**: Optional stable short name to register under on first use. Lowercase snake_case. If empty, the helper auto-derives `agent_<surface_num>` from this agent's surface_ref (e.g., `agent_556`). Subsequent calls ignore this flag and use the existing manifest. Do NOT ask the user to pick a name — auto-default is fine for plumbing. Default: "".
- **peer**: Name or cmux tab title of the destination peer. Manifest name beats tab title; tab title is fallback for first contact. Default: "".
- **message**: Message body. Always passed via `--message-file` to side-step shell quoting. Default: "".

## Instructions

### Steps

1. **Send a message to any peer — existing, stale, or unknown — with one call:**
   `python3 ~/.claude/skills/p2p/agent_msg.py send --peer {peer} --my-name {my_name} --message-file <path>`. Drop `--my-name` once this agent has registered. The helper handles registration, peer resolution, plain-vs-bootstrap framing, and cross-workspace routing internally.
2. **Read the JSON result on stdout.**
   - `{"ok": true, ...}` → done. The success object reports `canonical_name`, `surface`, `resolved_by`, `peer_status` (`live`/`stale`), and `kind` (`message`/`bootstrap`).
   - `{"ok": false, "code": ..., "agent_instruction": ..., ...}` → follow the `agent_instruction` literally. Common cases:
     - `peer_unknown` → the helper has written a spawn payload to `payload_file`. Invoke the **tfork** skill and have it spawn a new agent whose first user-turn prompt is the contents of `payload_file` (use whatever delayed-input mechanism tfork currently exposes — p2p does not name a specific flag).
     - `peer_ambiguous` → either pick the canonical manifest name (unique) or rerun with `--peer <original-or-label> --peer-surface <candidates[i].ref>` to route by surface directly. A bare `surface:N` string is not a valid `--peer`.
     - `info_needed` with `missing: ["self_name"]` → rerun with `--my-name`.
     - `name_collision` / `name_collision_stale` → pick a different name and rerun.
3. **See who you can talk to:** `python3 ~/.claude/skills/p2p/agent_msg.py list`. Returns `{me, peers}` JSON with workspace info and `status` (`live`/`stale`) per agent.
4. **Receiving a bootstrap inline (one call):** when a `[p2p-bootstrap]` block appears in this agent's user-turn prompt, do NOT register-then-send. Pass the inline values straight to `send` in a single invocation:
   `python3 ~/.claude/skills/p2p/agent_msg.py send --peer <peer_name> --peer-surface <peer_surface> --bootstrap-suggested-name <suggested_name> --message-file <reply.txt>`. The helper registers this agent under `suggested_name` on the fly, skips name/tab resolution because `--peer-surface` is explicit, and routes the reply with plain `[from: <me>]` framing. If you have the raw bootstrap block in a file, pass `--bootstrap-file <path>` instead — it fills `--peer`, `--peer-surface`, and `--bootstrap-suggested-name` from the parsed text. Use `agent_msg.py parse-incoming` (scrollback scraper) only when the values cannot be read inline.

### Constraints

- **Require:** Pick one snake_case name on the first invocation and keep it for life — peers route by the manifest's `name` field; renaming makes you unreachable under the prior name.
- **Require:** Always use `send` for outgoing messages. Never call `cmux set-buffer`, `cmux paste-buffer`, or `cmux send-key` directly — the helper alone passes `--workspace`, applies the `[from: <me>]` prefix, and uses a per-op buffer name to avoid concurrent-sender interleaving.
- **Avoid:** Never have this skill call `tfork` directly. When a spawn is needed, the helper returns a `peer_unknown` handoff with a pre-written `payload_file`; the calling agent invokes `tfork`. Same rule in reverse.
