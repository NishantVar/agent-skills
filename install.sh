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
  echo "Install agent skills for the specified agent(s)."
  echo "If skill-name is provided, only that skill is installed."
  echo "Otherwise, all skills are installed."
  exit 1
}

agent_label() {
  echo "$1" | awk '{print toupper(substr($0,1,1)) substr($0,2)}'
}

dest_for_agent() {
  case "$1" in
    claude) echo "$CLAUDE_SKILLS" ;;
    codex)  echo "$CODEX_SKILLS" ;;
    gemini) echo "$GEMINI_SKILLS" ;;
  esac
}

install_skill() {
  local agent="$1"
  local skill_name="$2"
  local skill_dir="$SKILLS_DIR/$skill_name"
  local dest_base
  dest_base="$(dest_for_agent "$agent")"

  mkdir -p "$dest_base"
  local dest="$dest_base/$skill_name"

  # Remove existing install (symlink or directory)
  if [[ -L "$dest" ]]; then
    rm "$dest"
  elif [[ -d "$dest" ]]; then
    rm -rf "$dest"
  fi

  ln -s "$skill_dir" "$dest"
  echo "  Installed $skill_name for $(agent_label "$agent") (symlinked)"
}

install_all_skills() {
  local agent="$1"
  for skill_dir in "$SKILLS_DIR"/*/; do
    [[ -d "$skill_dir" ]] || continue
    local skill_name
    skill_name="$(basename "$skill_dir")"
    [[ -f "$skill_dir/SKILL.md" ]] || continue
    install_skill "$agent" "$skill_name"
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
  echo "Installing for $agent..."
  if [[ -n "$skill_filter" ]]; then
    if [[ ! -d "$SKILLS_DIR/$skill_filter" ]]; then
      echo "Error: Skill '$skill_filter' not found in $SKILLS_DIR" >&2
      exit 1
    fi
    install_skill "$agent" "$skill_filter"
  else
    install_all_skills "$agent"
  fi
done

echo "Done."
