---
name: p2p
description: 'P2P messaging between cmux agents: one verb (`send`) handles first contact, follow-up, and reply. Routes first contact by cmux tab title with optional workspace/window scope, then returns a surface ref for follow-up; returns handoff JSON when a peer can''t be resolved. p2p never spawns agents.'
---

## Parameters

- **my_title**:
  REQUIRED on first send for this agent EXCEPT on inline-bootstrap reply (see reply_to_inline_bootstrap block). Pick a snake_case role-reflective title (qa_lead, reviewer, builder, etc.) from your own role context BEFORE calling. Drop on subsequent calls; the title is sticky in the manifest. Carve-outs: (a) inline-bootstrap reply uses --bootstrap-suggested-title instead — DO NOT pass --my-title there, it overrides the initiator's expected title and breaks routing; (b) if your spawner already set a meaningful cmux tab title (anything outside {claude, claude-code, codex, gemini, shell, bash, zsh, ""}), you may omit --my-title and the helper will adopt it silently.
  Default: "".
- **peer**:
  Cmux tab title of the destination peer. First-contact routing key. With no --workspace/--window modifier it resolves with locality: the caller's own workspace first, then other workspaces in the caller's window, then other windows — a single live match at the closest tier wins, two-plus at a tier returns candidates. Explicit modifiers force a single scope. By convention, the first word of an incoming message is treated as the peer's cmux tab title.
  Default: "".
- **workspace**:
  Optional workspace scope for first contact or stale-surface recovery. Use a workspace title, `workspace:N`/UUID, or `all`. A workspace TITLE resolves with the same locality (caller's own workspace, then caller's window, then other windows), so `--peer renderer --workspace HTML` finds the nearest workspace titled HTML with no manual cmux inspection. Omit to let peer-title resolution cascade across the caller's workspace and window.
  Default: "".
- **window**:
  Optional cmux window scope for first contact or stale-surface recovery. Use a window ref/UUID/index, or `all`. Omit when the peer is in the caller's window/workspace.
  Default: "".
- **message**: Message body. Always passed via --message-file to side-step shell quoting. Default: "".

## Constraints

- **Require:** Pick one short, lowercase, snake_case title on the first call and keep it for life. First contact routes by title plus workspace/window scope; successful sends return a `surface` ref that is the exact follow-up pointer. Renaming mid-session makes this agent unreachable under the prior title unless peers re-resolve. The helper renames the cmux tab cosmetically to match the registered title.
- **Require:** All outgoing messages go through `agent_msg.py send`. Never call `cmux set-buffer`, `cmux paste-buffer`, or `cmux send-key` directly — the helper alone passes `--workspace` (without it cross-workspace delivery fails as `Surface is not a terminal`), applies the `[from: <me>]` prefix, and uses a per-op buffer name to avoid concurrent-sender interleaving.
- **Require:** When the helper returns `ok: false`, the JSON contains an explicit `agent_instruction` field. Follow it verbatim — do not improvise around it. The handoff carries `code`, `human_message`, `agent_instruction`, `action_required`, `handoff_skill`, `rerun_argv`, and `retryable`, plus per-code extras.
- **Require:** When forking an agent via tfork (or afork) that you'll message, pass `--title <t>` — the new tab is renamed before the fork returns, so `send --peer <t>` resolves on the first try.
- **Require:** If you receive a p2p message that appears routed to the wrong agent or role, do not silently act on it. Reply to the sender via p2p with a short misroute notice naming your current title/surface and what looked wrong, so the calling agent can update its peer ref or retarget.
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

1. Read `peer_title=` / `peer_surface=` / `peer_workspace=` / `peer_window=` / `suggested_title=` from the inline `[p2p-bootstrap]` block in the user-turn prompt. Older bootstraps may omit peer_workspace / peer_window; use them when present.
2. Write the reply body to a temp file like `/tmp/p2p-out-{peer}.txt`.
3. Run `python3 ~/.claude/skills/p2p/agent_msg.py send --peer <peer_title> --peer-surface <peer_surface> --bootstrap-suggested-title <suggested_title> --message-file <path>`, adding `--workspace <peer_workspace>` and `--window <peer_window>` when the bootstrap supplies them. The helper registers this agent under `suggested_title` on the fly and routes directly without title resolution; if that exact surface has disappeared, it uses the peer title plus workspace/window hints to recover and returns the updated `surface`. DO NOT also pass --my-title here — code precedence is --my-title > --bootstrap-suggested-title, so adding it would override the title the initiator expects and break their routing to this agent. The send_via_helper 'REQUIRED on first send' rule is satisfied here by --bootstrap-suggested-title.
4. If the bootstrap text is in a file rather than inline, pass `--bootstrap-file <path>` instead — it fills --peer, --peer-surface, --workspace, --window, and --bootstrap-suggested-title from the parsed text. Use `agent_msg.py parse-incoming` (scrollback scraper) only when the values cannot be read inline.

### Procedure: send-via-helper

1. Write {message} to a temp file like `/tmp/p2p-out-{peer}.txt`.
2. Run `python3 ~/.claude/skills/p2p/agent_msg.py send --peer {peer} --my-title {my_title} --message-file <path>`. COMMIT to --my-title upfront on the first send for this agent (exception: inline-bootstrap reply uses --bootstrap-suggested-title instead — see reply_to_inline_bootstrap block). Pick the snake_case title from your own role context, do not call-then-react to info_needed. Drop --my-title on subsequent invocations; the helper ignores it once a manifest exists. Add `--one-way` for fire-and-forget delivery — the wire frame becomes `[from: <me> | one-way] <body>` and any first-contact bootstrap drops the reply request. Add `--workspace <value>` and/or `--window <value>` to scope first-contact title matching. `--workspace` accepts a workspace title, `workspace:N`/UUID, or `all`; `--window` accepts a window ref/UUID/index, or `all`. With neither modifier, p2p resolves with locality: the peer title (and a `--workspace` title) is matched in the caller's own workspace first, then in other workspaces of the caller's window, then in other windows — a single live match at the closest tier wins; two-plus at a tier returns candidates rather than silently picking. So `$p2p renderer in HTML` is just `--peer renderer --workspace HTML` and needs nothing but this skill. Title/window/workspace lookups that miss or collide return explicit `*_unknown` / `*_ambiguous` handoffs; pick from the listed candidates and rerun.
3. Parse the JSON on stdout. `{ok: true}` reports `title`, `surface`, `resolved_by`, `kind` (message/bootstrap), and `one_way` — use `surface` for follow-up sends. If you supplied a stale `--peer-surface` that no longer exists but also supplied `--peer`, success may include `previous_surface`; replace your stored ref with the returned `surface`. Liveness is grounded in the cmux tree: if the peer's tab is open, the peer is reachable and gets a plain framed message (`kind: message`); a bootstrap is sent only on genuine first contact when no manifest exists yet for that surface (`kind: bootstrap`). An idle peer is NOT a fork signal. `{ok: false}` carries `code`, `agent_instruction`, and (per code) extra fields like `candidates`. p2p NEVER spawns: a title that matches no live tab returns `peer_not_found` — with sibling agents listed as `candidates` when the scope holds other registered agents (so you can correct a misnamed --peer), or empty when none. You decide whether to retarget or spawn a peer yourself via tfork / afork; the helper never writes a spawn payload.

### Procedure: follow-handoff-instruction

1. `peer_not_found` → no live agent holds the addressed title in scope. p2p does NOT spawn. If `candidates` is non-empty, the scope holds other registered agents under different titles — the addressed `--peer` was almost certainly a misname; rerun with `--peer <candidates[i].title>` (or `--peer-surface <candidates[i].ref>`). Do NOT spawn just because the title missed; that duplicates a live peer. If `candidates` is empty (or none is the intended peer) and you genuinely need a NEW agent, spawn it yourself via the tfork or afork skill (give it `--title <t>`), then `send --peer <t>`.
2. `peer_ambiguous` → rerun with --peer set + --peer-surface <candidates[i].ref> to route by surface directly, or with --window <value> and/or --workspace <value> to scope the title match. A bare `surface:N` string is not a valid --peer.
3. `peer_surface_mismatch` → the `--peer-surface` you passed is live but now holds a different title than your `--peer` (the surface ref is an address; --peer is the identity you asserted). The ref is almost certainly stale — a bootstrap `peer_surface` carried over from an OLDER message, or a tab whose occupant changed in a multi-producer setup. `current_title` reports who is actually there. Do NOT trust the stale ref: rerun WITHOUT --peer-surface, with `--peer <title>` alone, to re-resolve by title; add `--workspace <ref>` / `--window <ref>` if the peer is outside your default scope. Only keep routing to that surface if you genuinely meant the agent now at `current_title`.
4. `workspace_unknown` → the `--workspace <value>` you passed did not match any live workspace. Don't retry verbatim; pick a valid workspace title or ref (or drop --workspace to scope to your own workspace, or pass `all` for global) and rerun.
5. `workspace_ambiguous` → the `--workspace <title>` matched two-plus live workspaces. Pick one of `candidates[i].ref` and rerun with `--workspace <ref>`.
6. `window_unknown` → the `--window <value>` you passed did not match any live window. Don't retry verbatim; pick a valid window ref/UUID/index, drop --window to use the default scope, or pass `--window all` for global window scope.
7. `peer_renamed` → no live tab holds the addressed title in scope, but a live surface in scope was previously registered under it (human likely renamed the cmux tab). `candidates[i]` carries `current_title`, `former_title`, `ref`. If the rename signals the same agent under a new label, rerun with --peer <current_title> (or --peer-surface <ref>). If the rename signals a role change, treat the destination as a different agent — re-evaluate intent, and if no live tab now fits, p2p will return `peer_not_found` (it never spawns); spawn a fresh peer yourself via tfork / afork if you need one. Never silently retarget.
8. `info_needed` with `missing: ["self_title"]` → safety net: you should have passed --my-title upfront on the first send. Choose a snake_case role-reflective title from your own context and rerun with `--my-title <t>`. Do NOT ask the human.
9. `title_collision` → another live agent in the workspace already holds that title. Pick a different --my-title and rerun.
10. `empty_message` → write a non-empty body and rerun.

