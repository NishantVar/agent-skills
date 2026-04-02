#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$SCRIPT_DIR/skills"

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

# --- Discover skills ---

skill_names=()
for skill_dir in "$SKILLS_DIR"/*/; do
  [[ -d "$skill_dir" ]] || continue
  name="$(basename "$skill_dir")"
  skill_names+=("$name")
done

if [[ ${#skill_names[@]} -eq 0 ]]; then
  echo "No skill directories found in $SKILLS_DIR"
  exit 1
fi

echo "Found ${#skill_names[@]} skill(s): ${skill_names[*]}"
echo ""

for name in "${skill_names[@]}"; do
  echo "== $name =="
  skill_dir="$SKILLS_DIR/$name"
  skill_md="$skill_dir/SKILL.md"

  # Must have SKILL.md
  if [[ ! -f "$skill_md" ]]; then
    fail "missing SKILL.md"
    echo ""
    continue
  else
    pass "SKILL.md exists"
  fi

  # Name format: lowercase + hyphens, max 64 chars
  if [[ ! "$name" =~ ^[a-z][a-z0-9-]*$ ]]; then
    fail "directory name must be lowercase letters, digits, and hyphens"
  elif [[ ${#name} -gt 64 ]]; then
    fail "directory name exceeds 64 characters (${#name})"
  else
    pass "directory name format valid"
  fi

  # Has YAML frontmatter delimiters
  first_line="$(head -1 "$skill_md")"
  if [[ "$first_line" != "---" ]]; then
    fail "SKILL.md must start with --- (YAML frontmatter)"
    echo ""
    continue
  fi

  # Extract frontmatter (between first and second ---)
  frontmatter="$(awk '/^---$/{n++; next} n==1{print} n>=2{exit}' "$skill_md")"

  # Has name field
  fm_name="$(echo "$frontmatter" | awk '/^name:/{print $2; exit}')"
  if [[ -z "$fm_name" ]]; then
    fail "frontmatter missing 'name' field"
  elif [[ "$fm_name" != "$name" ]]; then
    fail "frontmatter name '$fm_name' does not match directory name '$name'"
  else
    pass "frontmatter name matches directory"
  fi

  # Has description field
  if echo "$frontmatter" | grep -q '^description:'; then
    # Check length (extract full description including multi-line >- values)
    desc="$(awk '
      /^---$/{n++; next}
      n>=2{exit}
      n==1 && /^description:/{found=1; sub(/^description:[[:space:]]*>-?[[:space:]]*/, ""); if($0) buf=$0; next}
      found && /^[[:space:]]/{gsub(/^[[:space:]]+/, ""); buf=buf " " $0; next}
      found{exit}
      END{print buf}
    ' "$skill_md")"
    desc_len=${#desc}
    if [[ $desc_len -gt 1024 ]]; then
      fail "description exceeds 1024 characters ($desc_len)"
    else
      pass "has description ($desc_len chars)"
    fi
  else
    fail "frontmatter missing 'description' field"
  fi

  # Body length under 500 lines
  total_lines="$(wc -l < "$skill_md" | tr -d ' ')"
  if [[ "$total_lines" -le 500 ]]; then
    pass "SKILL.md is $total_lines lines (max 500)"
  else
    fail "SKILL.md is $total_lines lines (max 500)"
  fi

  echo ""
done

# --- Summary ---

echo "================================"
echo "Results: $passed passed, $failed failed"
echo "================================"

[[ "$failed" -eq 0 ]]
