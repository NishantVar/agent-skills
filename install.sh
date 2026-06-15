#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$SCRIPT_DIR/skills"

# Agents expanded by the 'all' keyword. Any other name works too: it maps to
# ~/.<agent>/skills, so e.g. 'hermes' installs into ~/.hermes/skills.
DEFAULT_AGENTS=(claude codex gemini)

usage() {
  echo "Usage: $0 <agent|all> [skill-name|skill-path] [--dir /path/to/skills] [--force]"
  echo ""
  echo "Install agent skills for the specified agent(s)."
  echo "<agent> is any agent name; skills are installed into ~/.<agent>/skills."
  echo "  e.g. '$0 hermes my-skill' installs into ~/.hermes/skills."
  echo "  'all' expands to: ${DEFAULT_AGENTS[*]}"
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
  echo "$HOME/.$1/skills"
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
  all)
    agents=("${DEFAULT_AGENTS[@]}")
    ;;
  ""|*/*|.|..)
    echo "Error: invalid agent name '$target'" >&2
    usage
    ;;
  *)
    agents=("$target")
    ;;
esac

# Resolve skill_filter as a filesystem path first (absolute or relative to $PWD),
# regardless of whether it contains '/'. This allows invocations from any working
# directory. Falls back to SKILLS_DIR name lookup only when no local path matches.
skill_path=""
skill_name=""
if [[ -n "$skill_filter" ]]; then
  _resolved="$(cd "$skill_filter" 2>/dev/null && pwd)" || true
  if [[ -n "$_resolved" && -d "$_resolved" ]]; then
    if [[ ! -f "$_resolved/SKILL.md" ]]; then
      echo "Error: '$skill_filter' does not contain a SKILL.md" >&2
      exit 1
    fi
    skill_path="$_resolved"
    skill_name="$(basename "$skill_path")"
  fi
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
