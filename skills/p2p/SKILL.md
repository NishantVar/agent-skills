---
name: p2p
description: >-
  P2P messaging between cmux agents: one verb (`send`) for first contact,
  follow-up, and reply. Routes by cmux tab title scoped to the caller's
  workspace; returns a handoff JSON object when a peer needs to be spawned
  or another skill must run.
---

## Parameters

- **my_title**: REQUIRED on the first send for this agent — EXCEPT on inline-bootstrap reply (see step 3), where `--bootstrap-suggested-title` registers you under the title the initiator expects. Pick a snake_case role-reflective title (`qa_lead`, `reviewer`, `builder`, `p2p_tester`, etc.) from your own role context BEFORE calling — do NOT ask the human, and do NOT call-then-react. Drop the flag on subsequent calls; the title is sticky in the manifest for the agent's lifetime. Carve-outs: (a) inline-bootstrap reply — use `--bootstrap-suggested-title` instead; passing `--my-title` here overrides the initiator's expected title and breaks routing. (b) Meaningful spawner-set tab title — if your spawner already set a cmux tab title outside `{claude, claude-code, codex, gemini, shell, bash, zsh, ""}`, you may omit `--my-title` and the helper will adopt the current tab title silently. Default: "".
- **peer**: Cmux tab title of the destination peer. The single routing key — scoped to this agent's workspace by default. Default: "".
- **message**: Message body. Always passed via `--message-file` to side-step shell quoting. Default: "".

## Instructions

### Steps

1. **Send a message to any peer — existing, stale, or unknown — with one call:**
   `python3 ~/.claude/skills/p2p/agent_msg.py send --peer {peer} --my-title {my_title} --message-file <path>`. **Commit to `--my-title` upfront on the first send for this agent** (exception: inline-bootstrap reply — see step 3). You already have the role context you need — pick a snake_case title from it rather than calling first and reacting to `info_needed`. Drop `--my-title` once this agent has registered. Add `--one-way` for fire-and-forget delivery (no reply expected): the wire frame becomes `[from: <me> | one-way] <body>` and the first-contact bootstrap omits the reply request. Add `--workspace <ref>` to scope the title match to a different workspace, or `--workspace all` for global scope. The helper handles registration, title resolution, plain-vs-bootstrap framing, and cross-workspace routing internally.
2. **Read the JSON result on stdout.**
   - `{"ok": true, ...}` → done. The success object reports `title`, `surface`, `resolved_by`, `peer_status` (`live`/`stale`), `kind` (`message`/`bootstrap`), and `one_way`.
   - `{"ok": false, "code": ..., "agent_instruction": ..., ...}` → follow the `agent_instruction` literally. Common cases:
     - `peer_unknown` → the helper has written a spawn payload to `payload_file`. Invoke the **tfork** skill and have it spawn a new agent whose first user-turn prompt is the contents of `payload_file` (use whatever delayed-input mechanism tfork currently exposes — p2p does not name a specific flag).
     - `peer_ambiguous` → rerun with `--peer <title> --peer-surface <candidates[i].ref>` to route by surface directly, or with `--workspace <ref>` to scope the title match to a specific workspace. Bare `surface:N` strings are NOT accepted as `--peer`.
     - `peer_renamed` → no live tab in scope holds the addressed title, but a live surface in scope was previously registered under it (the human likely renamed the tab in cmux). `candidates[i]` carries `current_title`, `former_title`, and `ref`. If the rename signals the same agent under a new label, rerun with `--peer <current_title>` (or `--peer-surface <ref>` to bypass title routing). If the rename signals a role change, treat the destination as a different agent — re-evaluate intent before resending, and if no live tab now fits, fall through to the `peer_unknown` path (spawn via tfork). Never silently retarget; the handoff exists because the rename might be meaningful.
     - `info_needed` with `missing: ["self_title"]` → safety net: you should have passed `--my-title` upfront on the first send. Choose a snake_case role-reflective title from your own context and rerun with `--my-title <t>`. Do NOT ask the human.
     - `title_collision` → another live agent in the workspace already holds that title. Pick a different `--my-title` and rerun.
3. **Receiving a bootstrap inline (one call):** when a `[p2p-bootstrap]` block appears in this agent's user-turn prompt, do NOT register-then-send. Pass the inline values straight to `send` in a single invocation:
   `python3 ~/.claude/skills/p2p/agent_msg.py send --peer <peer_title> --peer-surface <peer_surface> --bootstrap-suggested-title <suggested_title> --message-file <reply.txt>`. The helper registers this agent under `suggested_title` on the fly, skips title resolution because `--peer-surface` is explicit, and routes the reply with plain `[from: <me>]` framing. **Do NOT pass `--my-title` on this path** — code precedence is `--my-title > --bootstrap-suggested-title`, so adding `--my-title` would override the title the initiator expects and break their routing to you. The "REQUIRED on first send" rule in step 1 is satisfied here by `--bootstrap-suggested-title`. If you have the raw bootstrap block in a file, pass `--bootstrap-file <path>` instead — it fills `--peer`, `--peer-surface`, and `--bootstrap-suggested-title` from the parsed text. Use `agent_msg.py parse-incoming` (scrollback scraper) only when the values cannot be read inline.

### Constraints

- **Require:** Pick one snake_case title on the first invocation and keep it for life — peers route by `(workspace, title)`; renaming makes this agent unreachable under the prior title. The helper renames the cmux tab cosmetically to match.
- **Require:** Always use `send` for outgoing messages. Never call `cmux set-buffer`, `cmux paste-buffer`, or `cmux send-key` directly — the helper alone passes `--workspace`, applies the `[from: <me>]` prefix, and uses a per-op buffer name to avoid concurrent-sender interleaving.
- **Avoid:** Never have this skill call `tfork` directly. When a spawn is needed, the helper returns a `peer_unknown` handoff with a pre-written `payload_file`; the calling agent invokes `tfork`. Same rule in reverse.
- **Deprecated:** `--my-name` and `--bootstrap-suggested-name` still work as one-release aliases for `--my-title` / `--bootstrap-suggested-title` (with a stderr warning). Update call sites; the aliases will be removed.
- **Require:** When forking an agent via tfork that you'll message, pass `--title <t>` to tfork — the new tab is renamed before tfork returns, so `send --peer <t>` resolves on the first try.

### Red Flags

Skip these — SKILL.md is the complete interface.

| Thought | Reality |
|---|---|
| "`agent_msg.py list` first" | `send` returns `peer_*` handoffs with everything you need. |
| "Check `--help` for the right flag" | All flags are listed in Parameters. |
| "Read agent_msg.py to understand `send`" | SKILL.md is the contract. |
| "`cmux identify` to know my surface first" | The helper handles it. |
