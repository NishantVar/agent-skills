# agent-skills — conventions for agents

## Per-skill todo files

Each skill maintains an open backlog at `todo/<skill-name>.md` (e.g. `todo/cmux-observability.md`, `todo/p2p.md`). One file per skill, at repo root under `todo/`.

- **Tracked in git** — todo files reference PRs, design docs, branch names, and rationale that belong with the project, not the local checkout. Don't `.gitignore` them.
- **Living documents** — update as items land or new ones surface. Mark a header line with the date of the last meaningful refresh.
- **Format is free** — markdown, organized however suits the skill. Cross-link to design docs in `$OBSIDIAN/plans/` rather than duplicating their contents.
- **New skill checklist** — when adding a skill to `skills/<name>/`, create `todo/<name>.md` even if empty (a placeholder line is fine). This keeps the pattern uniform and discoverable.

When picking up work after a break, the per-skill todo is the first thing to read alongside `skills/<name>/SKILL.md`.

## Skill Authoring

- When creating or editing a skill `SKILL.md`, keep the YAML frontmatter valid. If a `description` contains a colon, quotes, backticks, or other punctuation, write it as a folded block scalar:

  ```yaml
  description: >-
    Use when designing or reviewing agent-engineering artifacts: skills, agent instruction files, ...
  ```

- After editing frontmatter, parse or validate it before considering the skill fixed; invalid YAML causes the skill loader to skip the entire skill.

- When compiling a `SKILL.glyph` to its IR, use `glyph icompile` rather than `glyph compile -o SKILL.ir.json` — the explicit `-o` form errors when the output path already exists as a file. `icompile` handles existing IR files in place. Then `glyph validate-output <SKILL.ir.json> <SKILL.md>` (IR path first, MD second).
