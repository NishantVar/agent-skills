#!/usr/bin/env bash
#
# codex-notify.sh — Codex `notify` dispatcher.
#
# Codex allows exactly ONE notify program. If you already use that slot (e.g.
# for computer-use), this dispatcher lets you keep it AND run the orphaned-
# browser reaper on every Codex turn.
#
# Wiring in ~/.codex/config.toml — put the original program (and its static
# args) AFTER this script; Codex appends the event JSON as the final arg:
#
#   notify = [
#     "/ABS/PATH/agents/adapters/codex-notify.sh",   # this dispatcher
#     "/ABS/PATH/to/original-notify-program",         # forwarded downstream ($1)
#     "turn-ended",                                    # any static args it expects
#   ]
#
# Resulting exec is byte-identical to calling the original program directly.
# If you have NO existing notify program, don't use this — point notify at
# reap-orphaned-browsers.sh directly instead.

REAPER="$(cd "$(dirname "$0")" && pwd)/reap-orphaned-browsers.sh"

# Fire-and-forget so we never delay or block Codex.
"$REAPER" >/dev/null 2>&1 &

# Forward everything to the original downstream program, unchanged.
[ "$#" -ge 1 ] || exit 0
prog="$1"
shift
exec "$prog" "$@"
