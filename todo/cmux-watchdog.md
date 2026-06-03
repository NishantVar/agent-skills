# cmux-watchdog — todo

Open backlog for the `cmux-watchdog` skill. Last refreshed 2026-06-03 (v0.1 authoring).

## What it is

Deterministic detector + tiered remediator for failed cmux panes. `watchdog.py`
owns the mechanical loop (`scan` / `watch`) and the single safe fix
(`send-enter` on a stuck composer). The calling agent owns judgement on risky
cases and never shells out to p2p or tfork — it returns handoffs instead
(per the skill-boundary rule in CLAUDE.md).

- `scan [--workspace <ref|title|all>]` — one-shot JSON `{candidates: [...]}`.
- `watch [--workspace ...] [--interval N]` — NDJSON event stream for the Monitor tool; dedups, re-emits only after a finding clears and recurs.
- `send-enter --surface --workspace` — self-verifying safe remediation.

Detection signatures (v0.1): `unsent_p2p` (tier safe), `api_error` (tier risky).

## v0.1 status

- Binary built, 19 pytest unit tests passing (`tests/test_watchdog.py`).
- SKILL.glyph authored; compiled to SKILL.md via `/glyph:compile`.
- Live `scan --workspace all` returns valid JSON against real cmux.

## Backlog / not yet actionable

### process_exited signature
Detect an agent process that died unexpectedly (pane dropped to a bare shell
prompt with prior agent chrome). Deferred from v0.1 to avoid false positives on
plain terminals. Remediation would be a tfork respawn handoff. Add when there's
a real corpus of exited-agent screens to pin fixtures against.

### unsent_p2p heuristic robustness
Current detection: a `[from:]` frame in the bottom `_TAIL_WINDOW` (30) lines
with no agent output / active-spinner indicator below it, treating box-interior
(`│`-prefixed) and footer-hint lines as inert. Heuristic — validate against
codex/gemini composer chrome (only Claude Code box-drawing is well-covered).
Watch for false negatives when a long message wraps past the window, and false
positives on agents whose composer chrome differs.

### scrollback vs viewport for api_error
`scan` reads a single 120-line viewport. An API error that has already scrolled
out of view won't be caught. If recall matters, add a scrollback read
(`--scrollback`) for the error pass while keeping the viewport read for the
composer pass.

### state grounding via `cmux top`
Detection is screen-only. Could cross-check `cmux top --all` tag state
(running / needs input) to raise/lower confidence, but tag→surface mapping is
per-workspace, not per-surface — punted for v0.1.

### Reuse vs duplication with cmux-observability
The sibling `cmux-observability` skill already reads screens + redacts across
workspaces. Kept standalone per the skill-boundary rule (skills don't shell out
to each other). Revisit only if the redaction/read-screen logic drifts apart in
a way that causes real bugs.
