---
name: ateam
description: >-
  Multi-LLM agent team management. Use ONLY when the user explicitly mentions
  Codex or Gemini teammates, or a mixed-LLM team. Do NOT trigger for
  Claude-only agent teams. Triggers on: "create a team with Codex/Gemini",
  "add a Codex/Gemini teammate", "tell [name] to", "what has [name] done",
  "check on [name]", "wait for [name]", "shut down the team", "team status"
  — but only when a non-Claude LLM is involved.
user-invocable: true
---

# ateam — Multi-LLM Agent Teams

Manage teams of mixed LLM agents (Claude Code, Codex CLI, Gemini CLI) from a single orchestrator. Each teammate runs in its own session. The orchestrator assigns tasks, reads responses, and coordinates work.

## Variables

TEAM_STATE_DIR: ~/.claude/multi-teams
DEFAULT_BACKEND: auto
POLL_INTERVAL: 5
POLL_MAX_ATTEMPTS: 120

## Dependencies

This skill depends on the fork-terminal skill for terminal-based teammates:
- `~/.claude/skills/fork-terminal/tools/fork_terminal.py`
- `~/.claude/skills/fork-terminal/tools/send_to_surface.py`
- `~/.claude/skills/fork-terminal/cookbook/codex-cli.md`
- `~/.claude/skills/fork-terminal/cookbook/gemini-cli.md`
- `~/.claude/skills/fork-terminal/cookbook/claude-code.md`

## Routing Rules

Every operation checks the teammate's `protocol` field in team.json:
- IF `protocol == "terminal"` → use fork-terminal tools + sentinel protocol
- IF `protocol == "native"` → use Claude Code native Agent/SendMessage tools

## Workflow

### 1. Create Team + Spawn Members

User says: "Create a team with a Codex backend dev and a Claude infra dev"

1. Run: `python3 ~/.claude/skills/ateam/tools/team_manager.py create --name <team>`
2. For each **terminal teammate** (Codex/Gemini):
   a. READ the fork-terminal cookbook for the chosen LLM type (see Dependencies)
   b. READ `~/.claude/skills/ateam/prompts/teammate-bootstrap.md`
   c. Replace template variables: `{{NAME}}`, `{{TEAM}}`, `{{DESCRIPTION}}`, `{{SENTINEL_ID}}` (use `TEAM_MSG_1`), `{{INITIAL_TASK}}`
   d. Write the completed prompt to `/tmp/ateam-<team>-<name>-bootstrap.txt`
   e. Fork terminal:
      ```bash
      python3 ~/.claude/skills/fork-terminal/tools/fork_terminal.py \
        --backend DEFAULT_BACKEND --split auto \
        --delayed-input-file /tmp/ateam-<team>-<name>-bootstrap.txt \
        --delay 5 "<agent-launch-command>"
      ```
   f. Parse fork output for surface ref (`surface:N` or `%N`) and backend type
   g. Register:
      ```bash
      python3 ~/.claude/skills/ateam/tools/team_manager.py add-member \
        --team <team> --name <name> --llm <codex|gemini> --protocol terminal \
        --surface <ref> --backend <cmux|tmux>
      ```
3. For each **Claude teammate**:
   a. Create a native sub-team via `TeamCreate` tool (name: `<team>-native`) if it doesn't exist
   b. Spawn via `Agent` tool with `team_name: "<team>-native"` and `name: "<teammate-name>"`
   c. Register:
      ```bash
      python3 ~/.claude/skills/ateam/tools/team_manager.py add-member \
        --team <team> --name <name> --llm claude --protocol native \
        --native-team <team>-native
      ```
4. Report the team roster to the user

### 2. Send Task to Teammate

User says: "Tell backend-dev to implement the users API"

1. Look up the teammate in team.json
2. **IF terminal:**
   a. Get current `messageCount` for this member, compute sentinel: `TEAM_MSG_{count+1}`
   b. READ `~/.claude/skills/ateam/prompts/task-assignment.md`
   c. Replace `{{SENTINEL_ID}}` and `{{TASK_DESCRIPTION}}`
   d. Write to `/tmp/ateam-<team>-<name>-msg<N>.txt`
   e. Send:
      ```bash
      python3 ~/.claude/skills/fork-terminal/tools/send_to_surface.py \
        --surface <ref> --file /tmp/ateam-<team>-<name>-msg<N>.txt
      ```
   f. Update state:
      ```bash
      python3 ~/.claude/skills/ateam/tools/team_manager.py update-status \
        --team <team> --name <name> --status working
      python3 ~/.claude/skills/ateam/tools/team_manager.py log-message \
        --team <team> --from orchestrator --to <name> --sentinel TEAM_MSG_<N> --protocol terminal
      ```
3. **IF native:**
   a. Use `SendMessage` tool with `to: "<teammate-name>"` and the task description
   b. Update state:
      ```bash
      python3 ~/.claude/skills/ateam/tools/team_manager.py update-status \
        --team <team> --name <name> --status working
      python3 ~/.claude/skills/ateam/tools/team_manager.py log-message \
        --team <team> --from orchestrator --to <name> --protocol native
      ```

### 3. Check Status / Read Response

User says: "What has backend-dev done?"

1. Look up the teammate in team.json
2. **IF terminal:**
   ```bash
   python3 ~/.claude/skills/ateam/tools/read_teammate.py \
     --surface <ref> \
     --start-marker TEAM_RESPONSE_START --end-marker TEAM_RESPONSE_END \
     --blocked-start TEAM_BLOCKED_START --blocked-end TEAM_BLOCKED_END \
     --idle-marker TEAM_IDLE \
     --sentinel-id <last-sentinel-id>
   ```
   Parse the JSON result and report to user.
3. **IF native:**
   Use `SendMessage` to ask for a status update. Report the response.

### 4. Wait for Teammate

User says: "Wait for backend-dev to finish"

1. **IF terminal:**
   ```bash
   python3 ~/.claude/skills/ateam/tools/read_teammate.py \
     --surface <ref> \
     --start-marker TEAM_RESPONSE_START --end-marker TEAM_RESPONSE_END \
     --blocked-start TEAM_BLOCKED_START --blocked-end TEAM_BLOCKED_END \
     --idle-marker TEAM_IDLE \
     --sentinel-id <sentinel-id> \
     --poll --interval POLL_INTERVAL --max-attempts POLL_MAX_ATTEMPTS
   ```
2. **IF native:**
   Claude teammates notify via `SendMessage` automatically.
3. After response received, update status:
   ```bash
   python3 ~/.claude/skills/ateam/tools/team_manager.py update-status \
     --team <team> --name <name> --status idle
   ```

### 5. Broadcast

User says: "Tell everyone to commit their work"

1. List all members: `python3 ~/.claude/skills/ateam/tools/team_manager.py list --team <team>`
2. For each member, route through the appropriate protocol (Section 2 above)
3. Each terminal teammate gets a unique sentinel ID

### 6. Failure Recovery

If `read_teammate.py` returns `timeout` or `error`:

1. Update status:
   ```bash
   python3 ~/.claude/skills/ateam/tools/team_manager.py update-status \
     --team <team> --name <name> --status unresponsive
   ```
2. Report to user: "<name> appears unresponsive after <N> poll attempts"
3. Ask user what to do: respawn, skip, or abort
4. Do NOT auto-respawn — wait for user decision

### 7. Shutdown

User says: "Shut down the team"

1. **Ask user for confirmation first** — do not proceed without it
2. For terminal teammates, send the CLI-specific exit command, wait briefly, then kill the terminal:
   - **Codex**: `/exit`
   - **Gemini**: `/quit`
   - **Claude Code**: `/exit`
   ```bash
   # Send the exit command
   echo '<exit-command>' > /tmp/ateam-<team>-<name>-shutdown.txt
   python3 ~/.claude/skills/fork-terminal/tools/send_to_surface.py \
     --surface <ref> --file /tmp/ateam-<team>-<name>-shutdown.txt
   sleep 3
   # Kill the terminal (use member's backend field from team.json)
   # cmux:  cmux close-surface --surface <ref>
   # tmux:  tmux kill-pane -t <ref>
   ```
3. For Claude native teammates: send shutdown request via `SendMessage`
4. Optionally `TeamDelete` for the native sub-team
5. Clean up state files only with user permission

## Cookbook

| User says | Action |
|-----------|--------|
| "Create a team with..." | Section 1: Create Team + Spawn Members |
| "Add a [codex/gemini/claude] teammate..." | Section 1 (add single member to existing team) |
| "Tell [name] to..." | Section 2: Send Task |
| "What has [name] done?" | Section 3: Check Status |
| "Wait for [name]" / "Poll [name]" | Section 4: Wait for Teammate |
| "Tell everyone..." / "Broadcast..." | Section 5: Broadcast |
| "[name] is not responding" | Section 6: Failure Recovery |
| "Shut down the team" / "Dismiss the team" | Section 7: Shutdown |
| "Team status" / "Show the team" | Run `team_manager.py list --team <team>` and present roster |
