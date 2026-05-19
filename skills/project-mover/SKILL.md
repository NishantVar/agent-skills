---
name: project-mover
description: Move a project folder and update all path-dependent metadata for Claude Code, Codex CLI, and Gemini CLI. Use whenever the user wants to move, rename, or relocate a project directory — handles updating session history, trust registries, project mappings, and symlinks across all three tools automatically.
---

# Project Mover

Moves a project folder and fixes all path references in Claude Code, Codex CLI, and Gemini CLI.

## Usage

1. Ask the user for the **source path** (current location) and **destination path** (where to move it), if not already provided.

2. Run a dry run first to preview changes:
   ```
   python ~/.claude/skills/project-mover/scripts/move_project.py --source <src> --dest <dst> --dry-run
   ```

3. Show the user the summary of what will change and ask for confirmation.

4. Run the script for real (without `--dry-run`):
   ```
   python ~/.claude/skills/project-mover/scripts/move_project.py --source <src> --dest <dst>
   ```

5. Report the results to the user.

## Flags

- `--source PATH` — current project path (required)
- `--dest PATH` — target path (required)
- `--dry-run` — preview changes without modifying anything
- `--skip-move` — skip moving the folder, only fix path references (use when the user already moved the folder themselves)

## What it updates

- **Claude Code** (`~/.claude/`): project directories, session metadata, team configs
- **Codex CLI** (`~/.codex/`): config.toml project keys, skill symlinks
- **Gemini CLI** (`~/.gemini/`): projects.json, trustedFolders.json, history/tmp .project_root files, hashed tmp directories
