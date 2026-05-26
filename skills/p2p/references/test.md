# Surface-resolution test

If you change `my_surface()`, `_ancestor_ttys()`, or `_surface_from_tty_walk()` in `p2plib/surface.py` (the production module — `tools/agent_msg.py` is the legacy monolith retained only until cutover), **re-run this test from inside every agent runtime you care about** (Claude Code, Codex, Gemini, …). The bug it guards against — silent mis-registration to the user-focused pane instead of the agent's own pane — is hard to notice without it.

## Run

```bash
python3 ~/.claude/skills/p2p/tools/test_resolve.py
```

Exit 0 with all PASS lines = good. Anything else = regression.

For a stronger anti-regression check, **focus a different cmux pane than the one running the agent before invoking**. When focused == own pane, the anti-regression check auto-skips because it can't distinguish them.

## Multi-runtime verification prompt

Paste this into each agent (Claude Code, Codex, Gemini) and confirm exit 0:

> Run `python3 ~/.claude/skills/p2p/tools/test_resolve.py` and report the output. Should exit 0 with all checks passing. If any check fails, paste the full output plus `ps -o pid,ppid,tty,command -p $$ -p $PPID` and `env | grep CMUX` so the resolution path can be debugged. For a stronger test, focus a different cmux pane than yours before running.

## What it covers

| Check | Catches |
|---|---|
| ground-truth tty walk works | helper can't run inside cmux at all |
| Path 1 (normal env) matches truth | `cmux identify` regression |
| Path 2 (env stripped) matches truth | tty-walk regression — the original bug |
| Path 3 (override) returned verbatim | `AGENT_MSG_SURFACE_ID` flag regression |
| Path 4 (all paths fail) returns None | silent-fallback regression — `my_surface()` must return None so `cli.py` can wrap it as `errors.not_in_cmux()`; it must NOT fall back to the focused-pane surface_ref |
| stripped resolution ≠ focused surface | the original `focused`-fallback footgun re-appearing |

## Why the tty walk is non-trivial

Different agent runtimes wrap shell subprocesses differently, and `_ancestor_ttys()` has to handle all of them:

| Runtime | Subprocess tty | Walk must… |
|---|---|---|
| Claude Code | none (`??`, stdin from /dev/null) | walk up to the agent process itself, which inherits the cmux pane's tty |
| Gemini | its own internal pty (e.g. `ttys026`) — **not** a cmux pane | skip past the pty, walk up to the node process, which has the pane's tty |
| Codex | varies | same shape: keep walking past unknown ttys |

That's why the walk yields **every** ancestor's tty and matches against cmux's known set, instead of stopping at the first tty it finds. Stopping early gives the wrong answer on Gemini.

If a future runtime arrives where no ancestor has the pane's tty (e.g. the agent runs in a container that hides the host tty), the user can fall back to `AGENT_MSG_SURFACE_ID=surface:<N>`.
