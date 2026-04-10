#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$SCRIPT_DIR/skills"

CLAUDE_SKILLS="$HOME/.claude/skills"
CODEX_SKILLS="$HOME/.codex/skills"
GEMINI_SKILLS="$HOME/.gemini/skills"

usage() {
  echo "Usage: $0 <claude|codex|gemini> <skill-name> [--force]"
  echo ""
  echo "Copy a skill from a local agent directory into this repository."
  echo ""
  echo "Options:"
  echo "  --force    Overwrite if skill already exists in ./skills/"
  echo ""
  echo "Examples:"
  echo "  $0 claude discord"
  echo "  $0 codex my-skill"
  echo "  $0 claude discord --force"
  exit 1
}

agent_label() {
  echo "$1" | awk '{print toupper(substr($0,1,1)) substr($0,2)}'
}

source_for_agent() {
  case "$1" in
    claude) echo "$CLAUDE_SKILLS" ;;
    codex)  echo "$CODEX_SKILLS" ;;
    gemini) echo "$GEMINI_SKILLS" ;;
  esac
}

# --- Parse arguments ---

force=false
args=()
for arg in "$@"; do
  if [[ "$arg" == "--force" ]]; then
    force=true
  else
    args+=("$arg")
  fi
done

[[ ${#args[@]} -ne 2 ]] && usage

agent="${args[0]}"
skill_name="${args[1]}"

case "$agent" in
  claude|codex|gemini) ;;
  *) usage ;;
esac

# --- Resolve source ---

source_base="$(source_for_agent "$agent")"
source_path="$source_base/$skill_name"

if [[ ! -e "$source_path" ]]; then
  echo "Error: Skill '$skill_name' not found in $source_base" >&2
  exit 1
fi

real_source="$(cd "$source_path" && pwd -P)"

echo "Porting '$skill_name' from $source_base into this repository..."
echo ""
echo "  Source: $source_path"
if [[ -L "$source_path" ]]; then
  echo "    -> $real_source"
fi

# Check if the skill already lives in this repo
if [[ "$real_source" == "$SKILLS_DIR"/* ]]; then
  echo ""
  echo "Warning: '$skill_name' already lives in this repository."
  echo "Nothing to port."
  exit 0
fi

# --- Check destination ---

dest_path="$SKILLS_DIR/$skill_name"
echo "  Destination: $dest_path"

if [[ -d "$dest_path" ]]; then
  if [[ "$force" == true ]]; then
    echo ""
    echo "Warning: Overwriting existing skill at $dest_path (--force)"
    rm -rf "$dest_path"
  else
    echo ""
    echo "Warning: Skill '$skill_name' already exists at $dest_path"
    read -rp "Overwrite? [y/N] " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
      rm -rf "$dest_path"
    else
      echo "Aborted."
      exit 0
    fi
  fi
fi

# --- Copy ---

echo ""
echo "Copying skill (excluding __pycache__, *.pyc, .DS_Store, .git)..."

rsync -a --copy-links \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  --exclude='.git/' \
  "$real_source/" "$dest_path/"

echo "  Done."

# --- Validate ---

echo ""
echo "Validating ported skill..."
echo ""
if "$SCRIPT_DIR/validate.sh" "$skill_name"; then
  echo ""
  echo "Skill '$skill_name' ported successfully to ./skills/$skill_name/"
else
  echo ""
  echo "Skill '$skill_name' was copied but has validation warnings."
  echo "You may want to fix the issues above before committing."
fi

# --- Next steps ---

echo ""
echo "Next steps:"
echo "  git add skills/$skill_name/"
echo "  git commit -m 'Add $skill_name skill'"
echo "  ./install.sh all $skill_name    # symlink it back for all agents"
