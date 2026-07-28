---
name: tfork
description: 'Fork a coding agent or command into a new cmux pane via the deterministic fork_terminal.py binary.'
---

## Parameters

- **command**:
  The single command or agent to fork. Aliases are one word — only the first word is matched against the registry, and any words after it are arguments to that command, not a briefing. tfork forks exactly one thing; never append a briefing, prompt, or handoff (e.g. `tfork worker handover the current task` is wrong — `worker` is the alias and the rest looks like args). Fork with just the alias, then use p2p to send the briefing.
  Required.
- **placement**:
  Where the new pane opens: right, left, top, or bottom for a split. Omit to default to a right-split when no --workspace is given, or a fresh pane in the workspace when --workspace is set.
  Default: none.
- **anchor**:
  Optional cmux surface ref (surface:N) or tab title the new pane attaches next to; omit to anchor on the caller's own pane. Mutually exclusive with --workspace.
  Default: none.
- **workspace**:
  Optional cmux workspace title or ref (workspace:N / UUID) where the new pane opens. New title → workspace is created with that name. Existing title or ref → pane opens inside it. Mutually exclusive with --anchor. Combine with --placement to split the workspace's active pane in that direction.
  Default: none.
- **cwd**:
  Optional working directory the forked command runs in. Path is expanded (~ and relative paths resolved against the caller's cwd) and must exist as a directory. Used for both the wrapper's cd-and-run line and, when --workspace creates a new workspace, the workspace's cwd. Omit to inherit the caller's cwd — useful when forking into a different repo without cd-ing the caller first.
  Default: none.
- **type_override**: Optional classification override: agent or command. Omit to let the binary classify by what it observed after the fork. Default: none.
- **title**:
  Optional cmux tab title for the new pane — renamed right after fork so it's immediately p2p-addressable. Pass a snake_case title (e.g. `worker_42`) for any agent you'll message. cmux allows duplicates in a workspace; collisions surface in `note`, not failures.
  Default: none.
- **window**:
  Optional cmux window to open the fork in: 'new' creates a fresh top-level window, or a window ref/index/UUID targets an existing one. Combine with --workspace to name the workspace inside the window. Mutually exclusive with --anchor.
  Default: none.
- **launch_contract**:
  Optional path to the launch-contract sidecar afork wrote for this attempt, taken verbatim from an afork ready_to_fork handoff's launch_contract field. Never construct one yourself — tfork holds no runtime knowledge, and this file is the only thing that lets it tell 'the runtime was missing' apart from 'something exited non-zero'. Omitting it is not an error: the fork still runs and still reports a launch_outcome, but every ambiguous launch degrades to state unknown.
  Default: none.

## Context

- **binary-contract**

  fork_terminal.py is deterministic and self-verifying: it resolves the caller's own cmux surface (or the anchor the user named, or the workspace --workspace targeted), opens the new pane or workspace, runs the command in --cwd (or the caller's current directory when --cwd is omitted) through a per-fork sentinel wrapper, observes what happened, and always prints exactly one JSON object — a success result or a handoff. The success result carries verified (true when the wrapper accounts for the outcome: clean exit, or still running with a non-shell foreground process), type (agent or command), foreground (the process running in the pane at observation time, or null when none was tracked), exit_status (the integer the command exited with, or null when it is still running), workspace (`{ref, title, created}` when --workspace or --window was passed, else null — created=true means the workspace was just created, false means it already existed and was reused), window (`{ref, created}` when --window was passed, else null — created=true means a fresh window was opened, false means an existing window was targeted), launch_outcome (the versioned machine-readable reading of the same observation — see the launch-outcome contract), and note (a one-line plain-language summary of what was observed — clean exit, exit status N, still running with foreground X, state unknown, or missing start sentinel; with --workspace or --window, the note also reports the workspace title / window and whether each was created or reused). A verified-false success is still a success: the pane is never killed and the command is never re-run on tfork's behalf.

- **launch-outcome-contract**

  Every success result carries a `launch_outcome` object, and so do the three failure handoffs where a launch was mechanically attempted (`split_failed`, `window_create_failed`, `spawn_failed`). It is the ONLY field a policy or dispatcher may branch on. Its fields are exactly: version, state, reason_code, evidence_code, start_sentinel_seen, end_sentinel_seen, exit_status, foreground.

  `state` is one of: `started` | `prework_failure` | `unknown`.
  `reason_code` is null unless state is prework_failure, where it is one of: `runtime_unavailable` | `model_unavailable` | `launch_failed`.
  `evidence_code` is one of: `agent_started`, `runtime_exec_failed`, `model_rejected`, `runtime_launch_error`, `pane_creation_failed`, `command_delivery_absent`, `unrecognized_exit`, `missing_start_sentinel`, `observation_timeout`, `shell_foreground`, `missing_foreground`, `delivery_ambiguous`, `contradictory_evidence`.

  `prework_failure` is the only state that means the intended agent definitely never started, and therefore the only one that licenses trying a different runtime or model. `unknown` means tfork could not account for the launch — it is NOT a failure and must never be treated as one; retrying or falling back on `unknown` is how you end up with two live agents doing the same work. `unknown` can never be elevated: no exit status, no pane text, and no reading of `note` may turn it into a prework_failure. tfork holds no runtime or model table of its own — the only runtime-specific evidence it can trust comes from the --launch-contract sidecar afork wrote, so a fork without one reports `unknown` wherever it would otherwise have classified.

## Constraints

- **Must:** Infer only the front-door parameters from the user's request — command, placement, anchor, workspace, cwd, type_override, and window — using documented defaults when omitted. Pass the command through after the -- separator without reinterpreting it. Never hand-build cmux commands, inspect panes, classify agent vs command, verify success, retry/re-run, or override a runtime decision the binary owns. Do not pass --anchor together with --workspace or --window; the binary rejects those combinations.
- **Require:** tfork only forks. Never message or brief the forked agent from this skill. When the user asks to communicate with, brief, or message the forked agent, load the p2p skill and use it with the session ref (or --title) returned from the fork — p2p owns all agent-to-agent messaging.

### Red Flags

Skip these — SKILL.md is the complete interface.

| Thought | Reality |
|---|---|
| "Run `--help` first" | All flags are listed in Parameters. |
| "Read fork_terminal.py to understand it" | SKILL.md is the contract. |
| "`cmux identify` / `ls` to check surfaces first" | The binary resolves the caller's surface itself. |
| "Peek at the registry first" | The binary handles it; result reports the label. |
| "Append a briefing after the alias (e.g. `tfork worker handover the task`)" | Aliases are one word. Fork the alias alone, then use p2p to send the briefing. |
| "`cd /other/repo` in my pane before tfork to fork there" | Pass `--cwd /other/repo` instead — keeps the caller's cwd unchanged. |
| "afork gave me a launch_contract path, but the fork works without it" | Without it tfork cannot tell a missing runtime from any other non-zero exit — every ambiguous launch reports `unknown`. Pass it verbatim. |
| "I'll parse `note` / `exit_status` to decide whether to try another runtime" | Only `launch_outcome.state == prework_failure` licenses that. The note is free-form prose and is never a policy input. |
| "state is `unknown`, so the launch failed — retry it" | `unknown` means tfork could not account for the launch, not that it failed. The agent may be running; retrying forks a second one. |
| "I'll write a launch-contract file myself so tfork can classify" | The sidecar is afork's, written 0600 for one attempt. Pass the path afork returned or pass nothing. |

## Steps

1. Extract the parameters from the user's request — {command}, {placement}, {anchor}, {workspace}, {cwd}, {type_override}, {window}, and {launch_contract} — and forward them as-is. Do not invent values; if the user did not name a placement, an anchor, a workspace, a cwd, or a window, use the defaults.
2. Begin the invocation as: python3 <skill-dir>/fork_terminal.py -- {command}. Run the binary explicitly with python3, and resolve <skill-dir> to the absolute path of the directory this SKILL.md was loaded from — fork_terminal.py sits in that same directory, and the working directory is the user's project, not the skill directory, so a bare fork_terminal.py will not resolve. Everything after the -- separator is the command.
3. Decide whether the user named a placement applies and, if so:
   a. Insert --placement {placement} into the invocation, before the -- separator.
4. Decide whether the user named a workspace applies and, if so:
   a. Insert --workspace {workspace} into the invocation, before the -- separator. Do not also pass --anchor — the two are mutually exclusive.
5. Decide whether the user named an anchor (a surface ref like surface:42 or a cmux tab title) applies and, if so:
   a. Insert --anchor {anchor} into the invocation, before the -- separator.
6. Decide whether the user asked to open the fork in a new or separate window applies and, if so:
   a. Insert --window {window} into the invocation, before the -- separator — 'new' for a fresh window, or a window ref/index/UUID for an existing one. Do not also pass --anchor — the two are mutually exclusive.
7. Decide whether the user named a working directory (e.g. a path to a different repo) applies and, if so:
   a. Insert --cwd {cwd} into the invocation, before the -- separator. The binary expands the path and rejects it with bad_arguments if the directory does not exist.
8. Decide whether the user explicitly specified agent or command as the type applies and, if so:
   a. Insert --type {type_override} into the invocation, before the -- separator.
9. Decide whether the fork is an agent you'll p2p applies and, if so:
   a. Pick a snake_case title and insert --title {title} before the -- separator. p2p can route to it on the first send.
10. Decide whether you are forking a command afork prepared and its handoff carried a launch_contract path applies and, if so:
   a. Insert --launch-contract {launch_contract} into the invocation, before the -- separator, using the path from the handoff verbatim. Dropping it silently costs you the ability to tell a missing runtime from an ordinary non-zero exit.
11. Run the assembled fork_terminal.py invocation and capture its stdout as a single JSON object.
12. Decide which of the following applies and follow only that path:
   If the JSON result has ok set to true:
   a. Follow the report-success procedure.
   Otherwise:
   a. Treat the JSON as a handoff object: carry out its agent_instruction exactly, relay its human_message to the user, and offer suggested_next_command when retryable is true.

### Procedure: report-success

1. Report the fork succeeded. Always surface the result's note field to the user verbatim — it is the only place the distinction between 'exited cleanly' and 'still running, foreground = X' is recorded, and it carries any registry/observation conflict the binary noticed.
2. Decide whether the result's type is agent applies and, if so:
   a. Record the session field — the new cmux surface ref — as the address for this forked agent. When the user asks to communicate with, brief, or message that agent (now or later in the conversation), load the p2p skill and use it with this session ref to talk to the agent.
3. Decide whether the result's verified field is false applies and, if so:
   a. tfork could not confirm the command ran cleanly. Point the user at the session surface so they can inspect the pane themselves, and do not re-run the command.
4. Decide whether you are deciding programmatically whether the agent launched (e.g. to pick a fallback runtime or model) applies and, if so:
   a. Read the result's launch_outcome.state and nothing else — never the note, the exit_status, or the pane. Only `prework_failure` means the agent definitely never started; act on its reason_code. On `started`, the agent is live. On `unknown`, tfork could not account for the launch: do NOT retry and do NOT fall back — say what was observed and let the user decide, because the agent may well be running.
5. Decide whether the result's note mentions 'correct if intended' applies and, if so:
   a. The label tfork is returning disagrees with what it observed (the registry or --type override is winning over a contradictory observation). Tell the user they can pass --type agent or --type command on the next run if the registry has it wrong.

