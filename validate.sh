#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$SCRIPT_DIR/skills"

skill_filter="${1:-}"

passed=0
failed=0

validate_yaml_frontmatter() {
  local yaml_file="$1"
  local err_file="$2"

  if command -v python3 >/dev/null 2>&1 && python3 - <<'PY' >/dev/null 2>&1
import importlib.util
import sys
sys.exit(0 if importlib.util.find_spec("yaml") else 1)
PY
  then
    python3 - "$yaml_file" > /dev/null 2>"$err_file" <<'PY'
import pathlib
import sys
import yaml

path = pathlib.Path(sys.argv[1])
try:
    data = yaml.safe_load(path.read_text())
except Exception as exc:
    print(exc, file=sys.stderr)
    raise SystemExit(1)

if not isinstance(data, dict):
    print("frontmatter must parse to a mapping", file=sys.stderr)
    raise SystemExit(1)
PY
    return $?
  fi

  if command -v ruby >/dev/null 2>&1; then
    ruby - "$yaml_file" > /dev/null 2>"$err_file" <<'RUBY'
require "yaml"

path = ARGV.fetch(0)

begin
  data = YAML.load_file(path)
  raise "frontmatter must parse to a mapping" unless data.is_a?(Hash)
rescue => e
  warn e.message
  exit 1
end
RUBY
    return $?
  fi

  echo "no YAML parser available (install PyYAML or Ruby)" >"$err_file"
  return 1
}

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
if [[ -n "$skill_filter" ]]; then
  if [[ ! -d "$SKILLS_DIR/$skill_filter" ]]; then
    echo "Error: Skill '$skill_filter' not found in $SKILLS_DIR" >&2
    exit 1
  fi
  skill_names+=("$skill_filter")
else
  for skill_dir in "$SKILLS_DIR"/*/; do
    [[ -d "$skill_dir" ]] || continue
    name="$(basename "$skill_dir")"
    skill_names+=("$name")
  done
fi

if [[ ${#skill_names[@]} -eq 0 ]]; then
  echo "No skill directories found in $SKILLS_DIR"
  exit 1
fi

echo "Validating ${#skill_names[@]} skill(s): ${skill_names[*]}"
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

  delimiter_count="$(awk '/^---$/{count++} END{print count+0}' "$skill_md")"
  if [[ "$delimiter_count" -lt 2 ]]; then
    fail "SKILL.md frontmatter is missing a closing --- delimiter"
    echo ""
    continue
  fi

  # Extract frontmatter (between first and second ---)
  frontmatter="$(awk '/^---$/{n++; next} n==1{print} n>=2{exit}' "$skill_md")"

  yaml_tmp="$(mktemp)"
  yaml_err="$(mktemp)"
  printf '%s\n' "$frontmatter" > "$yaml_tmp"

  if validate_yaml_frontmatter "$yaml_tmp" "$yaml_err"; then
    pass "frontmatter is valid YAML"
  else
    parse_error="$(tr '\n' ' ' < "$yaml_err" | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//')"
    fail "invalid YAML frontmatter: $parse_error"
    rm -f "$yaml_tmp" "$yaml_err"
    echo ""
    continue
  fi

  rm -f "$yaml_tmp" "$yaml_err"

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
