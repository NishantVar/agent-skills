# reap-orphaned-browsers

Kills orphaned `agent-browser` Chrome instances — ephemeral headless browsers whose
owning daemon died without cleanup, leaving Chrome pinned at ~100% CPU (sometimes for
days). Portable across AI coding agents (Claude Code, Codex, …).

Files in this hook dir:

- `reap-orphaned-browsers.sh` — the portable core reaper.
- `codex-notify.sh` — a Codex `notify` dispatcher, for when the (single) notify slot
  is already in use and you want to keep it *and* run the reaper.

### Why it's safe

`agent-browser` spawns Chrome as a **direct child of its daemon** (plain spawn, no
`setsid`/detach). So the parent PID is a reliable liveness signal:

| State | Parent | Action |
|-------|--------|--------|
| In use (daemon alive) | the daemon (ppid ≠ 1) | **skipped** |
| Orphaned (daemon died) | init/launchd (ppid == 1) | **reaped** |

It only ever matches ephemeral profiles (`agent-browser-chrome-<uuid>` in the temp
dir) — never a named/persistent session. It ignores its args and always exits 0, so
it can't block or fail the host agent. Safe to run on every turn, or from cron.

This is a **backstop**. The first line of defense is `AGENT_BROWSER_IDLE_TIMEOUT_MS`,
which makes an orphaned daemon self-terminate after N ms idle. The reaper catches the
case where the daemon is hard-killed before that timer engages.

### Wiring

Paths below assume this repo lives at `~/git/agent-skills`.

**Claude Code** — add a `Stop` hook in `~/.claude/settings.json`:

```json
"hooks": {
  "Stop": [
    { "hooks": [ { "type": "command", "command": "bash ~/git/agent-skills/hooks/reap-orphaned-browsers/reap-orphaned-browsers.sh" } ] }
  ]
}
```

**Codex** — in `~/.codex/config.toml`:

- *No existing `notify`*: point it straight at the reaper (it ignores the event JSON arg):
  ```toml
  notify = ["/ABS/PATH/agent-skills/hooks/reap-orphaned-browsers/reap-orphaned-browsers.sh"]
  ```
- *Existing `notify`* (the slot is single-program): use the dispatcher, listing your
  original program + its static args after it — Codex appends the event JSON last:
  ```toml
  notify = [
    "/ABS/PATH/agent-skills/hooks/reap-orphaned-browsers/codex-notify.sh",
    "/ABS/PATH/to/original-notify-program",
    "turn-ended",
  ]
  ```

**Anything else / catch-all** — run it from cron or a launchd/systemd timer every few minutes.

### Manual use

```sh
hooks/reap-orphaned-browsers/reap-orphaned-browsers.sh          # reap now
AGENT_REAPER_LOG=/tmp/r.log hooks/reap-orphaned-browsers/reap-orphaned-browsers.sh
```

Reaps are logged to `$TMPDIR/agent-browser-reaper.log` (override with `AGENT_REAPER_LOG`).
