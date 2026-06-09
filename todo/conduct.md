# conduct — todo

_Last refreshed: 2026-06-09 (flat scripts/ layout)._

Skill: `skills/conduct/` — cmux control plane (status read + runtime-aware
lifecycle control over an owned set). Design spec:
`$OBSIDIAN/plans/conduct-design-2026-06-09.md`.

Layout: flat Python in `skills/conduct/scripts/` — `conduct.py` (entry) plus
sibling modules `cli.py`, `core.py` (the `run_*` orchestration + `LIFECYCLE_VERBS`),
`cmux.py`, `ownership.py`, `adapters.py`, `errors.py`, and the `test_*.py` next to
them. Absolute flat sibling imports (`import cmux`, `from errors import ...`); no
package, no `sys.path` shim, no `pyrightconfig.json`. Run tests with
`python3 -m pytest skills/conduct/scripts`.

## Resolved (2026-06-09 codex reviewer ground-truth)

- **Codex runtime detection (was BLOCKING).** `cmux top` reports codex as an
  arch-suffixed, often-truncated binary name (`codex-aarch64-a`), not `codex`.
  Detection now matches a curated prefix allow-list (`codex-`, `claude-`) plus
  exact names, deliberately excluding `pi` from prefixing (would catch
  pip/pipenv/pixi). Verified live: surface:545 (codex) → `type: codex`.
- **Codex context% (was deferred + BLOCKING).** Codex 0.137.0 footer is
  `Context NN% left` (REMAINING). `CodexAdapter.context_pct` now parses it (both
  word orders) and converts to USED via `100 - left`. SEMANTICS PINNED:
  `context_pct` = percent of context USED (higher = closer to full). Verified
  this against the live claude statusline source
  (`~/.claude/statusline-command.sh` → `context_window.used_percentage`), so
  claude's `ctx:NN%` is already "used"; codex is converted to match. Verified
  live: surface:545 `Context 37% left` → `context_pct: 63`.
- **`state` field (was NON-BLOCKING gap).** `_agent_view` now emits `state`:
  coarse "busy" when the runtime shows an "esc to interrupt" affordance, else
  `null`. cmux tree/top expose no clean per-surface agent state, and
  fine-grained idle/needs-input/error classification is watchdog/observability's
  job — conduct only surfaces the cheap signal from the screen it already reads
  for context%. Shape now matches what SKILL.md/CLI advertise.

## Deferred (from spec §8)

- **Codex lifecycle keystrokes — reviewer-corroborated, NOT yet live-fired.**
  The codex reviewer confirmed `clear`=`/clear`, `compact`=`/compact`,
  `exit`=`/quit` for codex 0.137.0, matching `scripts/adapters.py`. These were
  NOT fired against a live codex agent here (no destructive verbs in this pass),
  so they remain unverified-by-execution but corroborated by the reviewer.
  claude/pi `clear`/`compact`/`exit` keystrokes are still the best current guess
  and unverified against live panes. `interrupt`→Esc and `kill`→close-surface
  are runtime-agnostic and confirmed by design.
- **Context% extraction for pi.** claude (`ctx:NN%`, used) and codex
  (`Context NN% left` → used) are now parsed and live-verified. pi exposes no
  parseable context indicator yet → reports `null`; add a parser when pi
  surfaces one.
- **Manifest staleness / GC policy.** Orphaned entries (dead target OR dead
  owner) are ignored live and reclaimed on next touch — no compaction runs.
  Optional: a periodic `conduct gc` to drop entries whose target UUID is no
  longer in the live tree. Not built; not needed for correctness.

## Open questions / interpretations made during build

- **`register --from-fork`** parses `session` (tfork's documented field) with
  fallbacks to `surface` / `surface_ref` / `uuid` / `surface_id`, and accepts
  either an inline JSON string or a file path. Revisit if tfork's result shape
  is pinned to a different key.
- **`$CMUX_SURFACE_ID` as a `surface:N` ref vs UUID.** caller_surface_uuid()
  treats an env value containing `-` and not prefixed `surface:` as a UUID;
  otherwise it falls back to `cmux identify`'s `caller.surface_id`. If cmux ever
  injects a bare `surface:N` into that env var, the identify fallback covers it.
- **`exit`/`kill` via `--all`** over the owned set are allowed by spec (§4) and
  implemented. They were NOT exercised against live agents during build (safety);
  only the keystroke/close dispatch was verified via stubbed unit tests.

## Verification status (post codex review)

- `scripts/test_ownership.py` — first-touch claim, same-owner pass,
  different-owner `owned_by_other`, orphan reclaim, release rules, owned-set
  scoping, persistence. PASS.
- `scripts/test_adapters.py` — runtime identification incl. `codex-aarch64-a` +
  arch variants and pip/pipenv/pixi over-match guards; verb→keystroke per
  runtime; unknown-runtime / unsupported-verb gates; claude `ctx:NN%` (used) +
  codex `Context NN% left`→used parsing; coarse busy `state`. PASS.
- `scripts/test_lifecycle.py` — stubbed-cmux integration: ownership-gated control,
  fail-closed refusals (no injection), captured keystroke dispatch, envelope
  shape, `--all` owned-set-only, `state` in view, codex runtime+context_pct
  end-to-end. PASS.
- Full suite: 61 passed. Pyright: 0 errors.
- Live read-only ground-truth: `status --agent surface:545` (real codex agent
  conduct_reviewer) → `type: codex`, `context_pct: 63` (from live
  `Context 37% left`), `state` present; released the claim. `status --agent
  surface:526` (own claude pane) → `type: claude`, `context_pct: 92`, `state`
  present; released. Manifest clean. No destructive verb run against any agent.

## Possible follow-ups

- SKILL.glyph is authored, compiled, and `glyph validate-output`-clean
  (SKILL.md + SKILL.ir.json shipped).
