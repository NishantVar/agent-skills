---
name: fork-terminal
description: Fork a terminal session to a new terminal window. Use this when the user requests 'fork terminal' or 'create a new terminal' or 'new terminal: <command>' or 'fork session: <command>'.
---

# Purpose

Fork a terminal session to a new terminal window. Using one agentic coding tools or raw cli commands.
Follow the `Instructions`, execute the `Workflow`, based on the `Cookbook`.

## Variables

ENABLE_RAW_CLI_COMMANDS: true
ENABLE_GEMINI_CLI: true
ENABLE_CODEX_CLI: true
ENABLE_CLAUDE_CODE: true
AGENTIC_CODING_TOOLS: claude-code, codex-cli, gemini-cli
TERMINAL_BACKEND: auto            # auto | native | tmux | cmux
SPLIT_DIRECTION: auto             # auto | right | bottom
PLAN_SAVE_DIR: auto               # auto | explicit path. "auto" checks: ~/Documents/Obsidian Vault/Claude/plans/ → ~/.claude/plans/ → /tmp/claude-plans/

## Instructions

- On the FIRST time this skill is triggered in a session, tell the user:
  "Fork Terminal is using **auto** detection (cmux > tmux > native). You can override this by setting `TERMINAL_BACKEND` in this skill's SKILL.md file."
- Based on the user's request, follow the `Cookbook` to determine which tool to use.

### Fork with Plan

- IF: The user says "fork terminal with this plan", "fork with plan", or references a plan file / the current plan in context.
- THEN:
  1. Identify the plan content. It can come from:
     a. The current plan file in context (check `/Users/nishant/.claude/plans/` for the active plan)
     b. A plan file the user explicitly references
     c. Plan content from the conversation
  2. Save the plan to a file using `--save-plan` flag on fork_terminal.py:
     - The tool auto-detects the best save location (see PLAN_SAVE_DIR variable)
     - It returns the saved path — **tell the user where the plan was saved**
  3. Fork the agentic tool (default: Claude Code) with `--delayed-input-file <saved_path>` and `--delay 5`
  4. The prompt sent to the forked agent should be: `Read and execute the plan at <saved_path>. Do NOT commit.`
- EXAMPLES:
  - "fork terminal with this plan"
  - "fork terminal below, execute the plan"
  - "fork with plan at ~/path/to/plan.md"
  - "fork terminal with claude code, use this plan"

### Fork Summary User Prompts

- IF: The user requests a fork terminal with a summary. This ONLY works for our agentic coding tools `AGENTIC_CODING_TOOLS`. The tool MUST BE enabled as well.
- THEN: 
  - Read, and REPLACE the `.claude/skills/fork-terminal/prompts/fork_summary_user_prompt.md` with the history of the conversation between you and the user so far. 
  - Include the next users request in the `Next User Request` section.
  - This will be what you pass into the PROMPT parameter of the agentic coding tool.
  - IMPORTANT: To be clear, don't update the file directly, just read it, fill it out IN YOUR MEMORY and use it to craft a new prompt in the structure provided for the new fork agent.
  - Let's be super clear here, the fork_summary_user_prompt.md is a template for you to fill out IN YOUR MEMORY. Once you've filled it out, pass that prompt to the agentic coding tool.
  - XML Tags have been added to let you know exactly what you need to replace. You'll be replacing the <fill in the history here> and <fill in the next user request here> sections.
- EXAMPLES:
  - "fork terminal use claude code to <xyz> summarize work so far"
  - "spin up a new terminal request <xyz> using claude code include summary"
  - "create a new terminal to <xyz> with claude code with summary"

## Workflow

1. Understand the user's request.
2. READ: `.claude/skills/fork-terminal/tools/fork_terminal.py` to understand our tooling.
3. Follow the `Cookbook` to determine which tool to use.
4. Execute via bash: `python3 .claude/skills/fork-terminal/tools/fork_terminal.py --backend TERMINAL_BACKEND --split SPLIT_DIRECTION <command>`
   - Replace `TERMINAL_BACKEND` and `SPLIT_DIRECTION` with their values from the Variables section above.
   - `<command>` is the full command string built from the Cookbook (e.g. `claude --model opus --dangerously-skip-permissions`).

### Sending prompts to agentic tools (delayed input)

When the user wants to fork a terminal AND send a prompt to an agentic tool (like Claude Code):

1. Save the prompt to a file if it's long (e.g., `~/Documents/Obsidian Vault/Claude/plans/`)
2. Use `--delayed-input-file <path>` to send file contents, or `--delayed-input "<text>"` for short prompts
3. Use `--delay <seconds>` to wait for the tool to load (default: 5s, use 5s for Claude Code)

This launches the tool in interactive mode, waits for it to load, then automatically types the prompt.

Example:
```bash
python3 fork_terminal.py --backend auto --split bottom --delayed-input-file ~/path/to/prompt.md --delay 5 "claude --model opus --dangerously-skip-permissions"
```

### Sending prompts to already-running sessions

When you need to send a follow-up prompt to a session that was already forked (e.g. judgy round 2+), use `send_to_surface.py` instead of `cmux send "$(cat ...)"`. The `$(cat ...)` shell expansion hits argument length limits and silently truncates large prompts.

```bash
python3 .claude/skills/fork-terminal/tools/send_to_surface.py \
  --surface <ref> \
  --file /tmp/your-prompt.txt \
  --delay 0
```

- Always write the prompt to a temp file first
- Use `--delay` if the session may be mid-output and needs a moment to settle
- Works for cmux (`surface:N`) and tmux (`%N`) refs

## Cookbook

### Raw CLI Commands

- IF: The user requests a non-agentic coding tool AND `ENABLE_RAW_CLI_COMMANDS` is true.
- THEN: Read and execute: `.claude/skills/fork-terminal/cookbook/cli-command.md` 
- EXAMPLES:
  - "Create a new terminal to <xyz> with ffmpeg"
  - "Create a new terminal to <xyz> with curl"
  - "Create a new terminal to <xyz> with python"

### Claude Code

- IF: The user requests a claude code agent to execute the command AND `ENABLE_CLAUDE_CODE` is true.
- THEN: Read and execute: `.claude/skills/fork-terminal/cookbook/claude-code.md`
- EXAMPLES:
  - "fork terminal use claude code to <xyz>"
  - "spin up a new terminal request <xyz> using claude code"
  - "create a new terminal to <xyz> with claude code"

### Codex CLI

- IF: The user requests a codex CLI agent to execute the command AND `ENABLE_CODEX_CLI` is true.
- THEN: Read and execute: `.claude/skills/fork-terminal/cookbook/codex-cli.md`
- EXAMPLES:
  - "fork terminal use codex to <xyz>"
  - "spin up a new terminal request <xyz> using codex"
  - "create a new terminal to <xyz> with codex"

### Gemini CLI

- IF: The user requests a gemini CLI agent to execute the command AND `ENABLE_GEMINI_CLI` is true.
- THEN: Read and execute: `.claude/skills/fork-terminal/cookbook/gemini-cli.md`
- EXAMPLES:
  - "fork terminal use gemini to <xyz>"
  - "spin up a new terminal request <xyz> with gemini"
  - "create a new terminal to <xyz> using gemini"
