---
name: judgy
description: Iterative code review using an external AI reviewer (codex, gemini, or claude) in a forked terminal. The reviewer finds issues across multiple rounds while Claude fixes high/medium severity problems between rounds. Use this skill when the user asks for a code review, wants a second opinion on their changes, says "review my code", "check my diff", "judgy", or wants an external AI reviewer to audit local changes before committing. Also triggers for "review staged changes", "review diff to main", or any request for multi-pass code review. Supports "review with gemini", "review with codex", "review with claude".
---

# Judgy

Iterative code review that forks a terminal, runs an external AI reviewer to find issues in local changes, and has Claude fix high/medium severity problems between rounds. The cycle repeats until either no high/medium issues remain or the maximum number of rounds is reached.

The key insight: the reviewer is the critic, Claude is the fixer. The reviewer never modifies files — it only reports what it finds. Claude reads those findings, fixes the serious ones, and sends the reviewer back to check again. This adversarial loop catches issues that a single-pass review would miss, including problems introduced by the fixes themselves.

## Variables

MAX_ROUNDS: 3
REPORT_DIR: .judgy
DEFAULT_REVIEWER: codex
REVIEWER_GUIDANCE: false
REVIEWER_FIX_FIRST: false

## Reviewer Commands

Parse the user's request for a reviewer preference (`codex`, `gemini`, or `claude`). If none specified, use `DEFAULT_REVIEWER`. Then READ the corresponding fork-terminal cookbook for CLI conventions:

| Reviewer | Cookbook | Round 1 launch command |
|----------|---------|------------------------|
| codex | `/Users/nishant/.claude/skills/fork-terminal/cookbook/codex-cli.md` | `codex -c 'model_reasoning_effort="xhigh"' --dangerously-bypass-approvals-and-sandbox "$(cat /tmp/${JUDGY_SESSION}-round1.txt)"` |
| gemini | `/Users/nishant/.claude/skills/fork-terminal/cookbook/gemini-cli.md` | `gemini --model gemini-3-pro-preview -y -i "$(cat /tmp/${JUDGY_SESSION}-round1.txt)"` |
| claude | `/Users/nishant/.claude/skills/fork-terminal/cookbook/claude-code.md` | `claude --model opus --dangerously-skip-permissions "$(cat /tmp/${JUDGY_SESSION}-round1.txt)"` |

**Rounds 2+ send text directly into the already-running reviewer session — no new process. Use the backend-appropriate send command from the Backend Commands section below.**

The rest of the workflow is identical regardless of which reviewer is used. The prompt templates are the same — only the Round 1 launch command and backend interaction commands change.

## Backend Commands

After `fork_terminal.py` runs, parse its output to detect the backend and capture the ref needed for sending and polling. The backends now include the ref in their output:

| Fork output prefix | Backend | Ref format | Send text | Enter | Poll screen |
|-------------------|---------|------------|-----------|-------|-------------|
| `cmux surface split` | cmux | `surface:N` (parse from `[ref=surface:N]` in output) | `python3 .claude/skills/fork-terminal/tools/send_to_surface.py --surface <ref> --file /tmp/${JUDGY_SESSION}-roundN.txt` | (included in send_to_surface.py) | `cmux read-screen --surface <ref>` |
| `tmux pane split` | tmux | `%N` (parse from `[ref=%N]` in output) | `python3 .claude/skills/fork-terminal/tools/send_to_surface.py --surface <ref> --file /tmp/${JUDGY_SESSION}-roundN.txt --backend tmux` | (included in send_to_surface.py) | `tmux capture-pane -p -t <ref>` |
| `stdout:` / `Windows terminal` | native | none | N/A | N/A | N/A |

**Native backend**: Opens a new terminal window with no programmatic way to send text or read screen output. Only single-pass review is possible with native — use `REVIEWER_FIX_FIRST: true` to have the reviewer find and fix in one shot, or accept a report-only Round 1 with no follow-up rounds.

## Mode Variables

**`REVIEWER_GUIDANCE: false`** — When `true`, the reviewer annotates each finding with a suggested fix approach. Claude still does the actual fixing, but uses the reviewer's suggestions as guidance. Useful when you want the external reviewer's perspective on *how* to fix things, not just *what* is broken.

**`REVIEWER_FIX_FIRST: false`** — When `true`, the reviewer finds AND fixes all HIGH and MEDIUM issues in a single Round 1 pass, then the process ends immediately. No iterative rounds — the reviewer handles everything in one shot. Use this when you want a fast, single-pass review-and-fix rather than the iterative Claude-fixes loop.

## Instructions

### Determine Diff Mode

Parse the user's request to figure out what code to review:

- **Default** (no arguments): all local changes → `git diff HEAD`
- **staged** or **--staged**: only staged changes → `git diff --cached`
- **diff to \<branch\>**: diff against a specific branch → `git diff <branch>...HEAD`

Run the appropriate `git diff` command and capture the output. If the diff is empty, tell the user there's nothing to review and stop.

### Generate Report Path and Session ID

Create the report directory if it doesn't exist, generate a timestamped report path, and generate a session ID for unique temp files:

```bash
mkdir -p REPORT_DIR
REPORT_PATH="REPORT_DIR/report-$(date +%s).md"
JUDGY_SESSION="judgy-$$-$(date +%s)"   # e.g. judgy-12345-1773095000
```

Use `JUDGY_SESSION` as the prefix for all temp files this run (e.g. `/tmp/${JUDGY_SESSION}-round1.txt`, `/tmp/${JUDGY_SESSION}-run.sh`). This prevents concurrent judgy sessions from clobbering each other's prompt files.

## Workflow

### 1. Setup

1. Parse the user's request to determine diff mode, resolve the git diff command, and identify the reviewer.
2. Run a quick `git diff --stat` to verify there are changes. If empty → tell user, stop.
3. Generate the timestamped report path.
4. READ the corresponding fork-terminal cookbook for the chosen reviewer (see table above).
5. READ the prompt partials — these are substituted into all prompt templates:
   - `prompts/partials/severity-categories.md` → use as `{{SEVERITY_CATEGORIES}}`
   - `prompts/partials/fixed-format.md` → use as `{{FIXED_FORMAT}}`
6. Determine the Round 1 mode:
   - If `REVIEWER_FIX_FIRST` is `true` → READ `prompts/fix_prompt.md`
   - Otherwise → READ `prompts/review_prompt.md`

### 2. Round 1 — Fork Terminal

**If `REVIEWER_FIX_FIRST` is `true`:** Use `prompts/fix_prompt.md` and skip to the fix flow below. After the reviewer finishes, collect findings and fixes from `JUDGY_FIXED_START`/`JUDGY_FIXED_END`, then jump directly to Synthesize & Present — no further rounds.

**Normal flow (`REVIEWER_FIX_FIRST` is `false`):**

1. Build the Round 1 prompt from `prompts/review_prompt.md`:
   - Replace `{{DIFF_COMMAND}}` with the resolved git diff command (e.g. `git diff HEAD`, `git diff --cached`, `git diff main...HEAD`). The reviewer will run this itself — no need to pass the diff content.
   - Replace `{{AGENT_CONTEXT}}` — **only when using the default diff mode** (all local changes, no user-specified scope): summarize what you (Claude) changed in this session and why, so the reviewer understands the intent behind those changes. If the user explicitly specified staged, a branch, or specific files, leave `{{AGENT_CONTEXT}}` empty — the reviewer doesn't need the backstory since the user curated what to review.
   - Replace `{{GUIDANCE_FORMAT}}` — use the appropriate output format block based on `REVIEWER_GUIDANCE`:
     - If `REVIEWER_GUIDANCE` is `false` (default):
       ```
       Print your findings in this exact format:

       JUDGY_REPORT_START
       - [HIGH] description — file:line
       - [MEDIUM] description — file:line
       - [LOW] description — file:line
       JUDGY_REPORT_END
       ```
     - If `REVIEWER_GUIDANCE` is `true`:
       ```
       Print your findings in this exact format. For HIGH and MEDIUM issues, include a FIX suggestion:

       JUDGY_REPORT_START
       - [HIGH] description — file:line | FIX: concise suggestion for how to fix it
       - [MEDIUM] description — file:line | FIX: concise suggestion for how to fix it
       - [LOW] description — file:line
       JUDGY_REPORT_END
       ```
2. Write the prompt to `/tmp/${JUDGY_SESSION}-round1.txt`. Then write a wrapper script `/tmp/${JUDGY_SESSION}-run.sh`:
   ```bash
   #!/bin/bash
   <REVIEWER_COMMAND> "$(cat /tmp/${JUDGY_SESSION}-round1.txt)"
   ```
   Fork using the wrapper — this avoids shell argument collapsing of multiline prompts:
   ```
   python3 .claude/skills/fork-terminal/tools/fork_terminal.py --backend auto --split auto -- bash /tmp/${JUDGY_SESSION}-run.sh
   ```
3. **Parse the fork output** to detect the backend and capture the ref (e.g. `surface:42` for cmux, `%7` for tmux) — store both for subsequent interactions.
4. Wait for the reviewer to complete by polling with the backend-appropriate poll command (see Backend Commands) until it has finished (look for the shell prompt returning or exit indicator).
5. Read the screen output and extract everything between `JUDGY_REPORT_START` and `JUDGY_REPORT_END`.

**Fix flow (when `REVIEWER_FIX_FIRST` is `true`):**

1. Build the Round 1 prompt from `prompts/fix_prompt.md`:
   - Replace `{{DIFF_COMMAND}}`, `{{AGENT_CONTEXT}}` as above.
   - No `{{PREVIOUS_FINDINGS}}` or `{{FIXES_APPLIED}}` — this is Round 1, there's nothing prior.
2. Fork the terminal and launch the reviewer exactly as in the normal flow above.
3. Parse the fork output to detect backend and capture the ref.
4. Wait for the reviewer to finish using the backend-appropriate poll command (see Backend Commands). Look for `JUDGY_FIXED_END` or shell prompt returning.
5. Extract the `JUDGY_FIXED_START`/`JUDGY_FIXED_END` block — this contains both what was found and what was fixed.
6. Continue to "Between Rounds — Claude Fixes" below — the loop runs the same way as normal mode, except the reviewer does the fixing (not Claude) and subsequent rounds also use `prompts/fix_prompt.md`.

### 3. Between Rounds — Claude Fixes

After each round's reviewer output:

1. **Parse the round's output** — extract HIGH, MEDIUM, LOW issues from the appropriate markers.
2. **Check stop condition**: If no HIGH or MEDIUM issues were found → stop the loop, skip to Synthesize & Present.
3. **Fix issues**:
   - Normal mode: Claude fixes all HIGH and MEDIUM issues using its own editing tools (Read, Edit, Write). If `REVIEWER_GUIDANCE` is `true`, use the reviewer's `FIX:` suggestions as guidance.
   - `REVIEWER_FIX_FIRST` mode: the reviewer already handled fixes — no action needed from Claude. If HIGH/MEDIUM issues were found and fixed, continue to the next round to verify nothing remains.
4. Accumulate LOW issues into a running list across all rounds (do NOT fix these).
5. **After fixing, re-sync the diff scope** so the next round sees the current state:
   - **Staged mode** (`git diff --cached`): stage the fixed files — `git add <files you edited>` — otherwise the reviewer will still see the original staged version next round.
   - **Branch-diff mode** (`git diff <branch>...HEAD`): commit the fixes — `git commit -am "judgy fixes round N"` — the diff command only reflects committed changes.
   - **Default mode** (`git diff HEAD`): no extra step needed — unstaged edits are visible immediately.

### 4. Rounds 2–N — Send via cmux

The reviewer is still running interactively in the forked terminal. Do NOT start a new reviewer process — just send the follow-up prompt text directly into the existing session, as if you're continuing the conversation.

For each subsequent round (up to `MAX_ROUNDS`):

1. Choose the prompt template:
   - `REVIEWER_FIX_FIRST` mode → `prompts/followup_fix_prompt.md` (reviewer checks for remaining/new issues and fixes them; outputs `JUDGY_FIXED` markers)
   - Normal mode → `prompts/followup_prompt.md` (reviewer reports only; Claude fixes)
   Build the prompt by replacing:
   - `{{ROUND_NUMBER}}` with the current round number
   - `{{PREVIOUS_FINDINGS}}` with the previous round's findings/fixes
   - `{{FIXES_APPLIED}}` with a summary of what Claude changed (normal mode only)
   - `{{DIFF_COMMAND}}` with the resolved git diff command
   - `{{GUIDANCE_FORMAT}}` as in Round 1 (normal mode only)
2. Write the prompt to a temp file `/tmp/${JUDGY_SESSION}-roundN.txt` (where N is the round number) to avoid shell escaping issues.
3. Send the prompt text directly into the running reviewer session using the backend-appropriate send command (see Backend Commands).
4. Poll using the backend-appropriate poll command until the reviewer finishes (new `JUDGY_REPORT_END` appears or shell prompt returns).
5. Extract the latest `JUDGY_REPORT_START`/`JUDGY_REPORT_END` block.
6. Return to "Between Rounds — Claude Fixes" above.

### 5. Synthesize & Present

After the loop ends (clean exit or max rounds):

1. Collect all findings across all rounds.
2. Write a structured report to the timestamped report path using this format:

```markdown
# Judgy Review Report

## Summary
- Rounds completed: X / MAX_ROUNDS
- Stopped because: [no high/medium issues found | max rounds reached]
- Total issues found: X high, X medium, X low
- Issues fixed: X high, X medium

## Round Details

### Round 1
#### Issues Found
- [HIGH] description — file:line
- [MEDIUM] description — file:line
- [LOW] description — file:line

#### Fixes Applied
- Fixed [HIGH] description — what Claude changed
- Fixed [MEDIUM] description — what Claude changed

### Round 2
...

## Remaining Low-Severity Issues
- [LOW] description — file:line — suggestion
- [LOW] description — file:line — suggestion
```

3. Present a **synthesized summary** to the user:
   - **Fixed issues**: All high/medium severity issues found and fixed, organized by round.
   - **Remaining low-severity issues**: All low-severity findings across ALL rounds, listed so the user can decide what to address.
   - **Round count**: How many rounds ran and why it stopped (clean bill of health vs max rounds reached).
   - **Report location**: Path to the full report file.
