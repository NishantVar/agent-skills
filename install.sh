#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$SCRIPT_DIR/skills"

CLAUDE_SKILLS="$HOME/.claude/skills"
CODEX_SKILLS="$HOME/.codex/skills"
GEMINI_SKILLS="$HOME/.gemini/skills"

usage() {
  echo "Usage: $0 <claude|codex|gemini|all> [skill-name|skill-path] [--dir /path/to/skills] [--force]"
  echo ""
  echo "Install agent skills for the specified agent(s)."
  echo "Second positional arg:"
  echo "  - If it contains '/', it is treated as a direct path to a skill directory"
  echo "    (must contain SKILL.md); the skill name is derived from its basename."
  echo "  - Otherwise it is treated as a skill name looked up inside SKILLS_DIR."
  echo "If omitted, all skills in SKILLS_DIR are installed."
  echo ""
  echo "Options:"
  echo "  --dir <path>  Use an external skills directory (parent of skill subdirs) instead of the built-in one"
  echo "  --force       Overwrite existing non-symlinked skills without prompting"
  exit 1
}

# Parse flags from arguments
force=false
args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)
      if [[ -z "${2:-}" ]]; then
        echo "Error: --dir requires a path argument" >&2
        exit 1
      fi
      SKILLS_DIR="$(cd "$2" 2>/dev/null && pwd)" || {
        echo "Error: Directory '$2' does not exist" >&2
        exit 1
      }
      shift 2
      ;;
    --force)
      force=true
      shift
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done
set -- "${args[@]}"

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
  local skill_dir="${3:-$SKILLS_DIR/$skill_name}"
  local dest_base
  dest_base="$(dest_for_agent "$agent")"

  mkdir -p "$dest_base"
  local dest="$dest_base/$skill_name"

  # Remove existing install (symlink or directory)
  if [[ -L "$dest" ]]; then
    rm "$dest"
  elif [[ -d "$dest" ]]; then
    if [[ "$force" == true ]]; then
      echo "  Warning: Overwriting existing '$skill_name' for $(agent_label "$agent") (--force)"
      rm -rf "$dest"
    else
      echo "  Error: '$skill_name' already exists as a local directory for $(agent_label "$agent")" >&2
      echo "    $dest" >&2
      echo "    Use --force to overwrite, or remove it manually first." >&2
      return 1
    fi
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

# If the filter contains a '/', treat it as a direct skill path rather than a name lookup.
skill_path=""
if [[ "$skill_filter" == */* ]]; then
  skill_path="$(cd "$skill_filter" 2>/dev/null && pwd)" || {
    echo "Error: Directory '$skill_filter' does not exist" >&2
    exit 1
  }
  if [[ ! -f "$skill_path/SKILL.md" ]]; then
    echo "Error: '$skill_path' does not contain a SKILL.md" >&2
    exit 1
  fi
  skill_name="$(basename "$skill_path")"
fi

for agent in "${agents[@]}"; do
  echo "Installing for $agent..."
  if [[ -n "$skill_path" ]]; then
    install_skill "$agent" "$skill_name" "$skill_path"
  elif [[ -n "$skill_filter" ]]; then
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
