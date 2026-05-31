# inject-ctx

A `UserPromptSubmit` hook for Claude Code and Codex CLI that injects a context-degradation warning into the user-turn prompt once cmux `ctx:N%` reaches 50% or higher.

## Why

Agents can't see their own token usage, and past ~50% context their instruction adherence and reasoning degrade. The agent's status line already displays context usage — Claude Code as `ctx:N%`, Codex as `Context N% left`. This hook reads whichever is present and injects a tiered reminder **only when context crosses up into a new tier** (so it fires at most twice per session, instead of once per turn):

- **crossing 25%** — session is trending long; suggest spawning a sub-agent for any handoff-able work before context tightens.
- **crossing 50%** — stronger degradation warning: pause and suggest `/compact` or a fresh session before durable artifacts or irreversible actions.
- **below 25%** — silent no-op.

State is tracked per-surface in `/tmp/inject-ctx-tier-<surface>`. When context drops back down (e.g. after `/compact`), the state resets, so re-crossing a tier later fires the message again.

## Requirements

- [cmux](https://cmux.io) — the hook reads context via `cmux identify` + `cmux read-screen`.
- Claude Code or Codex CLI — both use the same `UserPromptSubmit` JSON hook contract (`hookSpecificOutput.additionalContext`).

## Install (Claude Code)

1. Copy the script into your Claude Code hooks directory:

   ```sh
   mkdir -p ~/.claude/hooks
   cp inject-ctx.sh ~/.claude/hooks/
   chmod +x ~/.claude/hooks/inject-ctx.sh
   ```

2. Add this `hooks` block to `~/.claude/settings.json` (merge with any existing keys; don't replace the file):

   ```json
   "hooks": {
     "UserPromptSubmit": [
       {
         "hooks": [
           { "type": "command", "command": "bash ~/.claude/hooks/inject-ctx.sh" }
         ]
       }
     ]
   }
   ```

3. Start a fresh `claude` session in a cmux pane. Once `ctx:N%` reaches 50%, the warning is injected on each prompt.

## Install (Codex CLI)

Codex CLI uses the same hook contract. Reuse the same script:

```sh
mkdir -p ~/.claude/hooks
cp inject-ctx.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/inject-ctx.sh
cp codex-hooks.json ~/.codex/hooks.json
```

`codex-hooks.json` is the standalone config Codex reads from `~/.codex/hooks.json` and points at the same `~/.claude/hooks/inject-ctx.sh` script.

## Injected messages

Each message is prefixed with `[system suggestion, not user-issued]` so the agent treats it as advisory rather than a direct user instruction.

When ctx first crosses 25%:

> `[system suggestion, not user-issued] ctx:32% - session is trending long. If upcoming work has parts that can be handed off (research, multi-step exploration, parallel checks), consider spawning a sub-agent now before context tightens.`

When ctx first crosses 50%:

> `[system suggestion, not user-issued] ctx:62% - past 50%, instruction adherence and reasoning degrade. Make sure any work done from here on gets reviewed and verified.`

While ctx stays inside the same tier, nothing is injected.

## Behavior outside cmux

If `cmux` is not on PATH, or `identify` / `read-screen` fail, or no `ctx:N%` is present on screen, the hook exits silently with success — no stdout, no stderr, no blocked prompt flow. Safe to leave installed in non-cmux environments.

## Cost

~30ms per user prompt (two short cmux calls). The injected payload is ~30 tokens per turn, only above the 50% threshold.
