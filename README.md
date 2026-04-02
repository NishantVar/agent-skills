# agent-skills

Write a skill once, use it in Claude Code, Codex CLI, and Gemini CLI.

All three agents use the same core format: `SKILL.md` with `name` + `description` YAML frontmatter ([Agent Skills open standard](https://agentskills.io/specification)). This repo exploits that shared format so you only write the skill body once.

## Repo Structure

```
agent-skills/
├── install.sh
├── uninstall.sh
├── README.md
└── skills/
    └── <skill-name>/
        ├── SKILL.md            # Universal — name + description frontmatter only
        ├── claude.yaml         # Claude-specific frontmatter overrides (optional)
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

**How it works:**
- **Claude Code**: Merges `claude.yaml` fields into `SKILL.md` frontmatter, copies to `~/.claude/skills/`
- **Codex CLI / Gemini CLI**: Symlinks the skill directory to `~/.codex/skills/` or `~/.gemini/skills/`

## Uninstall

```bash
./uninstall.sh claude        # Remove all from Claude Code
./uninstall.sh all           # Remove from all agents
./uninstall.sh codex my-skill # Remove single skill
```

## Adding a Skill

1. Create `skills/<skill-name>/SKILL.md`:

```yaml
---
name: my-skill
description: >-
  What it does and when to trigger it.
---

# My Skill

Instructions for the agent...
```

2. (Optional) Add `claude.yaml` for Claude-specific fields:

```yaml
user-invocable: true
argument-hint: "[args]"
allowed-tools:
  - Bash
```

3. (Optional) Add `agents/openai.yaml` for Codex UI metadata.

4. Run `./install.sh all my-skill`

## Format Rules

| Rule | Detail |
|------|--------|
| `name` | Lowercase + hyphens, max 64 chars, must match directory name |
| `description` | Max 1024 chars, include what + when to trigger |
| `SKILL.md` body | Under 500 lines; split large content into `references/` |
| Claude fields | Go in `claude.yaml`, never in `SKILL.md` frontmatter |
| Codex UI config | Goes in `agents/openai.yaml` |
| Body content | Keep agent-agnostic where possible |
