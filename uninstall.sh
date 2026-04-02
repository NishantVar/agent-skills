#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$SCRIPT_DIR/skills"

CLAUDE_SKILLS="$HOME/.claude/skills"
CODEX_SKILLS="$HOME/.codex/skills"
GEMINI_SKILLS="$HOME/.gemini/skills"

usage() {
  echo "Usage: $0 <claude|codex|gemini|all> [skill-name]"
  echo ""
  echo "Uninstall agent skills for the specified agent(s)."
  echo "If skill-name is provided, only that skill is removed."
  echo "Otherwise, all skills from this repo are removed."
  exit 1
}

uninstall_claude() {
  local skill_name="$1"
  local dest="$CLAUDE_SKILLS/$skill_name"

  if [[ -d "$dest" ]]; then
    rm -rf "$dest"
    echo "  Removed $skill_name from Claude Code ($dest)"
  else
    echo "  $skill_name not installed for Claude Code (skipped)"
  fi
}

uninstall_symlink() {
  local agent="$1"
  local skill_name="$2"
  local dest_base

  case "$agent" in
    codex) dest_base="$CODEX_SKILLS" ;;
    gemini) dest_base="$GEMINI_SKILLS" ;;
  esac

  local dest="$dest_base/$skill_name"
  local agent_label
  agent_label="$(echo "$agent" | awk '{print toupper(substr($0,1,1)) substr($0,2)}')"

  if [[ -L "$dest" ]]; then
    rm "$dest"
    echo "  Removed $skill_name from $agent_label ($dest)"
  elif [[ -d "$dest" ]]; then
    rm -rf "$dest"
    echo "  Removed $skill_name from $agent_label ($dest)"
  else
    echo "  $skill_name not installed for $agent_label (skipped)"
  fi
}

uninstall_skill() {
  local agent="$1"
  local skill_name="$2"

  case "$agent" in
    claude) uninstall_claude "$skill_name" ;;
    codex)  uninstall_symlink codex "$skill_name" ;;
    gemini) uninstall_symlink gemini "$skill_name" ;;
  esac
}

uninstall_all_skills() {
  local agent="$1"
  for skill_dir in "$SKILLS_DIR"/*/; do
    [[ -d "$skill_dir" ]] || continue
    local skill_name
    skill_name="$(basename "$skill_dir")"
    [[ -f "$skill_dir/SKILL.md" ]] || continue
    uninstall_skill "$agent" "$skill_name"
  done
}

# --- Main ---

[[ $# -lt 1 ]] && usage

target="$1"
skill_filter="${2:-}"

agents=()
case "$target" in
  claude) agents=(claude) ;;
  codex)  agents=(codex) ;;
  gemini) agents=(gemini) ;;
  all)    agents=(claude codex gemini) ;;
  *)      usage ;;
esac

for agent in "${agents[@]}"; do
  echo "Uninstalling for $agent..."
  if [[ -n "$skill_filter" ]]; then
    uninstall_skill "$agent" "$skill_filter"
  else
    uninstall_all_skills "$agent"
  fi
done

echo "Done."
