---
name: athena
description: Research and knowledge-management companion that builds a tiered wiki (unconfirmed → confirmed → consolidated → design) as the user investigates a topic. Use whenever the user wants to research something, investigate, do due diligence, compare options, explore a market, evaluate a technology, gather sources, confirm or consolidate findings, or turn scattered notes into a design doc. Triggers on phrases like "research X", "look into X", "what do we know about X", "dig into X", "confirm these findings", "consolidate the research on X", "promote this to design", "make this the main design" — even when the user doesn't explicitly mention notes, a wiki, or a folder. Also use when the user resumes work on a topic that already has a `research/<topic>/` or `design/<topic>/` folder.
---

# Athena — Tiered Research Wiki

Athena builds up a persistent, tiered knowledge base as the user researches. The knowledge flows through increasing levels of trust:

```
unconfirmed  →  confirmed  →  consolidated  →  design
  (raw)       (verified)    (synthesised)    (decisions)
```

The purpose of the tiers is to keep the user's decisions anchored in verified information. Raw research is almost always partly wrong; separating it from confirmed facts — and from the synthesized wiki pages and design docs built on top of those facts — means the user always knows what they can rely on.

## Why tiers matter (and what lives in each)

- **`unconfirmed/`** — raw findings from research: web searches, article summaries, claims from single sources. Treat everything here as potentially wrong. Great for breadth; bad for decisions.
- **`confirmed/`** — findings the user has explicitly verified, corrected, or contributed from their own knowledge. Treated as ground truth.
- **`consolidated/`** — synthesised wiki pages that weave many confirmed findings into coherent topic pages (entities, concepts, comparisons, timelines). This is the Karpathy-style wiki layer. Safe to rely on.
- **`design/`** — decisions and specs built on top of consolidated knowledge. Only exists in local storage, never in Obsidian. Safe to rely on.

## Storage modes

The user chooses once per topic. If they mention "Obsidian" or "vault", use Obsidian mode. Otherwise default to local mode. If uncertain, ask.

### Obsidian mode

Root: `$OBSIDIAN/research/<topic-slug>/`

```
$OBSIDIAN/research/<topic-slug>/
├── AGENTS.md           # topic-level index (CLAUDE.md symlinked to it)
├── CLAUDE.md -> AGENTS.md
├── log.md              # chronological audit trail (all ops)
├── unconfirmed/
│   ├── AGENTS.md
│   ├── CLAUDE.md -> AGENTS.md
│   └── <finding-files>.md
├── confirmed/
│   ├── AGENTS.md
│   ├── CLAUDE.md -> AGENTS.md
│   └── <finding-files>.md
└── consolidated/
    ├── AGENTS.md
    ├── CLAUDE.md -> AGENTS.md
    └── <synthesis-files>.md
```

Obsidian mode **never has a `design/` folder.** If the user wants to promote something to design while working in Obsidian mode, move the target files into the local project's `./design/<topic>/` and leave the Obsidian research wiki alone.

For vault I/O, prefer the `obsidian-cli` skill over raw file ops. For capturing web content into the vault, prefer `defuddle` over WebFetch. The user's global config mandates `$OBSIDIAN` env var — never hardcode the vault path.

### Local mode

Root: `./research/<topic-slug>/` for research, `./design/` for design.

```
./
├── AGENTS.md           # root index: pointers to research/<topic>/ and design/
├── CLAUDE.md -> AGENTS.md
├── research/
│   └── <topic-slug>/
│       ├── AGENTS.md
│       ├── CLAUDE.md -> AGENTS.md
│       ├── log.md
│       ├── unconfirmed/
│       │   ├── AGENTS.md
│       │   └── CLAUDE.md -> AGENTS.md
│       ├── confirmed/
│       │   ├── AGENTS.md
│       │   └── CLAUDE.md -> AGENTS.md
│       └── consolidated/
│           ├── AGENTS.md
│           └── CLAUDE.md -> AGENTS.md
└── design/
    ├── AGENTS.md       # lists topic subfolders with descriptions
    ├── CLAUDE.md -> AGENTS.md
    └── <topic-slug>/
        ├── AGENTS.md
        └── CLAUDE.md -> AGENTS.md
```

If the user says something like **"this is the main design"** (or "make this the top-level design", "promote to root design"), flatten the design into `./design/` directly without a topic subfolder. There can only be one main design.

If the user has picked Obsidian storage for research but is working in a local project, the local `./AGENTS.md` still gets a pointer — but it points into the Obsidian path (e.g. `$OBSIDIAN/research/<topic>/`).

## AGENTS.md as the index at every level

Every folder Athena creates gets an `AGENTS.md` plus a `CLAUDE.md` symlink. This file is the **index/router** for its folder — it tells whoever (human or agent) lands there what exists and where to go next.

Create the symlink with the user's standard procedure:

```bash
ln -sf AGENTS.md CLAUDE.md
```

### What each AGENTS.md contains

The AGENTS.md files have a job beyond being an index for Athena: any agent that lands in the folder should be able to read the local `AGENTS.md` and understand what these folders are and how content is organised.

**The skill-load reminder lives in one place only: the root `./AGENTS.md`.** That's the entry point every agent hits first, so one upstream reminder is enough — any agent that's going to touch research or design content will have passed through the root and seen it. Nested AGENTS.md files (topic, tier, design) should **not** repeat the reminder. They focus on their own job: describing the folder's purpose and listing its contents.

**Root `./AGENTS.md`** (local mode, created/updated whenever a topic is scaffolded in either storage mode):

```markdown
# Project Index

This project uses the **Athena** tiered research wiki. Research flows through
`unconfirmed/` → `confirmed/` → `consolidated/` → (optionally) `design/`, where
each tier is a higher trust level than the one before.

**If you're about to write, move, or promote any research or design content,
load the `athena` skill first.** Athena enforces tier discipline, registry
updates, and the audit log that keeps this structure coherent. Reading
existing `confirmed/`, `consolidated/`, or `design/` content directly is fine;
reading `unconfirmed/` content requires Athena (and a subagent when possible).

## Research
- [topic-one](research/topic-one/) — one-line description of the research question
- [topic-two]($OBSIDIAN/research/topic-two/) — stored in Obsidian vault

## Design
- [design/](design/) — main design doc (or list per-topic folders if not flattened)

<!-- If there are no research topics yet, say: _(no topics yet)_ -->
<!-- If there are no design docs yet, say: _(no design docs yet)_ -->
```

**`research/<topic>/AGENTS.md`** — topic-level routing:

```markdown
---
tags: [research, <topic-tag>]
date_created: YYYY-MM-DD
status: active
---

# <Topic Name>

This topic is part of the **Athena** tiered research wiki. Findings flow
`unconfirmed/` → `confirmed/` → `consolidated/` with increasing trust.
Reading `confirmed/` and `consolidated/` directly is fine; `unconfirmed/`
content should be read via a subagent.

## Research Question
<what the user wants to find out>

## Key Questions
- <sub-question 1>
- <sub-question 2>

## Decision Context
<why the user is researching this>

## Tiers
- [unconfirmed/](unconfirmed/) — raw findings, possibly wrong
- [confirmed/](confirmed/) — user-verified findings
- [consolidated/](consolidated/) — synthesised wiki pages

## See also
- [log.md](log.md) — chronological audit trail of every ingest, promotion, and move
```

**`<tier>/AGENTS.md`** — lists every file in the tier with a short description. This is the registry AND a reminder of the tier's trust level:

```markdown
# <Topic> — <tier>

<One sentence about the tier's trust level. e.g. for unconfirmed:
"Raw findings from research. Treat as potentially wrong until promoted.">

- [pricing.md](pricing.md) — pricing tiers, discounts, enterprise quotes
- [integrations.md](integrations.md) — Linear, Slack, GitHub integration claims
```

When a tier has no files yet, replace the bullet list with `_(empty — no files yet)_` so the reader knows the folder exists intentionally but hasn't been populated.

**`design/AGENTS.md`** and **`design/<topic>/AGENTS.md`** follow the same pattern — list design files or subfolders with one-line descriptions.

### The log.md file

Each topic folder has a `log.md` that is an append-only chronological audit trail. The topic `AGENTS.md` is the *content* index (what exists, where); `log.md` is the *time* index (what happened, when).

Format each entry with a consistent prefix so the log is grep-parseable:

```markdown
## [YYYY-MM-DD] <op> | <subject>
<optional one- or two-line detail>
```

Where `<op>` is one of: `ingest` (new research into unconfirmed), `confirm` (promote unconfirmed → confirmed), `reject` (remove from unconfirmed), `consolidate` (write or update a consolidated page), `promote-design` (move into `./design/`), `lint` (health check pass), `note` (freeform entry).

Example:
```markdown
## [2026-04-21] ingest | Pricing research for PM tools
Created unconfirmed/pricing.md with 4 findings (Linear, Asana, Monday, Shortcut). Sources: 6.

## [2026-04-21] confirm | Linear API integration
Moved finding from unconfirmed/integrations.md to confirmed/integrations.md.

## [2026-04-22] promote-design | Auth session handling
Moved consolidated/session-handling.md into ./design/ (main design).
```

A quick `grep "^## \[" log.md | tail -10` gives a timeline of recent activity — useful for both humans and agents resuming a topic.

### Registry discipline

- Every file in a tier must appear in that tier's `AGENTS.md`. Unlisted files are effectively invisible.
- Update the description when a file's scope shifts — the description should reflect what's in the file *now*.
- Update the registry **atomically** with the content change (same edit pass).
- Before creating a new file, read the tier's `AGENTS.md` first to see if something already covers that subtopic. Prefer appending to an existing file over creating a duplicate.

## What the main agent reads directly vs. delegates

This is the core behavioural rule of Athena. The tiers exist so the main agent can keep its context clean and only load trusted information.

**Main agent can read directly** (when needed to answer the user, not proactively):
- `confirmed/` files
- `consolidated/` files
- `design/` files
- Any `AGENTS.md` index at any level

**Main agent must NOT read directly** — always dispatch a subagent:
- Anything under `unconfirmed/`

**Main agent must NOT write directly** — always dispatch a subagent:
- Anything under `unconfirmed/`
- New research tasks in general (searching the web, reading articles, extracting findings — these all produce unconfirmed content)

The reasoning: unconfirmed content is voluminous, possibly wrong, and full of raw source material that would clog up the main context. Subagents can wade through it, extract what the user asked about, and return a clean summary.

### Dispatching subagents for unconfirmed work

Use the Agent tool. The subagent has no memory of the conversation, so the prompt must be self-contained: state the topic folder, the tier paths, the file registry convention, and exactly what output to return.

**For reading unconfirmed content:**

```
Agent({
  description: "Read unconfirmed findings on <subtopic>",
  prompt: `You are an Athena research reader. Do NOT modify any files.

  Topic folder: <absolute path to research/<topic>/>
  Task: Read the unconfirmed findings relevant to: <what the main agent needs>

  Start by reading research/<topic>/unconfirmed/AGENTS.md to find relevant files,
  then read those files. Return a concise summary:
  - What claims were found
  - Confidence level on each (as recorded in the finding)
  - Sources cited
  - Any contradictions you noticed

  Do not return raw file contents — summarise.`
})
```

**For new research (always writes to unconfirmed):**

```
Agent({
  description: "Research <topic/subtopic>",
  run_in_background: true,
  prompt: `You are an Athena research agent. Your writes go ONLY to unconfirmed/.

  Topic folder: <absolute path>
  Research question: <question>
  Key questions:
  1. <...>
  2. <...>

  Process:
  1. Read research/<topic>/AGENTS.md for context
  2. Read research/<topic>/unconfirmed/AGENTS.md to see what already exists
  3. Use WebSearch and WebFetch (prefer the defuddle skill for article extraction)
    to gather findings
  4. File findings into unconfirmed/<subtopic>.md using the finding format below
  5. Update unconfirmed/AGENTS.md with any new files or updated descriptions
  6. Append a log entry to research/<topic>/log.md using the format:
     ## [YYYY-MM-DD] ingest | <subject>
     <detail line>

  [Paste the Finding Format section here]

  Return: which files you created/updated, how many findings per subtopic, and
  any key questions you couldn't find good answers to.`
})
```

If sub-questions are independent (e.g., pricing vs. technical specs vs. reviews), dispatch multiple subagents in parallel in a single message.

### When the Agent tool is unavailable

Not every environment exposes the Agent tool (nested agents, restricted harnesses, some CLI runners). If dispatch is impossible, fall back gracefully:

- Do the research or unconfirmed-read in the main context directly. Don't tell the user about the fallback — it's an implementation detail.
- Keep writes strictly scoped to `unconfirmed/`. Do not touch `confirmed/`, `consolidated/`, or `design/` in the same pass.
- After the pass, prune what you bring back into your working context — keep only the summary you'd have gotten from a subagent. This preserves the "clean main context" goal even without delegation.

## Treating unconfirmed as provisional

When the main agent uses information — to answer a question, make a recommendation, support a decision — and any of that information traces back to **unconfirmed** content (even via a subagent's summary), flag it to the user explicitly. Example phrasings:

> "Based on unconfirmed findings: the enterprise tier is reported at $40/seat/month — worth verifying before you commit."

> "One caveat: the integration list I'm relying on here is still in unconfirmed/. Want me to verify before you act on it?"

The user should never be surprised later that a decision was built on shaky ground. When a decision is significant, ask before proceeding.

## Flows

### Starting a research session

1. Derive a kebab-case topic slug from what the user said.
2. Decide storage mode (Obsidian if mentioned, else local; ask if unclear).
3. Create the folder skeleton: topic root + three tier folders + an `AGENTS.md` + `CLAUDE.md` symlink at every level + an empty `log.md` at the topic root.
4. Write the topic `AGENTS.md` with the research question, key questions, and decision context.
5. Create/update the **local project's root `./AGENTS.md`** with a pointer to the new topic — in *both* storage modes. In Obsidian mode the pointer uses the `$OBSIDIAN/research/<topic>/` path; in local mode it uses the relative `research/<topic>/` path. Also create the root `CLAUDE.md -> AGENTS.md` symlink if it doesn't exist yet. The purpose of the root file: any agent that lands in the project should see the Athena wiki exists and know to load the skill before editing research.
6. Append a `note | Topic created` entry to the topic's `log.md` recording the scaffold (storage mode, tiers created).
7. Tell the user what was set up and that research will land in `unconfirmed/` until they confirm.

### Conducting research

Always dispatched to a subagent (main agent never writes unconfirmed directly). See the dispatch templates above. Parallelise across independent sub-questions when possible.

### Confirmation flow (unconfirmed → confirmed)

Surface findings for review periodically — "I've added findings on <subtopic>. Want to review and confirm?"

When the user confirms a finding:
- Read the unconfirmed file (via subagent if available and the file is large or unfamiliar; directly is fine when the user pointed at a specific finding the main agent already knows about).
- **Move** the finding out of `unconfirmed/<file>.md` — do not leave a copy behind. The same information must never live in two tiers simultaneously; promotion is a move, not a duplication.
- Append it to `confirmed/<file>.md` (create the file if needed, with matching frontmatter).
- If the source unconfirmed file is empty after the move, delete the empty file.
- Update both `unconfirmed/AGENTS.md` and `confirmed/AGENTS.md` registries to reflect the move (and remove the file entry from the unconfirmed registry if the file was deleted).
- Append a `confirm` entry to the topic `log.md`.

When the user rejects: delete the finding from `unconfirmed/`, don't promote. Append a `reject` entry to `log.md`.

When the user supplies a fact directly (their own knowledge, their own preferences): write straight to `confirmed/` — they are the source. Nothing lands in `unconfirmed/` first in this case.

### Consolidation flow (confirmed → consolidated)

Triggered when the user asks to "synthesise", "consolidate", "write up what we know about X", or when enough confirmed findings accumulate that a synthesis would be valuable (offer it).

Consolidation produces coherent topic pages — e.g. an entity page on a competitor, a comparison table, a timeline, a concept explainer — that weave confirmed findings together with cross-references. These pages live in `consolidated/` and cite the confirmed findings they were built from.

The main agent can do this directly (reads and writes are both on safe tiers). Update `consolidated/AGENTS.md` with the new page and append a `consolidate` entry to `log.md`.

### Design promotion (local only)

When the user says "this is part of the design", "move this to design", "promote this to design" — or similar — **move** the relevant consolidated content into `./design/<topic>/` (or flat `./design/` if they indicate it's the main design). The "no duplication" rule applies here too: the same material must not live in both `consolidated/` and `design/` at once.

Steps:
1. Create `./design/<topic>/` (or use `./design/` directly for main design) with its own `AGENTS.md` + `CLAUDE.md` symlink.
2. Restructure the source consolidated page into design files with clear decision-oriented framing (decision / rationale / alternatives / open questions). Link back to any `confirmed/` findings the design rests on, since those stay in place.
3. **Delete the source page from `consolidated/`** and remove its entry from `consolidated/AGENTS.md`. If the consolidated folder is now empty, leave its AGENTS.md as the empty-case template.
4. Update `./design/AGENTS.md` (and root `./AGENTS.md`) with pointers to the new design file.
5. Append a `promote-design` entry to the topic research `log.md` noting the move (source path → destination path).

Obsidian-mode topics still promote to the **local** `./design/` folder — the Obsidian vault never holds design. The source page is deleted from `$OBSIDIAN/research/<topic>/consolidated/` as part of the move.

### Resuming a topic

If `research/<topic>/` or `$OBSIDIAN/research/<topic>/` already exists:
1. Read its topic `AGENTS.md` — that's the map.
2. Load confirmed/consolidated content as the user's questions demand.
3. Dispatch a subagent for any unconfirmed reads.
4. Pick up where they left off.

## File formats

### Finding format (for unconfirmed/ and confirmed/)

```markdown
### <Descriptive title>

| Field | Value |
|-------|-------|
| Source | [Source Name](URL) |
| Found | YYYY-MM-DD |
| Confidence | high / medium / low |
| Tags | #tag1 #tag2 |

<The actual finding. Be specific — quotes, numbers, concrete details. Avoid vague summaries.>

---
```

Confidence levels: `high` = multiple reliable sources agree or authoritative primary source; `medium` = single credible source or multiple weaker ones; `low` = single weak source, anecdotal, or potentially outdated.

### Frontmatter for tier files

```markdown
---
tags: [research, <topic-tag>, <subtopic-tag>]
parent: "[[AGENTS]]"
date_created: YYYY-MM-DD
date_updated: YYYY-MM-DD
---
```

### Consolidated page format

Consolidated pages are free-form wiki articles. Suggested structure:

```markdown
---
tags: [research, <topic-tag>, consolidated]
date_created: YYYY-MM-DD
date_updated: YYYY-MM-DD
sources: <count of confirmed findings used>
---

# <Title>

## Summary
<2-4 sentence synthesis>

## <Sections as the content demands>

## References
- [[confirmed/<file>#<heading>]] — what this reference supports
- [[confirmed/<other-file>]]
```

Cross-reference liberally with wikilinks — that's what makes the wiki layer useful.

### Design file format

Design files are decision docs. They should be opinionated and concrete. Include: the decision, the rationale, the alternatives considered, and links back to the consolidated/confirmed material that informed it.

## Principles

- **The tiers are a trust gradient.** Everything you infer or recommend should be honest about which tier its evidence lives in.
- **The AGENTS.md indexes are the nervous system.** Keep them current, or the whole structure rots.
- **Keep the main context clean.** Dispatch aggressively into `unconfirmed/`. Bring back summaries, not raw content.
- **The user is always the authority.** Their direct statements go to `confirmed/`. Their explicit promotions move things between tiers. Don't auto-promote without them.
- **One topic, one folder.** Don't scatter related research across multiple topic folders. If a new angle emerges, add a subtopic file, not a new topic.
