#!/usr/bin/env bash
# UserPromptSubmit hook: inject context-degradation warning on tier transitions.
# Tiers: 0 (<25%), 25 (25–49%), 50 (50%+).
# Only injects when crossing UP into a new tier; resets when ctx drops.
# Silent no-op on any failure or when no transition occurred.
# Supports Claude Code ("ctx:N%") and Codex ("Context N% left") status lines.

command -v cmux >/dev/null 2>&1 || exit 0

identify=$(cmux identify --json 2>/dev/null) || exit 0
surface=$(printf '%s' "$identify" \
  | grep -m1 '"surface_ref"' \
  | sed 's/.*"surface_ref"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
[ -n "$surface" ] || exit 0

screen=$(cmux read-screen --surface "$surface" --lines 50 2>/dev/null) || exit 0

n=$(printf '%s' "$screen" | grep -o 'ctx:[0-9]*%' | head -1 | grep -o '[0-9]*')

if [ -z "$n" ]; then
  left=$(printf '%s' "$screen" | grep -oE 'Context [0-9]+% left' | head -1 | grep -o '[0-9]*')
  [ -n "$left" ] || exit 0
  n=$((100 - left))
fi

if [ "$n" -ge 50 ]; then
  tier=50
elif [ "$n" -ge 25 ]; then
  tier=25
else
  tier=0
fi

state_file="/tmp/inject-ctx-tier-$(printf '%s' "$surface" | tr ':' '-')"
prev_tier=$(cat "$state_file" 2>/dev/null || echo 0)

if [ "$tier" -le "$prev_tier" ]; then
  printf '%s' "$tier" > "$state_file"
  exit 0
fi

printf '%s' "$tier" > "$state_file"

if [ "$tier" -eq 50 ]; then
  msg="[system suggestion, not user-issued] ctx:${n}% - past 50%, instruction adherence and reasoning degrade. Make sure any work done from here on gets reviewed and verified."
else
  msg="[system suggestion, not user-issued] ctx:${n}% - session is trending long. If upcoming work has parts that can be handed off (research, multi-step exploration, parallel checks), consider spawning a sub-agent now before context tightens."
fi

printf '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"%s"}}\n' "$msg"
