# agent-skills

Write a skill once, use it in Claude Code, Codex CLI, and Gemini CLI.

All three agents use the same core format: `SKILL.md` with `name` + `description` YAML frontmatter ([Agent Skills open standard](https://agentskills.io/specification)). Each agent reads what it understands and ignores the rest.

## Skills

| Skill | Description |
|-------|-------------|
| `ateam` | **(Experimental)** Multi-LLM agent team management — spawn Claude, Codex, and Gemini teammates and coordinate them via a hybrid native + sentinel-based protocol. |
| `athena` | Research companion based on Andrej Karpathy's LLM wiki approach, organized into four tiers: unconfirmed → confirmed → consolidated → design (the one you actually use). |
| `find-session` | Search and resume previous sessions by keyword (Claude Code only) |
| `first-principles` | Decompose any idea, problem, or decision down to its fundamental truths through collaborative iterative questioning |
| `fork-terminal` | Fork a new terminal pane running an agentic coding tool with a plan or summary |
| `judgy` | Opinionated code reviewer that spawns a second agent to critique your staged changes |
| `prompt-builder` | Interactive prompt crafting with iterative refinement and versioned saves |

## Install / Uninstall

```bash
./install.sh all             # All skills → all agents
./install.sh claude my-skill # Single skill, single agent
./uninstall.sh all           # Remove everything
```

## Validate

```bash
./validate.sh   # Checks all skills follow the format rules
```

## Adding a Skill

1. Create `skills/<skill-name>/SKILL.md`:

```yaml
---
name: my-skill
description: >-
  What it does and when to trigger it.
# Claude-specific (optional, ignored by other agents):
user-invocable: true
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
| Agent-specific fields | Go directly in `SKILL.md` frontmatter |
| Codex UI config | Goes in `agents/openai.yaml` |
