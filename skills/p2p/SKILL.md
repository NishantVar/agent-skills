---
name: p2p
description: >-
  P2P messaging between cmux agents: one verb (`send`) for first contact,
  follow-up, and reply. Routes by cmux tab title scoped to the caller's
  workspace; returns a handoff JSON object when a peer needs to be spawned
  or another skill must run.
---

## Parameters

- **my_title**: Optional stable short title to register under on first use. Lowercase snake_case. If empty AND the current cmux tab title is generic (`claude`, `codex`, etc.), the helper returns `info_needed`; pick a title that reflects this agent's role (`qa_lead`, `reviewer`, `builder`, etc.) and rerun. Do NOT ask the human — choose from your own role context. Subsequent calls ignore this flag; the title is sticky for the agent's lifetime. Default: "".
- **peer**: Cmux tab title of the destination peer. The single routing key — scoped to this agent's workspace by default. Default: "".
- **message**: Message body. Always passed via `--message-file` to side-step shell quoting. Default: "".

## Instructions

### Steps

1. **Send a message to any peer — existing, stale, or unknown — with one call:**
   `python3 ~/.claude/skills/p2p/agent_msg.py send --peer {peer} --my-title {my_title} --message-file <path>`. Drop `--my-title` once this agent has registered. Add `--one-way` for fire-and-forget delivery (no reply expected): the wire frame becomes `[from: <me> | one-way] <body>` and the first-contact bootstrap omits the reply request. Add `--workspace <ref>` to scope the title match to a different workspace, or `--workspace all` for global scope. The helper handles registration, title resolution, plain-vs-bootstrap framing, and cross-workspace routing internally.
2. **Read the JSON result on stdout.**
   - `{"ok": true, ...}` → done. The success object reports `title`, `surface`, `resolved_by`, `peer_status` (`live`/`stale`), `kind` (`message`/`bootstrap`), and `one_way`.
   - `{"ok": false, "code": ..., "agent_instruction": ..., ...}` → follow the `agent_instruction` literally. Common cases:
     - `peer_unknown` → the helper has written a spawn payload to `payload_file`. Invoke the **tfork** skill and have it spawn a new agent whose first user-turn prompt is the contents of `payload_file` (use whatever delayed-input mechanism tfork currently exposes — p2p does not name a specific flag).
     - `peer_ambiguous` → rerun with `--peer <title> --peer-surface <candidates[i].ref>` to route by surface directly, or with `--workspace <ref>` to scope the title match to a specific workspace. Bare `surface:N` strings are NOT accepted as `--peer`.
     - `info_needed` with `missing: ["self_title"]` → choose a snake_case title that reflects this agent's role (e.g., `reviewer`, `qa_lead`, `builder`) from your own context, then rerun with `--my-title <t>`. Do NOT ask the human.
     - `title_collision` → another live agent in the workspace already holds that title. Pick a different `--my-title` and rerun.
3. **Receiving a bootstrap inline (one call):** when a `[p2p-bootstrap]` block appears in this agent's user-turn prompt, do NOT register-then-send. Pass the inline values straight to `send` in a single invocation:
   `python3 ~/.claude/skills/p2p/agent_msg.py send --peer <peer_title> --peer-surface <peer_surface> --bootstrap-suggested-title <suggested_title> --message-file <reply.txt>`. The helper registers this agent under `suggested_title` on the fly, skips title resolution because `--peer-surface` is explicit, and routes the reply with plain `[from: <me>]` framing. If you have the raw bootstrap block in a file, pass `--bootstrap-file <path>` instead — it fills `--peer`, `--peer-surface`, and `--bootstrap-suggested-title` from the parsed text. Use `agent_msg.py parse-incoming` (scrollback scraper) only when the values cannot be read inline.

### Constraints

- **Require:** Pick one snake_case title on the first invocation and keep it for life — peers route by `(workspace, title)`; renaming makes this agent unreachable under the prior title. The helper renames the cmux tab cosmetically to match.
- **Require:** Always use `send` for outgoing messages. Never call `cmux set-buffer`, `cmux paste-buffer`, or `cmux send-key` directly — the helper alone passes `--workspace`, applies the `[from: <me>]` prefix, and uses a per-op buffer name to avoid concurrent-sender interleaving.
- **Avoid:** Never have this skill call `tfork` directly. When a spawn is needed, the helper returns a `peer_unknown` handoff with a pre-written `payload_file`; the calling agent invokes `tfork`. Same rule in reverse.
- **Deprecated:** `--my-name` and `--bootstrap-suggested-name` still work as one-release aliases for `--my-title` / `--bootstrap-suggested-title` (with a stderr warning). Update call sites; the aliases will be removed.
