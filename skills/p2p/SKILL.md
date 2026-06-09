---
name: p2p
description: 'P2P messaging between cmux agents: one verb (`send`) handles first contact, follow-up, and reply. Routes by cmux tab title scoped to the caller''s workspace; returns a handoff JSON object when a peer can''t be resolved or another skill must run. p2p never spawns agents.'
---

## Parameters

- **my_title**:
  REQUIRED on first send for this agent EXCEPT on inline-bootstrap reply (see reply_to_inline_bootstrap block). Pick a snake_case role-reflective title (qa_lead, reviewer, builder, etc.) from your own role context BEFORE calling. Drop on subsequent calls; the title is sticky in the manifest. Carve-outs: (a) inline-bootstrap reply uses --bootstrap-suggested-title instead — DO NOT pass --my-title there, it overrides the initiator's expected title and breaks routing; (b) if your spawner already set a meaningful cmux tab title (anything outside {claude, claude-code, codex, gemini, shell, bash, zsh, ""}), you may omit --my-title and the helper will adopt it silently.
  Default: "".
- **peer**:
  Cmux tab title of the destination peer. Single routing key, scoped to the caller's workspace by default. By convention, the first word of an incoming message is treated as the peer's cmux tab title.
  Default: "".
- **message**: Message body. Always passed via --message-file to side-step shell quoting. Default: "".

## Constraints

- **Require:** Pick one short, lowercase, snake_case title on the first call and keep it for life. Peers route by `(workspace, title)`; renaming mid-session makes this agent unreachable under the prior title. The helper renames the cmux tab cosmetically to match the registered title.
- **Require:** All outgoing messages go through `agent_msg.py send`. Never call `cmux set-buffer`, `cmux paste-buffer`, or `cmux send-key` directly — the helper alone passes `--workspace` (without it cross-workspace delivery fails as `Surface is not a terminal`), applies the `[from: <me>]` prefix, and uses a per-op buffer name to avoid concurrent-sender interleaving.
- **Require:** When the helper returns `ok: false`, the JSON contains an explicit `agent_instruction` field. Follow it verbatim — do not improvise around it. The handoff carries `code`, `human_message`, `agent_instruction`, `action_required`, `handoff_skill`, `rerun_argv`, and `retryable`, plus per-code extras.
- **Require:** When forking an agent via tfork (or afork) that you'll message, pass `--title <t>` — the new tab is renamed before the fork returns, so `send --peer <t>` resolves on the first try.
- **Avoid:** This skill never spawns agents and never invokes the tfork/afork skills itself. On a title miss it returns a `peer_not_found` handoff (listing sibling `candidates` when the scope has other registered agents) — it does not write a spawn payload. The calling agent decides whether to retarget a candidate or spawn a new peer itself via tfork/afork. Same rule in reverse: tfork never calls p2p.

## Context

- **red-flags**

  Skip these — SKILL.md is the complete interface.

  | Thought | Reality |
  |---|---|
  | "`agent_msg.py list` first" | `send` returns `peer_*` handoffs with everything you need. |
  | "Check `--help` for the right flag" | All flags are listed in Parameters. |
  | "Read agent_msg.py to understand `send`" | SKILL.md is the contract. |
  | "`cmux identify` to know my surface first" | The helper handles it. |

## Steps

1. Decide which of the following applies and follow only that path:
   If An inbound `[p2p-bootstrap]` block is in this agent's prompt. Do one `send` call — register + reply in the same invocation:
   a. Follow the reply-to-inline-bootstrap procedure.
   Otherwise:
   a. Follow the send-via-helper procedure.
2. Decide whether The helper returned ok:false. Read `agent_instruction` and act applies and, if so:
   a. Follow the follow-handoff-instruction procedure.
3. Decide whether A teammate's message in your own scrollback was truncated. Read the full body from the peer's surface applies and, if so:
   a. When a teammate's message in your own scrollback is cut off (a piped `grep | head` truncation, a long HOLD that scrolled, etc.), read it directly from the peer's surface instead of guessing or asking. The peer's own tab shows the full body they sent. Get the peer's surface from the prior `send` success object (`surface:N`). Run `cmux read-screen --surface surface:<N> --lines 3000` and scan the tail for the `[from: <peer>]` block; copy the full body from there.

### Procedure: reply-to-inline-bootstrap

1. Read `peer_title=` / `peer_surface=` / `suggested_title=` from the inline `[p2p-bootstrap]` block in the user-turn prompt.
2. Write the reply body to a temp file like `/tmp/p2p-out-{peer}.txt`.
3. Run `python3 ~/.claude/skills/p2p/agent_msg.py send --peer <peer_title> --peer-surface <peer_surface> --bootstrap-suggested-title <suggested_title> --message-file <path>`. The helper registers this agent under `suggested_title` on the fly and routes directly without title resolution. DO NOT also pass --my-title here — code precedence is --my-title > --bootstrap-suggested-title, so adding it would override the title the initiator expects and break their routing to this agent. The send_via_helper 'REQUIRED on first send' rule is satisfied here by --bootstrap-suggested-title.
4. If the bootstrap text is in a file rather than inline, pass `--bootstrap-file <path>` instead — it fills --peer, --peer-surface, and --bootstrap-suggested-title from the parsed text. Use `agent_msg.py parse-incoming` (scrollback scraper) only when the values cannot be read inline.

### Procedure: send-via-helper

1. Write {message} to a temp file like `/tmp/p2p-out-{peer}.txt`.
2. Run `python3 ~/.claude/skills/p2p/agent_msg.py send --peer {peer} --my-title {my_title} --message-file <path>`. COMMIT to --my-title upfront on the first send for this agent (exception: inline-bootstrap reply uses --bootstrap-suggested-title instead — see reply_to_inline_bootstrap block). Pick the snake_case title from your own role context, do not call-then-react to info_needed. Drop --my-title on subsequent invocations; the helper ignores it once a manifest exists. Add `--one-way` for fire-and-forget delivery — the wire frame becomes `[from: <me> | one-way] <body>` and any first-contact bootstrap drops the reply request. Add `--workspace <value>` to scope the title match to a different workspace — `<value>` may be a workspace title, a ref (`workspace:N` or UUID), or the literal `all` for global scope. Title lookups that match zero or two-plus live workspaces return `workspace_unknown` or `workspace_ambiguous`; pick from the listed candidates and rerun.
3. Parse the JSON on stdout. `{ok: true}` reports `title`, `surface`, `resolved_by`, `kind` (message/bootstrap), and `one_way` — and you are done. Liveness is grounded in the cmux tree: if the peer's tab is open, the peer is reachable and gets a plain framed message (`kind: message`); a bootstrap is sent only on genuine first contact when no manifest exists yet for that surface (`kind: bootstrap`). An idle peer is NOT a fork signal. `{ok: false}` carries `code`, `agent_instruction`, and (per code) extra fields like `candidates`. p2p NEVER spawns: a title that matches no live tab returns `peer_not_found` — with sibling agents listed as `candidates` when the scope holds other registered agents (so you can correct a misnamed --peer), or empty when none. You decide whether to retarget or spawn a peer yourself via tfork / afork; the helper never writes a spawn payload.

### Procedure: follow-handoff-instruction

1. `peer_not_found` → no live agent holds the addressed title in scope. p2p does NOT spawn. If `candidates` is non-empty, the scope holds other registered agents under different titles — the addressed `--peer` was almost certainly a misname; rerun with `--peer <candidates[i].title>` (or `--peer-surface <candidates[i].ref>`). Do NOT spawn just because the title missed; that duplicates a live peer. If `candidates` is empty (or none is the intended peer) and you genuinely need a NEW agent, spawn it yourself via the tfork or afork skill (give it `--title <t>`), then `send --peer <t>`.
2. `peer_ambiguous` → rerun with --peer set + --peer-surface <candidates[i].ref> to route by surface directly, or with --workspace <value> to scope the title match. A bare `surface:N` string is not a valid --peer.
3. `workspace_unknown` → the `--workspace <value>` you passed did not match any live workspace. Don't retry verbatim; pick a valid workspace title or ref (or drop --workspace to scope to your own workspace, or pass `all` for global) and rerun.
4. `workspace_ambiguous` → the `--workspace <title>` matched two-plus live workspaces. Pick one of `candidates[i].ref` and rerun with `--workspace <ref>`.
5. `peer_renamed` → no live tab holds the addressed title in scope, but a live surface in scope was previously registered under it (human likely renamed the cmux tab). `candidates[i]` carries `current_title`, `former_title`, `ref`. If the rename signals the same agent under a new label, rerun with --peer <current_title> (or --peer-surface <ref>). If the rename signals a role change, treat the destination as a different agent — re-evaluate intent, and if no live tab now fits, p2p will return `peer_not_found` (it never spawns); spawn a fresh peer yourself via tfork / afork if you need one. Never silently retarget.
6. `info_needed` with `missing: ["self_title"]` → safety net: you should have passed --my-title upfront on the first send. Choose a snake_case role-reflective title from your own context and rerun with `--my-title <t>`. Do NOT ask the human.
7. `title_collision` → another live agent in the workspace already holds that title. Pick a different --my-title and rerun.
8. `empty_message` → write a non-empty body and rerun.

