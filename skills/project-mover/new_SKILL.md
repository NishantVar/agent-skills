---
name: project_mover
description: Move a project folder and update all path-dependent metadata for Claude Code, Codex CLI, and Gemini CLI.
---

## Parameters

- **source_path**: Current project path. Required.
- **dest_path**: Target path. Required.
- **dry_run**: Preview changes without modifying anything. Default: false.
- **skip_move**: Skip moving the folder, only fix path references (use when the user already moved the folder themselves). Default: false.

## Instructions

### Context

- **what-it-updates**

  Updates path references across:
  - Claude Code (~/.claude/): project directories, session metadata, team configs
  - Codex CLI (~/.codex/): config.toml project keys, skill symlinks
  - Gemini CLI (~/.gemini/): projects.json, trustedFolders.json, history/tmp .project_root files, hashed tmp directories

### Steps

1. Decide whether source or dest not yet provided applies and, if so:
   a. Ask the user for the source path (current location) and destination path (where to move it).
2. Run: python ~/.claude/skills/project-mover/scripts/move_project.py --source {source_path} --dest {dest_path} --dry-run
3. Show the user the dry-run summary of what will change and ask for confirmation.
4. Decide whether user confirmed applies and, if so:
   a. Follow the run-move procedure.
5. Report the results to the user.

### Procedure: run-move

1. If skip_move:
   a. Run: python ~/.claude/skills/project-mover/scripts/move_project.py --source {source_path} --dest {dest_path} --skip-move
   Otherwise:
   a. Run: python ~/.claude/skills/project-mover/scripts/move_project.py --source {source_path} --dest {dest_path}

