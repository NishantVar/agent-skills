#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$SCRIPT_DIR/skills"

CLAUDE_SKILLS="$HOME/.claude/skills"
CODEX_SKILLS="$HOME/.codex/skills"
GEMINI_SKILLS="$HOME/.gemini/skills"

passed=0
failed=0

pass() {
  echo "  PASS: $1"
  passed=$((passed + 1))
}

fail() {
  echo "  FAIL: $1"
  failed=$((failed + 1))
}

check() {
  local description="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    pass "$description"
  else
    fail "$description"
  fi
}

# --- Discover skills ---

skill_names=()
for skill_dir in "$SKILLS_DIR"/*/; do
  [[ -d "$skill_dir" ]] || continue
  name="$(basename "$skill_dir")"
  [[ -f "$skill_dir/SKILL.md" ]] || continue
  skill_names+=("$name")
done

if [[ ${#skill_names[@]} -eq 0 ]]; then
  echo "No skills found in $SKILLS_DIR"
  exit 1
fi

echo "Found ${#skill_names[@]} skill(s): ${skill_names[*]}"
echo ""

# --- Test 1: Skill format validation ---

echo "== Skill format validation =="

for name in "${skill_names[@]}"; do
  skill_md="$SKILLS_DIR/$name/SKILL.md"

  # Directory name matches 'name' field in frontmatter
  fm_name="$(awk '/^---$/{n++; next} n==1 && /^name:/{print $2; exit}' "$skill_md")"
  if [[ "$fm_name" == "$name" ]]; then
    pass "$name: directory name matches frontmatter name"
  else
    fail "$name: directory name '$name' != frontmatter name '$fm_name'"
  fi

  # Has description field
  check "$name: has description field" grep -q '^description:' "$skill_md"

  # Name is lowercase+hyphens only
  if [[ "$name" =~ ^[a-z][a-z0-9-]*$ ]]; then
    pass "$name: name format valid (lowercase+hyphens)"
  else
    fail "$name: name format invalid (must be lowercase+hyphens)"
  fi

  # Body under 500 lines
  total_lines="$(wc -l < "$skill_md")"
  if [[ "$total_lines" -le 500 ]]; then
    pass "$name: SKILL.md under 500 lines ($total_lines)"
  else
    fail "$name: SKILL.md too long ($total_lines lines, max 500)"
  fi
done

echo ""

# --- Test 2: Install for each agent ---

echo "== Install tests =="

for agent in claude codex gemini; do
  case "$agent" in
    claude) dest_base="$CLAUDE_SKILLS" ;;
    codex)  dest_base="$CODEX_SKILLS" ;;
    gemini) dest_base="$GEMINI_SKILLS" ;;
  esac

  "$SCRIPT_DIR/install.sh" "$agent" >/dev/null 2>&1

  for name in "${skill_names[@]}"; do
    dest="$dest_base/$name"

    # Symlink exists
    if [[ -L "$dest" ]]; then
      pass "$agent/$name: symlink exists"
    else
      fail "$agent/$name: symlink missing at $dest"
      continue
    fi

    # Symlink target is correct
    target="$(readlink "$dest")"
    expected="$SKILLS_DIR/$name"
    if [[ "$target" == "$expected" ]]; then
      pass "$agent/$name: symlink target correct"
    else
      fail "$agent/$name: symlink target '$target' != expected '$expected'"
    fi

    # SKILL.md accessible through symlink
    check "$agent/$name: SKILL.md readable" test -f "$dest/SKILL.md"
  done
done

echo ""

# --- Test 3: Idempotent re-install ---

echo "== Idempotent re-install =="

"$SCRIPT_DIR/install.sh" all >/dev/null 2>&1
for agent in claude codex gemini; do
  case "$agent" in
    claude) dest_base="$CLAUDE_SKILLS" ;;
    codex)  dest_base="$CODEX_SKILLS" ;;
    gemini) dest_base="$GEMINI_SKILLS" ;;
  esac

  for name in "${skill_names[@]}"; do
    check "$agent/$name: still valid after re-install" test -L "$dest_base/$name"
  done
done

echo ""

# --- Test 4: Single skill install ---

echo "== Single skill install =="

first_skill="${skill_names[0]}"
"$SCRIPT_DIR/uninstall.sh" all >/dev/null 2>&1
"$SCRIPT_DIR/install.sh" claude "$first_skill" >/dev/null 2>&1
check "single skill: $first_skill installed for claude" test -L "$CLAUDE_SKILLS/$first_skill"

echo ""

# --- Test 5: Uninstall ---

echo "== Uninstall tests =="

# First install everything
"$SCRIPT_DIR/install.sh" all >/dev/null 2>&1

# Uninstall everything
"$SCRIPT_DIR/uninstall.sh" all >/dev/null 2>&1

for agent in claude codex gemini; do
  case "$agent" in
    claude) dest_base="$CLAUDE_SKILLS" ;;
    codex)  dest_base="$CODEX_SKILLS" ;;
    gemini) dest_base="$GEMINI_SKILLS" ;;
  esac

  for name in "${skill_names[@]}"; do
    dest="$dest_base/$name"
    if [[ ! -e "$dest" && ! -L "$dest" ]]; then
      pass "$agent/$name: cleaned up after uninstall"
    else
      fail "$agent/$name: still exists after uninstall"
    fi
  done
done

echo ""

# --- Test 6: Uninstall is safe when not installed ---

echo "== Uninstall when not installed =="

"$SCRIPT_DIR/uninstall.sh" all >/dev/null 2>&1
check "double uninstall doesn't error" "$SCRIPT_DIR/uninstall.sh" all

echo ""

# --- Summary ---

echo "================================"
echo "Results: $passed passed, $failed failed"
echo "================================"

[[ "$failed" -eq 0 ]]
