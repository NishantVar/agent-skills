# Purpose

Create a new Codex CLI agent to execute the command.

## Instructions

- If the user provides an exact Codex launcher command or alias, use it verbatim. Do not replace it with a hand-built `codex ...` command.
- Before executing the command, run `codex --help` to understand the command and its options, but only when you are constructing a direct `codex` invocation yourself.
- Always use interactive mode (so leave off -p and use positional prompt if needed)
- Do NOT pass `-m` — let Codex use its default model.
- Always run with `--dangerously-bypass-approvals-and-sandbox`
- If the chosen launcher relies on aliases, shell functions, or shell startup files, wrap it in an interactive login shell.
- To exit/shutdown a running Codex session, send `/exit`.
