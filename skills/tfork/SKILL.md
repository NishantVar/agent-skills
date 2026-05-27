---
name: tfork
description: 'Fork a coding agent or command into a new cmux pane via the deterministic fork_terminal.py binary.'
---

## Parameters

- **command**:
  The coding-agent alias or literal command to fork, extracted verbatim from the user's request; its first word is the registry key.
  Required.
- **placement**:
  Where the new pane opens relative to the anchor: right, left, top, or bottom for a split, or new-workspace for a fresh tab.
  Default: "right".
- **anchor**:
  Optional cmux surface ref (surface:N) or tab title the new pane attaches next to; omit to anchor on the caller's own pane. Ignored when placement is new-workspace.
  Default: none.
- **type_override**: Optional classification override: agent or command. Omit to let the binary classify by what it observed after the fork. Default: none.
- **title**: Optional cmux tab title to apply to the new pane immediately after fork. Pass this whenever the spawner intends to p2p the forked agent — p2p routes by tab title, and without `--title` the new tab carries cmux's default title and is not addressable until renamed. Pick a snake_case title from the spawner's role context (e.g. `worker_42`, `qa_runner`); cmux allows duplicates within a workspace, so collisions are reported in `note` rather than failing the fork. Default: none.

## Context

- **binary-contract**

  fork_terminal.py is deterministic and self-verifying: it resolves the caller's own cmux surface (or the anchor the user named), opens the new pane or workspace, runs the command in the caller's current directory through a per-fork sentinel wrapper, observes what happened, and always prints exactly one JSON object — a success result or a handoff. The success result carries verified (true when the wrapper accounts for the outcome: clean exit, or still running with a non-shell foreground process), type (agent or command), foreground (the process running in the pane at observation time, or null when none was tracked), exit_status (the integer the command exited with, or null when it is still running), and note (a one-line plain-language summary of what was observed — clean exit, exit status N, still running with foreground X, state unknown, or missing start sentinel). A verified-false success is still a success: the pane is never killed and the command is never re-run on tfork's behalf.

## Constraints

- **Must:** Infer only the front-door parameters from the user's request — command, placement, anchor, and type_override — using documented defaults when omitted. Pass the command through after the -- separator without reinterpreting it. Never hand-build cmux commands, inspect panes, classify agent vs command, verify success, retry/re-run, or override a runtime decision the binary owns.
- **Require:** tfork only forks. Never message or brief the forked agent from this skill. When the user asks to communicate with, brief, or message the forked agent, load the p2p skill and use it with the session ref (or `--title`) returned from the fork — p2p owns all agent-to-agent messaging.

### Red Flags

These thoughts mean STOP — you are about to waste time on reconnaissance the binary does not need. This SKILL.md is the complete agent-facing interface; trust it and invoke the binary directly.

| Thought | Reality |
|---|---|
| "Let me run `fork_terminal.py --help` first" | Every flag the agent needs is listed in Parameters above. |
| "I'll read fork_terminal.py / tforklib to understand it" | The contract is SKILL.md. Source is implementation detail. |
| "I should `cmux identify` / `cmux ls` to check my surface first" | The binary resolves the caller's own surface itself. Just invoke. |
| "Let me peek at the registry before forking" | The binary reads and writes the registry; the JSON result tells you what label landed. |

## Steps

1. Extract the parameters from the user's request — {command}, {placement}, {anchor}, and {type_override} — and forward them as-is. Do not invent values; if the user did not name a placement or an anchor, use the defaults.
2. Begin the invocation as: python3 <skill-dir>/fork_terminal.py --placement {placement} -- {command}. Run the binary explicitly with python3, and resolve <skill-dir> to the absolute path of the directory this SKILL.md was loaded from — fork_terminal.py sits in that same directory, and the working directory is the user's project, not the skill directory, so a bare fork_terminal.py will not resolve. Everything after the -- separator is the command.
3. If the user named an anchor (a surface ref like surface:42 or a cmux tab title):
   a. Insert --anchor {anchor} into the invocation, before the -- separator.
4. If the user explicitly specified agent or command as the type:
   a. Insert --type {type_override} into the invocation, before the -- separator.
4a. If the fork is an agent the spawner intends to message via p2p:
   a. Pick a snake_case title from your own role context (do not ask the human) and insert --title {title} into the invocation, before the -- separator. The new tab is renamed before the binary returns, so p2p can route to it on the first send.
5. Run the assembled fork_terminal.py invocation and capture its stdout as a single JSON object.
6. Decide which of the following applies and follow only that path:
   If the JSON result has ok set to true:
   a. Follow the report-success procedure.
   Otherwise:
   a. Treat the JSON as a handoff object: carry out its agent_instruction exactly, relay its human_message to the user, and offer suggested_next_command when retryable is true.

### Procedure: report-success

1. Report the fork succeeded. Always surface the result's note field to the user verbatim — it is the only place the distinction between 'exited cleanly' and 'still running, foreground = X' is recorded, and it carries any registry/observation conflict the binary noticed.
2. If the result's type is agent:
   a. Record the session field — the new cmux surface ref — as the address for this forked agent. When the user asks to communicate with, brief, or message that agent (now or later in the conversation), load the p2p skill and use it with this session ref to talk to the agent.
3. If the result's verified field is false:
   a. tfork could not confirm the command ran cleanly. Point the user at the session surface so they can inspect the pane themselves, and do not re-run the command.
4. If the result's note mentions 'correct if intended':
   a. The label tfork is returning disagrees with what it observed (the registry or --type override is winning over a contradictory observation). Tell the user they can pass --type agent or --type command on the next run if the registry has it wrong.

