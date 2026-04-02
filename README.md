# agent-skills

Write a skill once, use it in Claude Code, Codex CLI, and Gemini CLI.

All three agents use the same core format: `SKILL.md` with `name` + `description` YAML frontmatter ([Agent Skills open standard](https://agentskills.io/specification)). This repo exploits that shared format so you only write the skill body once.

## Repo Structure

```
agent-skills/
├── install.sh
├── uninstall.sh
├── test.sh
├── README.md
└── skills/
    └── <skill-name>/
        ├── SKILL.md            # All frontmatter + skill body
        ├── agents/
        │   └── openai.yaml    # Codex UI metadata (optional)
        ├── references/         # Docs loaded on demand
        ├── scripts/            # Executable helpers
        └── assets/             # Templates, images
```

## Install

```bash
./install.sh claude          # All skills → Claude Code
./install.sh codex           # All skills → Codex CLI
./install.sh gemini          # All skills → Gemini CLI
./install.sh all             # All three

./install.sh claude my-skill # Single skill
```

All agents are installed via symlink. Agent-specific frontmatter fields (e.g. Claude's `user-invocable`, `allowed-tools`) go directly in `SKILL.md` — each agent reads what it understands and ignores the rest.

## Uninstall

```bash
./uninstall.sh claude        # Remove all from Claude Code
./uninstall.sh all           # Remove from all agents
./uninstall.sh codex my-skill # Remove single skill
```

## Test

```bash
./test.sh   # Validates format, install, uninstall, idempotency
```

## Adding a Skill

1. Create `skills/<skill-name>/SKILL.md`:

```yaml
---
name: my-skill
description: >-
  What it does and when to trigger it.
# Claude-specific fields (optional, ignored by other agents):
user-invocable: true
argument-hint: "[args]"
allowed-tools:
  - Bash
---

# My Skill

Instructions for the agent...
```

2. (Optional) Add `agents/openai.yaml` for Codex UI metadata.

3. Run `./install.sh all my-skill`

## Format Rules

| Rule | Detail |
|------|--------|
| `name` | Lowercase + hyphens, max 64 chars, must match directory name |
| `description` | Max 1024 chars, include what + when to trigger |
| `SKILL.md` body | Under 500 lines; split large content into `references/` |
| Agent-specific fields | Put directly in `SKILL.md` frontmatter; other agents ignore them |
| Codex UI config | Goes in `agents/openai.yaml` |
| Body content | Keep agent-agnostic where possible |
