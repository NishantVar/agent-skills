#!/usr/bin/env bash
# proof_codex_readonly.sh — the read-only ENFORCEMENT proof.
#
# Deliberately run (it shells out to the real codex CLI), not part of the unit
# suite. It proves two things end-to-end:
#
#   1. afork resolves a codex agent declaring sandbox_mode="read-only" and
#      builds a launch command that carries the enforced --sandbox flag.
#   2. That same read-only mode, run through codex's own seatbelt, BLOCKS a
#      filesystem write — deterministically, with no LLM call.
#
# Contrast case: workspace-write ALLOWS the write, so the block in (2) is the
# sandbox doing its job, not codex being broken.
#
# Requires: python3, the codex CLI on PATH (`codex sandbox` available).
set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok()   { echo "  PASS: $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL: $1"; fail=$((fail+1)); }

if ! command -v codex >/dev/null 2>&1; then
  echo "SKIP: codex CLI not on PATH"; exit 0
fi

# --- Fixture: a read-only codex agent port under a target cwd ---
mkdir -p "$TMP/.codex/agents"
cat > "$TMP/.codex/agents/probe.toml" <<'TOML'
name = "probe"
sandbox_mode = "read-only"
developer_instructions = """
You are a read-only probe agent.
## Boundaries
- You do not write files.
"""
TOML

echo "== 1. afork builds an enforced read-only launch command =="
OUT="$(python3 "$SKILL_DIR/afork.py" codex probe --cwd "$TMP" --title probe_agent)"
echo "$OUT" | python3 -c '
import json,sys
o=json.load(sys.stdin)
assert o["ok"] is True, o
assert o["posture"]=="read-only", o
assert o["enforced"] is True, o
assert o["handoff_skill"]=="tfork", o
' && ok "afork returns ready_to_fork with enforced read-only" \
  || bad "afork did not return an enforced ready_to_fork"

LAUNCHER="$(echo "$OUT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["workdir"])')/launch.sh"
grep -q -- "--sandbox read-only" "$LAUNCHER" \
  && ok "generated launcher carries --sandbox read-only" \
  || bad "launcher missing --sandbox read-only"

echo "== 2. the read-only seatbelt BLOCKS a write (deterministic, no LLM) =="
RO_TARGET="$TMP/should_not_be_created"
rm -f "$RO_TARGET"
codex sandbox -c sandbox_mode='"read-only"' -- touch "$RO_TARGET" >/dev/null 2>&1
[ ! -f "$RO_TARGET" ] \
  && ok "write under read-only was blocked" \
  || bad "LEAK: read-only allowed a write to $RO_TARGET"

echo "== 3. workspace-write ALLOWS a write INSIDE the workspace =="
WW_TARGET="$TMP/allowed_under_workspace_write"
rm -f "$WW_TARGET"
( cd "$TMP" && codex sandbox -c sandbox_mode='"workspace-write"' -- touch "$WW_TARGET" >/dev/null 2>&1 )
[ -f "$WW_TARGET" ] \
  && ok "write under workspace-write was allowed (sandbox is selective)" \
  || bad "workspace-write unexpectedly blocked a write under cwd"

echo "== 4. workspace-write BLOCKS a write OUTSIDE the workspace =="
# afork marks workspace-write 'enforced', so prove the restrictive half too:
# a write outside the workspace (and outside any temp root) must be blocked.
# $HOME is outside the workspace and is not a workspace-write writable root.
WW_OUTSIDE="$HOME/.afork_ww_should_be_blocked_$$_${RANDOM}"
rm -f "$WW_OUTSIDE"
if ! ( touch "$WW_OUTSIDE" 2>/dev/null && rm -f "$WW_OUTSIDE" ); then
  # Preflight: without a writable target, a 'blocked' result is meaningless
  # (we couldn't attribute the block to the sandbox vs. plain unwritability).
  echo "  SKIP: \$HOME not writable here; cannot attribute a block to the sandbox"
else
  ( cd "$TMP" && codex sandbox -c sandbox_mode='"workspace-write"' -- touch "$WW_OUTSIDE" >/dev/null 2>&1 )
  if [ ! -f "$WW_OUTSIDE" ]; then
    ok "write OUTSIDE the workspace was blocked under workspace-write"
  else
    bad "LEAK: workspace-write allowed an outside-workspace write to $WW_OUTSIDE"
    rm -f "$WW_OUTSIDE"
  fi
fi

echo
echo "RESULT: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
