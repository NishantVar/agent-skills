---
name: find-session
description: Find and resume Claude Code sessions by searching titles and conversation content. Use when the user wants to find a previous session, search session history, or resume a session by keyword. Triggers on phrases like "find session", "search sessions", "which session had", "resume the session where", "find the session about".
---

# Find Session

Run the find-session script with the user's search terms and display the results.

## Steps

1. Extract the search terms from the user's request
2. Run the script:

```bash
python3 ~/.claude/skills/find-session/scripts/find-session.py <search terms>
```

3. Display the output to the user EXACTLY as produced by the script. Do NOT summarize, reformat into tables, or omit any information. Every single result MUST include its full `Resume:` command so the user can copy-paste it.
4. If the user wants to resume a session, tell them to paste the `Resume:` command in a new terminal.
