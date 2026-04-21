# Purpose

Create a new Claude code agent to execute the command.

## Variables

DEFAULT_MODEL: opus
HEAVY_MODEL: opus
BASE_MODEL: sonnet
FAST_MODEL: haiku

## Instructions

- If the user provides an exact Claude launcher command or alias, use it verbatim. Do not replace it with a hand-built `claude ...` command.
- Before executing the command, run `claude --help` to understand the command and its options, but only when you are constructing a direct `claude` invocation yourself.
- Always use interactive mode (so leave off -p)
- For the --model argument, use the DEFAULT_MODEL if not specified. If 'fast' is requested, use the FAST_MODEL. If 'heavy' is requested, use the HEAVY_MODEL.
- Always run with `--dangerously-skip-permissions`
- If the chosen launcher relies on aliases, shell functions, or shell startup files, wrap it in an interactive login shell, for example `zsh -lic 'cx'`.

## Sending a prompt to Claude Code

When you need to send a prompt to the forked Claude Code session:

1. Save the prompt to a file (e.g., in the user's vault or a temp location)
2. Use `--delayed-input-file <path>` to send the file contents after Claude loads
3. Or use `--delayed-input "<text>"` for short prompts
4. Use `--delay <seconds>` to control wait time (default: 5s, use 5s for Claude Code)

Example:
```bash
python3 fork_terminal.py --backend auto --split bottom --delayed-input-file ~/path/to/prompt.md --delay 5 "claude --model opus --dangerously-skip-permissions"
```

This launches Claude Code interactively, waits for it to load, then sends the prompt text automatically.

## Exiting

- To exit/shutdown a running Claude Code session, send `/exit`.
