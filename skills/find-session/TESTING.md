# Testing find-session

## How to generate test cases

The test cases are derived from real session data — don't hardcode session IDs or specific results since sessions change over time. Instead, follow this process:

### 1. Find testable sessions

Scan a sample of JSONL files in `~/.claude/projects/` to find sessions with distinctive user messages. Look for:

- Sessions **with custom titles** (records with `"type":"custom-title"`) — for title search tests
- Sessions with **specific/unique terms** in user messages (tool names, error messages, project-specific jargon) — for content search tests
- Sessions where the user message is stored as **character-per-block** format (content array of single-char strings) — to verify the joining logic works

### 2. Categories to cover

Each test round should include searches that exercise these paths:

| Category | What to test | How to find a test case |
|----------|-------------|------------------------|
| **Title match** | Search term matches a custom title | Find any session with `"type":"custom-title"`, use part of the title as search |
| **Exact phrase in content** | Multi-word phrase that appears verbatim in a user message | Grep for a distinctive 2-3 word phrase from a real user message |
| **Keyword extraction** | Natural phrase with stop words ("run the main server") | Find a user message with common words mixed in; verify stop words are stripped and the right session is found |
| **Unique technical term** | Single specific word (e.g. a package name, tool, error code) | Grep for a distinctive term that only appears in 1-3 sessions |
| **Character-per-block** | Session where content is stored as individual keystrokes | Check a few sessions — if `content` array has 20+ single-char string blocks, that's one |
| **No match** | Search for something that doesn't exist | Use a nonsense string |
| **Progressive fallback** | Multi-word search where exact phrase doesn't match but individual words do | Use a phrase the user would say but that doesn't appear verbatim |

### 3. What to verify for each test

- **Correct session found**: The expected session appears in results
- **Low noise**: Results don't include dozens of unrelated sessions
- **No false positives from injected content**: Results shouldn't come from `<system-reminder>`, `Base directory for this skill:`, or `[Request interrupted` text
- **Preview quality**: The preview shows a real human message, not single characters or system text
- **Strategy label**: Check that the strategy shown (exact match, all keywords, any keyword) makes sense

### 4. Running a test

```bash
bash ~/.claude/skills/find-session/scripts/find-session.sh "<search_term>"
```

Or test the Python directly:

```bash
python3 ~/.claude/skills/find-session/scripts/find_session.py "<search_term>"
```

### 5. Known edge cases

- **Keystroke-streamed messages**: Some sessions store user input as individual characters in the content array. The script joins these before searching. Test with a term you know came from such a session.
- **Stop words**: Phrases like "turn this into a html" should work — stop words ("this", "into", "a") are stripped, leaving meaningful keywords.
- **Injected content filtering**: Skill invocation text (`Base directory for this skill:...`), system tags (`<system-reminder>`), and interruption markers (`[Request interrupted`) are all filtered out. A search for a word that only appears in these should return no results.
