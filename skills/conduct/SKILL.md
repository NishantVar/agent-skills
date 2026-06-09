---
name: conduct
description: 'cmux control plane for an orchestrating agent: read fleet status (per-agent context% + runtime + state) in a single call and issue runtime-aware lifecycle control (clear/compact/exit/kill/interrupt) over the agents you own. Ownership is implicit first-touch, exclusive, orphan-reclaim, keyed on the durable cmux surface UUID. Reads and control are scoped to the caller''s owned set only — never an ungated workspace/all broadcast. Never spawns (tfork''s job), never messages (p2p''s job), and never shells out to another skill; fails closed on unknown runtimes and unsupported verbs rather than injecting blindly.'
---

## Parameters

- **verb** (Verb):
  The conduct verb, positional-1. One of: status, claim, register, release, clear, compact, exit, kill, interrupt. status reads context%/state; claim / register / release manage ownership; clear / compact / exit / kill / interrupt inject runtime-aware lifecycle control.
  Required.
- **agent**:
  The target surface for a single-agent verb: a surface:N short ref (resolved to a durable UUID at call time) OR a surface UUID directly. Passed as --agent <ref>. Required for every single-target verb; omit on register (uses --from-fork) and on the --all form.
  Default: none.
- **all**:
  Operate over your OWNED SET only — the agents you orchestrate, never an ungated workspace/all broadcast. Valid on status and every lifecycle verb. Passed as --all.
  Default: false.
- **from_fork**:
  register only: tfork's result JSON, inline or as a file path. conduct reads its `session: surface:N` field and claims that surface. A decoupled alias of claim — conduct does not invoke tfork. Passed as --from-fork <tfork-json>.
  Default: none.

## Context

- **binary-contract**

  conduct.py is deterministic and self-contained, and exposes nine verbs, each printing exactly one JSON envelope: status, claim, register, release, clear, compact, exit, kill, interrupt. Invoke as python3 <skill-dir>/scripts/conduct.py <verb> [--agent <ref> | --all] [--from-fork <json>].
  - Identity is keyed on the cmux surface UUID, NOT surface:N. The short ref reindexes; the UUID is durable across workspace/window moves, so control never silently retargets. --agent accepts a surface:N (resolved to a UUID at call time) or a UUID directly. The caller's own UUID (from $CMUX_SURFACE_ID, fallback `cmux identify`) is the candidate OWNER — whoever runs a verb is the candidate owner.
  - status [--agent <ref> | --all]: the headline read. --agent reads one surface's live context_pct + runtime type + state + title + current workspace AND first-touches (claims) it. --all returns the same per-agent rows for your whole owned set in one call. context_pct is the percent of the context window USED (higher = closer to full): claude's `ctx:NN%` status line is already "used", and codex's `Context NN% left` footer is converted (100 - left) to the same "used" meaning; pi and runtimes that expose no indicator report null. state is a coarse signal — "busy" when the runtime shows an interrupt affordance ("esc to interrupt"), else null; fine-grained idle / needs-input / error classification belongs to the watchdog / observability skills, not conduct. Workspace is a derived field recomputed live, never stored, so it stays correct across moves.
  - claim --agent <ref>: eager explicit ownership without a control verb. register --from-fork <tfork-json>: a decoupled alias of claim that reads tfork's `session: surface:N` field from its result JSON (inline or a file path) and claims that surface — the spawn->own bridge. release --agent <ref>: drop a claim; required for ownership transfer and clean teardown.
  - clear / compact / exit / kill / interrupt [--agent <ref> | --all]: runtime-aware lifecycle control. conduct identifies the target's runtime via `cmux top` and maps the verb to that runtime's real keystroke sequence (a per-runtime adapter, afork-style — e.g. claude `/clear` then Enter, interrupt = Esc, kill = close the pane). Injection uses cmux send / send-key (`cmux send` does NOT auto-press Enter, so conduct follows text with send-key Enter). Verbs are ATOMIC — no implicit interrupt-then-clear.
  - Every verb runs the first-touch ownership algorithm under an advisory file lock against ~/.conduct/owners.json (keyed target_uuid -> {owner_uuid, claimed_at}): an unowned OR orphaned (recorded owner's pane gone from the live cmux tree) surface is CLAIMED for the caller; an already-mine surface passes; a surface live-owned by someone else fails closed (owned_by_other / not_owner — no steal). Touching to read IS the claim.
  - The envelope is always {ok, code, human_message, agent_instruction, action_required, handoff_skill, rerun_argv, retryable} plus per-code extras. On ok:false, agent_instruction is authoritative — follow it verbatim. conduct makes ONLY cmux calls; it never invokes afork / tfork / p2p, and resolves human titles from live cmux topology, not p2p's manifest.

- **ownership-model**

  Ownership is implicit first-touch, exclusive, and orphan-reclaim — there is no separate registration step required.
  - First-touch: the first conduct operation (read OR control) a caller issues against an unowned surface claims it for that caller. status --agent <ref> is the usual claim path — touching to read IS the claim.
  - Exclusive: one owner per agent. A first-touch on a surface already live-owned by someone else fails closed (owned_by_other) and names the current owner; conduct never steals.
  - Orphan-reclaim: if the recorded owner's surface UUID is no longer in the live cmux tree (the owner pane closed), the claim is stale and the next toucher reclaims it automatically.
  - Spawner-becomes-owner is EMERGENT, not coded: the orchestrator holds the surface:N from its own tfork, so it is always the first to touch and always wins the claim — with zero coupling to afork / tfork (neither writes conduct's manifest or knows conduct exists). conduct attributes ownership to the caller; the spawner just happens to touch first.
  - Hierarchy falls out naturally: A owns B, B owns C — exclusive single-owner edges compose into a tree. Reads and control are owned-set-only; you can only see and act on the agents you own.
  - Ownership survives workspace/window moves untouched because it is keyed on the durable surface UUID — only the surface:N alias and workspace_ref change, and conduct recomputes those live.

- **handoff-codes**

  On ok:false the envelope's `code` tells you what happened; `agent_instruction` tells you what to do. The codes:
  - not_in_cmux (not retryable): conduct could not resolve the caller's own surface UUID, so there is no owner identity. Terminal — run conduct from inside a cmux pane, or export CMUX_SURFACE_ID before launching the agent.
  - target_unknown (retryable): --agent matched no live surface — the surface:N alias reindexed or the pane is gone. Re-resolve the target (cmux tree) and rerun with a live ref or the UUID.
  - owned_by_other (not retryable): the surface is live-owned by another caller. No steal — for a transfer, the current owner must release first; an orphaned (dead-owner) claim self-reclaims on the next touch.
  - not_owner (not retryable): a control or release verb was issued against a surface you do not own and cannot first-touch. First-touch via status --agent to claim an unowned/orphaned surface, or operate on one you already own.
  - runtime_unknown (not retryable): no supported coding-agent runtime (claude / codex / pi) was detected on the target — conduct refuses to inject keystrokes blindly. Verify the pane is actually running a supported agent (not a shell / editor / REPL).
  - verb_unsupported (not retryable): the detected runtime has no keystroke mapping for this verb. Use a verb that runtime supports, or handle the action manually — do NOT improvise a keystroke.
  - cmux_failed (retryable): a cmux call failed mid-operation. Inspect cmux state (daemon up? surface still live?) and rerun.
  - bad_arguments (not retryable): invalid invocation. Fix the flags and call again.

## Constraints

- **Must:** Identity is the durable cmux surface UUID, never the surface:N alias. Pass --agent surface:N for convenience (conduct resolves it to a UUID at call time) or a UUID directly for durability, but never assume a surface:N is stable across calls — it can reindex, and ownership / control are keyed on the UUID so they survive workspace and window moves.
- **Must:** Treat a runtime_unknown or verb_unsupported result as a deliberate fail-closed refusal, never a best-effort attempt. When the target's runtime is unknown or the verb has no keystroke mapping for it, conduct refuses to inject — do NOT improvise a keystroke or force injection, because blind injection into a shell, editor, or REPL is harmful. This mirrors afork's posture: refuse rather than act on what cannot be proven.
- **Must:** Treat owned_by_other and not_owner as exclusive-ownership boundaries, not bugs to route around. Ownership is exclusive first-touch with no steal: for a transfer the current owner must run release first, and an orphaned (dead-owner) claim self-reclaims on the next touch — let it, rather than forcing a takeover.
- **Require:** Keep every read and every control action scoped to your owned set. --all on status or a lifecycle verb operates over the agents you own ONLY — it is never a workspace-wide or global broadcast, which is rejected as a haywire risk. Fleet-wide reads of unrelated agents belong to the watchdog / observability skills, not conduct.
- **Require:** Use conduct only to read status and control agents you own — it never spawns and never messages. When the right move is to spawn a new agent, that is the tfork (or afork) skill's job; when it is to message a peer, that is the p2p skill's job. conduct does not invoke afork / tfork / p2p; the register --from-fork alias merely READS tfork's result JSON, it does not call tfork.
- **Avoid:** Reaching for raw cmux send / send-key / close-surface to control an agent yourself. Go through conduct instead, so ownership is checked, the target's runtime is identified, and the verb maps to the correct atomic keystroke sequence — remember `cmux send` does NOT press Enter, so a hand-rolled injection silently fails to submit while conduct follows text with send-key Enter.

## Steps

1. Resolve <skill-dir> to the absolute directory this SKILL.md was loaded from — conduct.py sits in the scripts/ subdirectory under it, and the working directory is the user's project, not the skill directory, so a bare conduct.py will not resolve. Every verb below runs as: python3 <skill-dir>/scripts/conduct.py {verb} ...
2. Decide which of the following applies and follow only that path:
   If The caller passed --all: a status read over the whole owned set, or a lifecycle verb (clear / compact / exit / kill / interrupt) broadcast over the whole owned set — owned set only, never an ungated workspace/all:
   a. Follow the read-or-control-owned-fleet procedure.
   If The verb targets exactly one surface by --agent <ref> and the caller did NOT pass --all: a single status read, or a single lifecycle injection (clear / compact / exit / kill / interrupt) against one owned surface:
   a. Follow the target-one-agent procedure.
   If the verb is claim or register — eager explicit ownership without a status read or a control verb:
   a. Follow the manage-ownership-claim procedure.
   Otherwise:
   a. The verb is release: run python3 <skill-dir>/scripts/conduct.py release --agent {agent} to drop your claim on that surface. Release is required before an ownership transfer (the new owner can only claim once you release) and for clean teardown. A release of a surface you do not own returns owned_by_other; a release of an unclaimed surface is a harmless no-op.
3. Parse stdout as exactly one JSON envelope, then act on it.
4. Follow the handle-handoff-envelope procedure below.

### Procedure: read-or-control-owned-fleet

1. Decide which of the following applies and follow only that path:
   If the verb is status:
   a. Run python3 <skill-dir>/scripts/conduct.py status --all. The result lists every agent in your owned set with its live-derived context_pct (percent of context USED), type (runtime: claude / codex / pi / null), state, title, and current workspace — the single-call fleet read. Scope is your owned set ONLY, never the workspace or every agent; fleet-wide reads of unrelated agents belong to watchdog / observability.
   Otherwise:
   a. Run python3 <skill-dir>/scripts/conduct.py {verb} --all to broadcast that lifecycle verb over your owned set ONLY. Each target is handled independently and runtime-aware: a target whose runtime is unknown or that cannot map this verb is refused per-target (fail-closed) while the rest proceed; the result reports applied/count and per-target outcomes. This is never an ungated workspace/all broadcast — it is exactly the surfaces you own.

### Procedure: target-one-agent

1. Decide which of the following applies and follow only that path:
   If the verb is status:
   a. Run python3 <skill-dir>/scripts/conduct.py status --agent {agent}. This reads the surface's live context_pct (percent of context USED) + runtime type + state + title + current workspace AND first-touches it: touching an unowned (or orphaned) surface to read IS the ownership claim, so this is how you take ownership of a freshly spawned worker before controlling it.
   Otherwise:
   a. Run python3 <skill-dir>/scripts/conduct.py {verb} --agent {agent} to inject that lifecycle action into the one surface. You must own it — the verb first-touches an unowned/orphaned surface and claims it, but refuses (not_owner) a surface live-owned by someone else. conduct identifies the target's runtime and maps {verb} to that runtime's real keystroke sequence; an unknown runtime or unsupported verb is a fail-closed refusal, never a blind injection. Verbs are atomic — there is no implicit interrupt-then-clear; compose sequences yourself with separate calls.

### Procedure: manage-ownership-claim

1. Decide which of the following applies and follow only that path:
   If the verb is register:
   a. Run python3 <skill-dir>/scripts/conduct.py register --from-fork {from_fork}. Pass tfork's result JSON (inline string or a file path); conduct reads its `session: surface:N` field and claims that surface for you in one decoupled call. This is the spawn->own bridge: conduct does NOT invoke tfork — you fork via the tfork skill, then hand its result here. register is a pure alias of claim.
   Otherwise:
   a. Run python3 <skill-dir>/scripts/conduct.py claim --agent {agent} to take ownership of the surface eagerly, without issuing a status read or a control verb. Use it when you want to register ownership up front. Claiming an unowned or orphaned surface succeeds; an already-yours surface is a harmless pass; a surface live-owned by another caller returns owned_by_other (no steal).

### Procedure: handle-handoff-envelope

1. Decide which of the following applies and follow only that path:
   If the envelope has ok:true:
   a. The verb succeeded. For status, consume the agent / agents fields (context_pct, type, state, title, workspace). For a lifecycle verb, the injection (or per-target broadcast result) is reported; for claim / register / release, ownership state is updated. You are done.
   Otherwise:
   a. The verb failed: read `code` and follow `agent_instruction` verbatim — do not improvise around it. runtime_unknown / verb_unsupported are fail-closed refusals, so do NOT force injection. owned_by_other / not_owner mean the surface is not yours, so do NOT steal — a transfer needs the current owner to release first. target_unknown / cmux_failed are retryable after you re-resolve the target or check cmux state. See the handoff_codes context for the full code-by-code meaning and retryability.

