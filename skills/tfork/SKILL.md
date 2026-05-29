---
name: tfork
description: 'Fork a coding agent or command into a new cmux pane via the deterministic fork_terminal.py binary.'
---

## Parameters

- **command**:
  The coding-agent alias or literal command to fork, extracted verbatim from the user's request; its first word is the registry key.
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
- **type_override**: Optional classification override: agent or command. Omit to let the binary classify by what it observed after the fork. Default: none.
- **title**:
  Optional cmux tab title for the new pane — renamed right after fork so it's immediately p2p-addressable. Pass a snake_case title (e.g. `worker_42`) for any agent you'll message. cmux allows duplicates in a workspace; collisions surface in `note`, not failures.
  Default: none.

## Context

- **binary-contract**

  fork_terminal.py is deterministic and self-verifying: it resolves the caller's own cmux surface (or the anchor the user named, or the workspace --workspace targeted), opens the new pane or workspace, runs the command in the caller's current directory through a per-fork sentinel wrapper, observes what happened, and always prints exactly one JSON object — a success result or a handoff. The success result carries verified (true when the wrapper accounts for the outcome: clean exit, or still running with a non-shell foreground process), type (agent or command), foreground (the process running in the pane at observation time, or null when none was tracked), exit_status (the integer the command exited with, or null when it is still running), workspace (`{ref, title, created}` when --workspace was passed, else null — created=true means the workspace was just created, false means it already existed and was reused), and note (a one-line plain-language summary of what was observed — clean exit, exit status N, still running with foreground X, state unknown, or missing start sentinel; with --workspace, the note also reports the workspace title and whether it was created or reused). A verified-false success is still a success: the pane is never killed and the command is never re-run on tfork's behalf.

## Constraints

- **Must:** Infer only the front-door parameters from the user's request — command, placement, anchor, workspace, and type_override — using documented defaults when omitted. Pass the command through after the -- separator without reinterpreting it. Never hand-build cmux commands, inspect panes, classify agent vs command, verify success, retry/re-run, or override a runtime decision the binary owns. Do not pass --workspace and --anchor together; the binary rejects that combination.
- **Require:** tfork only forks. Never message or brief the forked agent from this skill. When the user asks to communicate with, brief, or message the forked agent, load the p2p skill and use it with the session ref (or --title) returned from the fork — p2p owns all agent-to-agent messaging.

## Steps

1. Extract the parameters from the user's request — {command}, {placement}, {anchor}, {workspace}, and {type_override} — and forward them as-is. Do not invent values; if the user did not name a placement, an anchor, or a workspace, use the defaults.
2. Begin the invocation as: python3 <skill-dir>/fork_terminal.py -- {command}. Run the binary explicitly with python3, and resolve <skill-dir> to the absolute path of the directory this SKILL.md was loaded from — fork_terminal.py sits in that same directory, and the working directory is the user's project, not the skill directory, so a bare fork_terminal.py will not resolve. Everything after the -- separator is the command.
3. Decide whether the user named a placement applies and, if so:
   a. Insert --placement {placement} into the invocation, before the -- separator.
4. Decide whether the user named a workspace applies and, if so:
   a. Insert --workspace {workspace} into the invocation, before the -- separator. Do not also pass --anchor — the two are mutually exclusive.
5. Decide whether the user named an anchor (a surface ref like surface:42 or a cmux tab title) applies and, if so:
   a. Insert --anchor {anchor} into the invocation, before the -- separator.
6. Decide whether the user explicitly specified agent or command as the type applies and, if so:
   a. Insert --type {type_override} into the invocation, before the -- separator.
7. Decide whether the fork is an agent you'll p2p applies and, if so:
   a. Pick a snake_case title and insert --title {title} before the -- separator. p2p can route to it on the first send.
8. Run the assembled fork_terminal.py invocation and capture its stdout as a single JSON object.
9. Decide which of the following applies and follow only that path:
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
4. Decide whether the result's note mentions 'correct if intended' applies and, if so:
   a. The label tfork is returning disagrees with what it observed (the registry or --type override is winning over a contradictory observation). Tell the user they can pass --type agent or --type command on the next run if the registry has it wrong.

