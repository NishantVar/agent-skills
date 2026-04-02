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

# Merge claude.yaml fields into SKILL.md frontmatter.
# Reads SKILL.md, extracts frontmatter, appends claude.yaml fields,
# writes combined file to destination.
merge_claude_skill() {
  local skill_dir="$1"
  local dest_dir="$2"
  local skill_md="$skill_dir/SKILL.md"
  local claude_yaml="$skill_dir/claude.yaml"

  mkdir -p "$dest_dir"

  if [[ ! -f "$claude_yaml" ]]; then
    # No Claude overrides — copy SKILL.md as-is
    cp "$skill_md" "$dest_dir/SKILL.md"
  else
    # Extract frontmatter and body from SKILL.md
    local in_frontmatter=false
    local frontmatter_done=false
    local frontmatter=""
    local body=""

    while IFS= read -r line || [[ -n "$line" ]]; do
      if [[ "$frontmatter_done" == true ]]; then
        body+="$line"$'\n'
      elif [[ "$in_frontmatter" == false && "$line" == "---" ]]; then
        in_frontmatter=true
      elif [[ "$in_frontmatter" == true && "$line" == "---" ]]; then
        frontmatter_done=true
      elif [[ "$in_frontmatter" == true ]]; then
        frontmatter+="$line"$'\n'
      fi
    done < "$skill_md"

    # Extract non-comment, non-empty lines from claude.yaml
    local claude_fields=""
    while IFS= read -r line || [[ -n "$line" ]]; do
      # Skip comments and empty lines
      [[ "$line" =~ ^[[:space:]]*# ]] && continue
      [[ -z "${line// /}" ]] && continue
      claude_fields+="$line"$'\n'
    done < "$claude_yaml"

    # Write merged SKILL.md
    {
      echo "---"
      printf '%s' "$frontmatter"
      printf '%s' "$claude_fields"
      echo "---"
      printf '%s' "$body"
    } > "$dest_dir/SKILL.md"
  fi

  # Copy supporting directories if they exist
  for subdir in references scripts assets; do
    if [[ -d "$skill_dir/$subdir" ]]; then
      cp -r "$skill_dir/$subdir" "$dest_dir/"
    fi
  done
}

install_claude() {
  local skill_name="$1"
  local skill_dir="$SKILLS_DIR/$skill_name"
  local dest_dir="$CLAUDE_SKILLS/$skill_name"

  if [[ -d "$dest_dir" ]]; then
    rm -rf "$dest_dir"
  fi

  merge_claude_skill "$skill_dir" "$dest_dir"
  echo "  Installed $skill_name for Claude Code (copied to $dest_dir)"
}

install_symlink() {
  local agent="$1"
  local skill_name="$2"
  local skill_dir="$SKILLS_DIR/$skill_name"
  local dest_base

  case "$agent" in
    codex) dest_base="$CODEX_SKILLS" ;;
    gemini) dest_base="$GEMINI_SKILLS" ;;
  esac

  mkdir -p "$dest_base"
  local dest="$dest_base/$skill_name"

  if [[ -L "$dest" ]]; then
    rm "$dest"
  elif [[ -d "$dest" ]]; then
    rm -rf "$dest"
  fi

  ln -s "$skill_dir" "$dest"
  local agent_label
  agent_label="$(echo "$agent" | awk '{print toupper(substr($0,1,1)) substr($0,2)}')"
  echo "  Installed $skill_name for $agent_label (symlinked to $dest)"
}

install_skill() {
  local agent="$1"
  local skill_name="$2"

  case "$agent" in
    claude) install_claude "$skill_name" ;;
    codex)  install_symlink codex "$skill_name" ;;
    gemini) install_symlink gemini "$skill_name" ;;
  esac
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
