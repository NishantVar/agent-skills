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
  echo ""
  echo "MCP server registration (not a skill):"
  echo "  $0 mcp [claude|codex|all]   Register the flux-mcp server (default all)"
  echo "  NOTE: 'mcp' is a reserved first positional for this subcommand, so it"
  echo "  cannot also name a skill-install agent. It takes no skill-install flags"
  echo "  (--dir/--force); any args after the host selector are ignored."
  exit 1
}

agent_label() {
  echo "$1" | awk '{print toupper(substr($0,1,1)) substr($0,2)}'
}

dest_for_agent() {
  echo "$HOME/.$1/skills"
}

# --- MCP server registration (additive; separate from skill install) ---
#
# flux-mcp is an MCP server, not a Skill-tool skill. It is NOT symlinked into
# ~/.<agent>/skills; instead it is registered with each host's MCP config.
# Defined (and dispatched) before skill-install flag parsing so the `mcp`
# subcommand never touches --dir/--force validation.

FLUX_MCP_PY="$SCRIPT_DIR/mcp/flux/flux_mcp.py"

toml_escape() {
  # Escape backslashes then double-quotes for a TOML basic string, so a repo
  # path containing " or \ still produces valid TOML.
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  printf '%s' "$s"
}

prune_flux_mcp_skill_symlink() {
  # flux-mcp is no longer a skill; remove a stale symlink if a prior install left one.
  local agent="$1" link
  link="$(dest_for_agent "$agent")/flux-mcp"
  if [[ -L "$link" ]]; then
    rm "$link" && echo "  Removed stale flux-mcp skill symlink for $(agent_label "$agent")"
  fi
}

register_mcp_claude() {
  if ! command -v claude >/dev/null 2>&1; then
    echo "  Skipping claude: 'claude' CLI not found on PATH" >&2
    return 0
  fi
  claude mcp remove flux -s user >/dev/null 2>&1 || true
  claude mcp add flux -s user -- python3 "$FLUX_MCP_PY" --scope orchestrator
  echo "  Registered flux MCP server for Claude (user scope, orchestrator)"
}

register_mcp_codex() {
  local cfg="$HOME/.codex/config.toml"
  mkdir -p "$HOME/.codex"
  touch "$cfg"
  local esc
  esc="$(toml_escape "$FLUX_MCP_PY")"
  # Strip any prior managed block, then append a fresh one (idempotent).
  local tmp
  tmp="$(mktemp)"
  awk '
    /^# >>> flux-mcp/ {skip=1}
    skip!=1 {print}
    /^# <<< flux-mcp/ {skip=0}
  ' "$cfg" > "$tmp"
  {
    printf '\n# >>> flux-mcp (managed by agent-skills install.sh) >>>\n'
    printf '[mcp_servers.flux_comms]\ncommand = "python3"\nargs = ["%s", "--scope", "comms"]\n\n' "$esc"
    printf '[mcp_servers.flux_orchestrator]\ncommand = "python3"\nargs = ["%s", "--scope", "orchestrator"]\n' "$esc"
    printf '# <<< flux-mcp <<<\n'
  } >> "$tmp"
  mv "$tmp" "$cfg"
  echo "  Wrote codex [mcp_servers.flux_comms]/[mcp_servers.flux_orchestrator] to $cfg"
}

register_mcp() {
  local agent="$1"
  echo "Registering flux MCP server for $agent..."
  case "$agent" in
    claude) register_mcp_claude ;;
    codex)  register_mcp_codex ;;
    *) echo "  No MCP registration defined for '$agent' (only claude, codex)" >&2 ;;
  esac
}

run_mcp_subcommand() {
  # $1 is the host selector (claude|codex|all, default all).
  local host="${1:-all}"
  local mcp_agents
  case "$host" in
    ""|all) mcp_agents=(claude codex) ;;
    claude) mcp_agents=(claude) ;;
    codex)  mcp_agents=(codex) ;;
    *) echo "Error: 'mcp' target accepts: claude | codex | all" >&2; exit 1 ;;
  esac
  # flux-mcp is no longer a skill on ANY host — prune stale symlinks for every
  # known agent (not just the hosts being registered) so e.g. a leftover
  # ~/.gemini/skills/flux-mcp is cleaned up too.
  local a
  for a in "${DEFAULT_AGENTS[@]}"; do prune_flux_mcp_skill_symlink "$a"; done
  local agent
  for agent in "${mcp_agents[@]}"; do register_mcp "$agent"; done
  echo "Done."
}

# Dispatch the `mcp` subcommand before any skill-install flag parsing so it is
# fully isolated from the skill grammar (--dir/--force, agent-name resolution).
if [[ "${1:-}" == "mcp" ]]; then
  run_mcp_subcommand "${2:-}"
  exit 0
fi

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
