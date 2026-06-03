# cmux-watchdog — todo

Open backlog for the `cmux-watchdog` skill. Last refreshed 2026-06-03 (v0.3 self-exclusion + learned resolutions).

## What it is

Deterministic detector + tiered remediator for failed cmux panes. `watchdog.py`
owns the mechanical loop (`scan` / `watch`) and the single safe fix
(`send-enter` on a stuck composer). The calling agent owns judgement on risky
cases and never shells out to p2p or tfork — it returns handoffs instead
(per the skill-boundary rule in CLAUDE.md).

- `scan [--workspace <ref|title|all>]` — one-shot JSON `{candidates: [...]}`.
- `watch [--workspace ...] [--interval N] [--summary-interval N]` — NDJSON event stream for the Monitor tool; dedups, re-emits only after a finding clears and recurs; journals settled output + emits `summarize_due` ticks (v0.2).
- `digest [--workspace ...] [--date ...]` — flush each in-scope surface's unread journal lines to a digest file, advancing a per-surface cursor (v0.2).
- `send-enter --surface --workspace` — self-verifying safe remediation for `unsent_p2p`.
- `resend --surface --workspace` — self-verifying Up+Enter resend; the proven fix for a stalled `api_error` (v0.3).
- `record-resolution --label --action` — persist the action that fixed a granular api-error label to `resolutions.json` (v0.3).

Detection signatures (v0.1): `unsent_p2p` (tier safe), `api_error` (tier risky).

## v0.3 status (self-exclusion + learned resolutions)

Three changes landed (TDD, all green — 67 pytest unit tests):

- **Controller-pane exclusion.** `scan` and `watch` now drop the watchdog's own
  controlling surface before detect/journal, ending self-flagging false positives.
  `_controller_surface_ref()` reads `CMUX_SURFACE_ID`; a `surface:N` passes through,
  a UUID is mapped via `cmux identify --surface <id>` → `caller.surface_ref`. Unset
  env or any cmux error → skip nothing (degrade, never crash). Excludes detection
  AND journaling (interpreting "from scans entirely").
- **Learned-resolution store + auto-graduate.** `resolutions.json` at `_state_root()`
  (honors `CMUX_WATCHDOG_HOME`), keyed by the GRANULAR api-error label
  (`_API_ERROR_PATTERNS`), value = the action that worked. `record-resolution`
  upserts it. On detect, `apply_known_resolution()` (pure; store passed in as a dict)
  graduates a matching finding risky→safe, sets remediation to the stored action, and
  annotates `known_resolution`. `Finding` gained two fields: `label` (granular sub-type)
  and `known_resolution` — both now flow into every candidate/finding JSON row.
- **`resend` subcommand.** Reads screen, `send-key up`, `send-key enter`, sleeps 0.4s,
  re-reads; `resumed = active-marker appeared OR screen changed`. Mirrors `send-enter`.

SKILL.glyph updated (binary_contract, failure_signatures, auto_only_safe,
process_failure_finding gained a graduated-safe branch + a record-resolution step on
risky-fix success); recompiled via `/glyph:compile`, `validate-output` clean.

Design calls (surfaced to watchdog_lead): controller exclusion also skips journaling
the controller pane; `record-resolution` does no label-whitelist validation (kept
permissive); resolution graduation is applied generically by `label`, but the store
is keyed by api-error labels in practice.

## v0.1 status

- Binary built, 19 pytest unit tests passing (`tests/test_watchdog.py`).
- SKILL.glyph authored; compiled to SKILL.md via `/glyph:compile`.
- Live `scan --workspace all` returns valid JSON against real cmux.

## v0.2 status — journaling + worklog summary

Implemented in `watchdog.py` to fulfill the `SKILL.md` binary-contract/journal-model
(design: `$OBSIDIAN/plans/cmux-watchdog-journaling-design-2026-06-03.md`).

- Pure helpers `slugify` / `settled_lines` / `append_new` (overlap-anchored diff,
  no hash-dedup, gap-flag on lost overlap).
- `watch` now journals newly-settled, redacted pane output per surface to
  `~/.cmux-watchdog/journal/<date>/<ws_slug>__<surface_slug>__<surface_ref>.log`
  (batch `# <ISO>` header, `# <gap...>` marker), plus a `summarize_due` event +
  `--summary-interval` flag (default 3600, 0 disables).
- New `digest` subcommand: per-surface byte cursor in `~/.cmux-watchdog/cursors.json`
  (atomic temp+rename, persisted per file), digest files under
  `~/.cmux-watchdog/digests/<date>/`, exactly-once for serial invocations.
- Per-day sidecar `journal/<date>/index.json` records each surface's real identity
  (`workspace_ref` / `workspace_title` / `surface_ref` / `title`); `digest` scope
  resolution (`_scope_matches`) mirrors `filter_scope()` exactly, so
  `digest --workspace X` selects exactly what `watch --workspace X` journaled.
- 50 pytest tests passing; live watch+digest smoke (incl. ref-scoping consistency)
  verified against real cmux. Reviewed via `tfork coxn` reviewer (round 2).

### Notes / known boundaries (accepted, not bugs)

- **UUID-vs-ref default scope (pre-existing).** When `CMUX_WORKSPACE_ID` is a UUID
  but `parse_tree` only surfaces `workspace:N` refs, the default-caller-workspace
  match in `filter_scope` is already imperfect (bare `scan`/`watch`/`digest` would
  degrade to all). `digest` deliberately behaves *identically* to `filter_scope`
  here — fixing the UUID↔ref default was out of scope for v0.2.
- **Digest is serial-only.** The exactly-once cursor guarantee holds for
  non-concurrent invocations. No file lock / transactional state across the
  digest-write→cursor-save step; concurrent digests or a crash mid-run can
  re-digest the in-flight surface (never silently drop). Add locking only if a
  concurrent-digest use case appears.

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
