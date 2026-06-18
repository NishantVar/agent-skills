#!/usr/bin/env bash
#
# reap-orphaned-browsers.sh
#
# Reaps orphaned `agent-browser` Chrome instances — ephemeral browsers whose
# owning daemon died without cleaning up, leaving headless Chrome spinning at
# 100% CPU (sometimes for days).
#
# Why this is safe to run anytime / on every agent Stop:
#   agent-browser spawns Chrome as a DIRECT CHILD of its daemon (plain spawn,
#   no setsid/detach — verified in cli/src/native/cdp/chrome.rs). So:
#     * in-use browser  -> parent is the live daemon (ppid != 1)  -> SKIPPED
#     * orphaned browser -> daemon died, reparented to init (ppid == 1) -> REAPED
#   We only ever touch ephemeral profiles (agent-browser-chrome-<uuid> in the
#   temp dir), never a named/persistent session.
#
# Tool-agnostic: works as a Claude Code Stop hook, a Codex notify step, a cron
# job, or a manual command. Ignores its arguments and always exits 0 so it can
# never block or fail the host agent.

set -uo pipefail

PATTERN="agent-browser-chrome-"
LOG="${AGENT_REAPER_LOG:-${TMPDIR:-/tmp}/agent-browser-reaper.log}"

reaped=0

# pid / ppid / full command for every process referencing an ephemeral profile.
# Only the Chrome ROOT reparents to init when the daemon dies; its renderers
# keep the (still-alive) root as parent, so a single pkill on the unique
# profile dir tears down the whole tree.
while IFS= read -r line; do
  [ -n "$line" ] || continue
  read -r pid ppid _ <<<"$line"
  [ "${ppid:-0}" = "1" ] || continue

  udd=$(printf '%s\n' "$line" | grep -oE "${PATTERN}[A-Za-z0-9._-]+" | head -1)
  [ -n "$udd" ] || continue

  if pkill -9 -f "$udd" 2>/dev/null; then
    reaped=$((reaped + 1))
  fi
done < <(ps -axo pid=,ppid=,command= 2>/dev/null | grep "$PATTERN" | grep -v grep)

if [ "$reaped" -gt 0 ]; then
  printf '%s reaped %d orphaned agent-browser chrome instance(s)\n' \
    "$(date '+%Y-%m-%dT%H:%M:%S')" "$reaped" >>"$LOG" 2>/dev/null || true
fi

exit 0
