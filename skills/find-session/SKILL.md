---
name: find-session
description: >
  Find Claude Code sessions by custom title or by searching session content across all projects.
  Use when the user wants to search for a named session, find a session by title,
  find a session by what was discussed in it, or list all named sessions.
  Trigger on /find-session or phrases like "find my session", "search sessions by name",
  "where is my dora session", "find the session where I worked on auth", etc.
  This works even for sessions that were never renamed — it searches through conversation content.
---

# find-session — Search Sessions by Title or Content

Search for Claude Code sessions across all projects. Works two ways:

- **By title**: finds sessions renamed with `/rename` (matches the custom title)
- **By content**: searches through user messages in session transcripts, so you can find sessions even if they were never named

## Usage

Search by title or content:

```bash
bash ~/.claude/skills/find-session/scripts/find-session.sh "<search_term>"
```

List all named sessions:

```bash
bash ~/.claude/skills/find-session/scripts/find-session.sh
```

## Instructions

1. Parse the user's input to extract the search term (if any)
2. Run the script above
3. Show the output verbatim
4. If results are found:
   - For **named sessions**: remind the user they can resume with `claude --resume <title>`
   - For **content-matched sessions**: the resume command uses the session ID since there's no title

## Testing

See `TESTING.md` in this skill's directory for instructions on how to generate and run test cases.
