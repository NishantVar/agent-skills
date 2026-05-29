---
name: p2p
description: 'P2P messaging between cmux agents: one verb (`send`) handles first contact, follow-up, and reply. Routes by cmux tab title scoped to the caller''s workspace; returns a handoff JSON object when a peer must be spawned or another skill must run.'
---

## Parameters

- **my_title**:
  REQUIRED on first send for this agent EXCEPT on inline-bootstrap reply (see reply_to_inline_bootstrap block). Pick a snake_case role-reflective title (qa_lead, reviewer, builder, etc.) from your own role context BEFORE calling. Drop on subsequent calls; the title is sticky in the manifest. Carve-outs: (a) inline-bootstrap reply uses --bootstrap-suggested-title instead — DO NOT pass --my-title there, it overrides the initiator's expected title and breaks routing; (b) if your spawner already set a meaningful cmux tab title (anything outside {claude, claude-code, codex, gemini, shell, bash, zsh, ""}), you may omit --my-title and the helper will adopt it silently.
  Default: "".
- **peer**: Cmux tab title of the destination peer. Single routing key, scoped to the caller's workspace by default. Default: "".
- **message**: Message body. Always passed via --message-file to side-step shell quoting. Default: "".

## Constraints

- **Require:** Pick one short, lowercase, snake_case title on the first call and keep it for life. Peers route by `(workspace, title)`; renaming mid-session makes this agent unreachable under the prior title. The helper renames the cmux tab cosmetically to match the registered title.
- **Require:** All outgoing messages go through `agent_msg.py send`. Never call `cmux set-buffer`, `cmux paste-buffer`, or `cmux send-key` directly — the helper alone passes `--workspace` (without it cross-workspace delivery fails as `Surface is not a terminal`), applies the `[from: <me>]` prefix, and uses a per-op buffer name to avoid concurrent-sender interleaving.
- **Require:** When the helper returns `ok: false`, the JSON contains an explicit `agent_instruction` field. Follow it verbatim — do not improvise around it. The handoff carries `code`, `human_message`, `agent_instruction`, `action_required`, `handoff_skill`, `rerun_argv`, and `retryable`, plus per-code extras.
- **Require:** When forking an agent via tfork that you'll message, pass `--title <t>` to tfork — the new tab is renamed before tfork returns, so `send --peer <t>` resolves on the first try.
- **Avoid:** This skill never invokes the tfork skill itself. When a spawn is needed, send returns a `peer_unknown` handoff with `handoff_skill: "tfork"` and a pre-written `payload_file`; the calling agent invokes the tfork skill using whatever delayed-input mechanism that skill currently exposes (p2p does not prescribe a flag). Same rule in reverse: tfork never calls p2p.

## Steps

1. Decide which of the following applies and follow only that path:
   If: An inbound `[p2p-bootstrap]` block is in this agent's prompt. Do one `send` call — register + reply in the same invocation.
   a. Follow the reply-to-inline-bootstrap procedure.
   Otherwise:
   a. Write {message} to a temp file like `/tmp/p2p-out-{peer}.txt`. Run `python3 ~/.claude/skills/p2p/agent_msg.py send --peer {peer} --my-title {my_title} --message-file <path>`. COMMIT to --my-title upfront on the first send for this agent (exception: inline-bootstrap reply uses --bootstrap-suggested-title instead — see reply_to_inline_bootstrap block). Pick the snake_case title from your own role context, do not call-then-react to info_needed. Drop --my-title on subsequent invocations; the helper ignores it once a manifest exists. Add `--one-way` for fire-and-forget delivery — the wire frame becomes `[from: <me> | one-way] <body>` and any first-contact bootstrap drops the reply request. Add `--workspace <ref>` to scope the title match to a different workspace, or `--workspace all` for global scope. Parse the JSON on stdout. `{ok: true}` reports `title`, `surface`, `resolved_by`, `kind` (message/bootstrap), and `one_way` — and you are done. Liveness is grounded in the cmux tree: if the peer's tab is open, the peer is reachable and gets a plain framed message (`kind: message`); a bootstrap is sent only on genuine first contact when no manifest exists yet for that surface (`kind: bootstrap`). An idle peer is NOT a fork signal. `{ok: false}` carries `code`, `agent_instruction`, and (per code) extra fields like `payload_file` or `candidates`; only `peer_unknown` (tab gone) means spawn a new peer.
2. If: The helper returned ok:false. Read `agent_instruction` and act.
   a. Follow the follow-handoff-instruction procedure.

### Procedure: reply-to-inline-bootstrap

1. Read `peer_title=` / `peer_surface=` / `suggested_title=` from the inline `[p2p-bootstrap]` block in the user-turn prompt.
2. Write the reply body to a temp file like `/tmp/p2p-out-{peer}.txt`.
3. Run `python3 ~/.claude/skills/p2p/agent_msg.py send --peer <peer_title> --peer-surface <peer_surface> --bootstrap-suggested-title <suggested_title> --message-file <path>`. The helper registers this agent under `suggested_title` on the fly and routes directly without title resolution. DO NOT also pass --my-title here — code precedence is --my-title > --bootstrap-suggested-title, so adding it would override the title the initiator expects and break their routing to this agent. The send_via_helper 'REQUIRED on first send' rule is satisfied here by --bootstrap-suggested-title.
4. If the bootstrap text is in a file rather than inline, pass `--bootstrap-file <path>` instead — it fills --peer, --peer-surface, and --bootstrap-suggested-title from the parsed text. Use `agent_msg.py parse-incoming` (scrollback scraper) only when the values cannot be read inline.

### Procedure: follow-handoff-instruction

1. `peer_unknown` → invoke the tfork skill and have it spawn an agent whose first user-turn input is the contents of `payload_file`. Use whatever delayed-input mechanism tfork currently exposes — p2p does not prescribe a flag. The payload file is already written 0600; do not re-create it.
2. `peer_ambiguous` → rerun with --peer set + --peer-surface <candidates[i].ref> to route by surface directly, or with --workspace <ref> to scope the title match. A bare `surface:N` string is not a valid --peer.
3. `peer_renamed` → no live tab holds the addressed title in scope, but a live surface in scope was previously registered under it (human likely renamed the cmux tab). `candidates[i]` carries `current_title`, `former_title`, `ref`. If the rename signals the same agent under a new label, rerun with --peer <current_title> (or --peer-surface <ref>). If the rename signals a role change, treat the destination as a different agent — re-evaluate intent, and if no live tab now fits, fall through to the peer_unknown path (spawn via tfork). Never silently retarget.
4. `info_needed` with `missing: ["self_title"]` → safety net: you should have passed --my-title upfront on the first send. Choose a snake_case role-reflective title from your own context and rerun with `--my-title <t>`. Do NOT ask the human.
5. `title_collision` → another live agent in the workspace already holds that title. Pick a different --my-title and rerun.
6. `empty_message` → write a non-empty body and rerun.

### Procedure: recover-truncated-peer-message

1. When a teammate's message in your own scrollback is cut off (a piped `grep | head` truncation, a long HOLD that scrolled, etc.), read it directly from the peer's surface instead of guessing or asking. The peer's own tab shows the full body they sent.
2. Get the peer's surface from the prior `send` success object (`surface:N`) or from `agent_msg.py list`.
3. Run `cmux read-screen --surface surface:<N> --lines 3000` and scan the tail for the `[from: <peer>]` block; copy the full body from there.
