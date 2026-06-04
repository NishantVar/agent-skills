---
name: cleanup
description: End-of-session sweep that scans the conversation for non-trivial decisions, preferences, conventions, gotchas, and facts the user surfaced that aren't yet persisted anywhere durable — then proposes a single batched list of what to save and where. Use when the user says "cleanup", "what should we save before closing", "anything we should write down", "end of session", "wrap up", "before I close this", or otherwise signals they're about to end the conversation and wants to capture loose knowledge. Also reasonable to suggest proactively when a long session is clearly winding down.
---

# Cleanup — End-of-Session Knowledge Sweep

The user invokes this skill when they're about to close a session. The job is to look back over the whole conversation, find things that *should have been written down somewhere but weren't*, and present them as a single batched list with proposed destinations. The user then picks what to save.

## Why this exists

Long sessions accumulate knowledge that never makes it into durable storage: a preference the user stated mid-conversation, a workaround we discovered, a convention we settled on, a fact about the user's environment, a decision rationale that future-you will need but won't be able to reconstruct. If it lives only in the transcript, it's effectively lost the moment the session ends.

This skill is the safety net. It's not trying to capture *everything* — it's trying to catch the things a future human or agent would genuinely benefit from knowing, that aren't already captured.

## What counts as "worth saving"

Look for items that are **non-trivial** (the future reader couldn't easily re-derive them) AND **not already persisted**. Strong candidates:

- **User preferences and conventions** the user stated this session ("always use X", "I prefer Y", "never do Z"). These belong in a CLAUDE.md / AGENTS.md / memory file.
- **Project-specific facts** discovered this session: how a system actually works, what a flag does, where something lives, why a past decision was made.
- **Gotchas, footguns, workarounds**: things that bit us this session and would bite the next agent the same way.
- **Decisions with rationale**: "we chose X over Y because Z". The rationale is the valuable part — it usually evaporates.
- **Environmental facts about the user**: their tools, accounts, paths, identities, schedules — anything personal that came up and would be useful next time.
- **Open threads / TODOs** the user mentioned but never formalized.
- **Names, URLs, IDs, credentials-locations** (not credentials themselves) that the user mentioned and the next agent will need.

Weak / skip:
- Things the user already wrote into a file during the session.
- Things already covered by an existing CLAUDE.md / memory entry / design doc (check before suggesting).
- One-shot task outputs (the code we wrote, the answer we computed) — those live in git or the artifact itself.
- Trivial restatements of well-known facts.

When in doubt, lean toward including it — the user will skip the noise faster than they'd reconstruct a missed item.

## How to route each item (smart routing)

For every candidate, propose a concrete destination. Use this routing logic:

- **Global user preferences, identity, personal facts** (apply across all projects): `~/.claude/memory/<topic>.md`, and a one-line reference added to `~/.claude/CLAUDE.md`'s Memory section in the format the user already uses there. Check `~/.claude/CLAUDE.md` to see existing memory files first — extend an existing one if the topic fits.
- **Project-specific conventions, facts, gotchas** (apply only to this repo): the project's `CLAUDE.md` or `AGENTS.md` (check which the project uses — some projects symlink one to the other).
- **Design decisions, plans, architectural rationale**: `$OBSIDIAN/plans/<topic>-design-YYYY-MM-DD.md`. Use the `obsidian` CLI if available rather than raw file I/O.
- **Research findings, notes, due-diligence**: if the project uses an Athena-style tiered wiki (`research/` + `design/` folders with `unconfirmed/confirmed/consolidated/`), route into the appropriate tier and load the `athena` skill rather than writing directly.
- **Open TODOs**: project's `TODO.md`, `design/todo.md`, or wherever the project already tracks them. Check first.
- **Skill or agent-config improvements** (e.g., user noticed a skill should behave differently): the skill's `SKILL.md` or the relevant agent definition file.

Always propose the *most specific* existing file before suggesting a new one. Creating a new file is fine when nothing fits, but prefer extending what's already there.

## How to present (single batch summary)

Output one message with the full list. Format:

```
## Cleanup sweep — N candidates

### 1. <short title>
**What:** <one or two sentences capturing the item>
**Why save:** <one sentence on what would be lost otherwise>
**Destination:** <absolute path or path-relative-to-repo>
**Action:** <append / new file / edit existing section>

### 2. ...
```

After the list, end with a short prompt like: *"Tell me which to save (numbers, ranges, 'all', or 'none'), or edit anything inline."* Then wait for the user's reply before writing anything.

If the sweep finds nothing worth saving, say so explicitly — don't pad. "Nothing non-trivial surfaced this session that isn't already captured" is a valid result and worth more than a fabricated list.

## Doing the sweep

1. **Read what already exists** before judging novelty. At minimum: the project's `CLAUDE.md` / `AGENTS.md`, `~/.claude/CLAUDE.md`, and any memory files it references that look topically relevant. If the project has a `design/` or `research/` tree, glance at the index. This prevents proposing things that are already saved.
2. **Walk the conversation chronologically**, not just the recent turns. Items from early in a long session are exactly the ones most at risk of being lost.
3. **Group related items** into a single entry rather than fragmenting (e.g., three preferences about the same tool → one entry).
4. **Be specific in destinations**. "Save to memory" is not a destination; `~/.claude/memory/google-workspace-cli.md` is.
5. **Don't write anything yet.** The skill's job in this first pass is to *propose*, not to act. The user picks; you write in the follow-up turn.

## After the user picks

For each approved item:
- Append/edit the file as proposed. Prefer `Edit` for additions to existing files (preserves surrounding content); use `Write` only for new files.
- If adding a new file under `~/.claude/memory/`, also add the one-line reference entry to `~/.claude/CLAUDE.md` so future sessions discover it.
- If the destination is in the Obsidian vault, use the `obsidian` CLI per the user's standing preference.
- Confirm with a terse summary of what landed where. Don't restate the content.

## Things to be careful about

- **Don't save secrets.** API keys, tokens, passwords, private credentials — flag them as "noted, but not saving" and remind the user to put them in their secrets manager.
- **Don't echo things the user said in frustration as if they're durable preferences.** "Ugh I hate when X" mid-debug ≠ "user prefers not-X always". Use judgment; when ambiguous, ask.
- **Don't invent rationale.** If the user made a decision but never explained why, capture the decision without fabricating a justification. "Chose X (rationale not captured)" beats a made-up reason.
- **Respect existing structure.** If the project clearly uses Athena tiers, don't dump research findings into `CLAUDE.md`. If the user has a memory-file naming pattern, follow it.
