# cmux-watchdog — todo

Open backlog for the `cmux-watchdog` skill. Last refreshed 2026-06-04 (v0.5 autonomous summarization via DeepSeek-V4 + launchd; overnight catch-up).

## v0.5 status — autonomous summarization (summarize.py + LLM API + launchd)

Solves "hourly worklog summaries don't happen overnight without a babysitting
agent." Root cause confirmed live: the producer emits `summarize_due` ticks fine,
but nothing summarized them because summarization required an attached consumer
agent (and `$OBSIDIAN/worklog/2026-06-04.md` was simply absent all morning).

Decision (user, 2026-06-04): summarize via a **generic OpenAI-compatible LLM
API (DeepSeek-V4 default)**, not an agent — so no babysitter at all. **Unify** on
this path (replaces the Haiku-subagent summary) and trigger it durably with
**launchd**.

- **New sibling `summarize.py`** (NOT watchdog.py — the binary stays network-free
  and model-free; this is the explicit reconciliation of the user's directive with
  the hard binary constraint). Two subcommands:
  - `run [--workspace] [--max-days N] [--catch-up] [--date]` — shells out to
    `watchdog.py digest`, POSTs each surface's unread digest to
    `<LLM_API_BASE>/chat/completions` (model `<LLM_MODEL>`, default
    `deepseek-v4-flash`), appends bullets to `$OBSIDIAN/worklog/<date>.md` under
    `## HH:MM — <ws>`. Plain stdlib HTTP, no SDK dep → any OpenAI-compatible
    provider works by changing env.
  - `install [--interval N] [--workspace] [--load] [--run-at-load]` — renders (and
    optionally `launchctl bootstrap`s) a launchd LaunchAgent that runs `run` every
    N seconds. Durable across reboot/logout/agent-crash. Stop via `launchctl bootout`.
- **Overnight catch-up + 1-day cap** (user, 2026-06-04): `run` catches up EVERY
  unsummarized day since the last summarized point (the digest cursor), not just
  today. Bounded autonomy: only days within `--max-days` of today (default 1 =
  today + yesterday) run automatically; older backlog is returned in `deferred`
  with a ready `resume_cmd`, so a human approves before >1 day of history is
  churned. `--catch-up` lifts the cap.
- **Config**: env first, then `~/.cmux-watchdog/summarizer.env` (KEY=VALUE):
  `LLM_API_KEY`/`DEEPSEEK_API_KEY`, `LLM_API_BASE`, `LLM_MODEL`, `OBSIDIAN`. The
  env file is REQUIRED for the launchd job (it doesn't inherit the shell env).
- **Tests**: `tests/test_summarize.py`, 14 new (81 total, all green). Pure-fn tests
  (env parse, config merge, payload, plist render, worklog format) + end-to-end
  `run_pass`/`run_catchup` running the REAL `watchdog.py digest` against a temp
  `CMUX_WATCHDOG_HOME` with a STUBBED HTTP transport (no network in tests).
- **Live demo done**: launchd job (RunAtLoad, isolated temp state/vault + local
  mock LLM) fired with NO agent attached → worklog landed, cursor advanced;
  catch-up summarized yesterday and deferred 2-days-ago; `--catch-up` released it.
- **SKILL.glyph**: `run_worklog_summary` now calls `summarize.py run` (unified);
  new `summarizer_component` context; `local_only` reworded; new flow step to
  install the launchd job; `summary_interval` doc updated. Recompiled
  (`glyph compile --emit-ir --strict`), `validate-output` clean.

### v0.5 single-owner coordination (cursor-race fix)

Both the launchd summarizer and an attached consumer run `watchdog.py digest`,
which advances the SAME per-surface cursor — if both run they split each hour's
lines. Resolved with a **`single_summary_owner`** constraint: the durable launchd
job is the default owner; once installed+loaded the interactive consumer must NOT
digest/summarize (summarize_due ticks become no-ops, attach-drain skipped) and
keeps only capture+detect+safe-remediation. Consumer summarizes itself only when
launchd is absent/inactive; an explicit user "summarize now" `launchctl kickstart`s
the job. Encoded inside the `run_worklog_summary` block (ownership guard at its
top — one branch level, so it compiles/validates). Coordinated live with
watchdog_observer (their interactive consumer stopped digest-on-tick).

### CAPTURE ROOT CAUSE — overnight empty journal (verified 2026-06-04)

The reason summaries didn't happen overnight was NOT only the missing consumer —
**capture produced nothing today either.** Root cause: the live producer was
launched with no `--workspace`, so it scoped to `CMUX_WORKSPACE_ID`, which is a
**UUID** (`8E6903E5-…`). `watchdog.py filter_scope` can't match a workspace UUID
against the `workspace:N` refs from `parse_tree`, so it matched **zero** panes and
journaled nothing. This is the pre-existing "UUID-vs-ref default scope" issue from
the v0.2 notes — latent until the producer ran un-scoped overnight.

Verified directly: `watch` with default(UUID) scope → **0** journal files;
`watch --workspace all` (CMUX_SURFACE_ID unset) → journaled the actively-producing
pane surface:325 (probe text present) + ~40 live panes. So capture-of-active-panes
WORKS; the bug is purely scope resolution.

- **Quick fix (applied live by observer):** producer relaunched with
  `--workspace all` (pid 68988); journal/2026-06-04 now populating.
- **Proper fix (DONE, watchdog.py + TDD):** see "watchdog.py fixes" below.

### watchdog.py fixes (observer-requested, TDD) — DONE

Two capture/detection-layer fixes landed in `watchdog.py` (88 tests green):

1. **filter_scope UUID→ref resolution** (closes the latent UUID-vs-ref item).
   `cmux tree` (text AND `--json`) only yields `workspace:N` refs — workspace
   UUIDs appear nowhere — so a UUID scope (the inherited `CMUX_WORKSPACE_ID` of an
   un-scoped launch) matched zero and silently journaled nothing. Fix: new
   `_caller_workspace_ref()` (mirrors `_controller_surface_ref`: resolves the
   caller's workspace UUID→ref via `cmux identify`) + `_resolve_scope_token()`,
   used by BOTH `filter_scope` and `_scope_matches` (kept mirrored). A UUID is
   assumed to be the caller's own workspace; if unresolvable it degrades to `all`
   rather than zero. Verified live: default(UUID) scope now journals `workspace:29`
   panes (was 0). Tests: UUID→ref resolve, default-env UUID resolve, unresolvable→
   all, ref/title/all unchanged, `_scope_matches` mirror. (Limitation: an explicit
   *other* workspace's UUID can't be mapped — use its ref/title; not a real case.)

2. **api_error token-count false-positive.** The detector matched bare codes
   (`429`, `5xx`) anywhere in the tail, colliding with Claude/Codex thinking
   status lines ("↓ 429 tokens", "500 tokens") — it flagged a *healthy thinking*
   agent as `rate_limit`/risky, and `--workspace all` would spam this from every
   busy pane. Fix: negative-lookahead `(?!\s*tokens?\b)` on the bare-number
   alternatives in the `rate_limit` / `server_5xx` patterns; explicit phrases
   (rate limit / overloaded / "Too Many Requests" / server-error words) still
   fire. Tests: thinking-status lines (429/500/503 tokens) → no flag; real
   "429 Too Many Requests" / "HTTP 503" / "rate limit" / "500 internal server
   error" → still flagged.

These are internal capture/detection refinements — no SKILL.glyph change needed
(agent-facing contract unchanged); glyph still validates clean.

**OPERATIONAL NOTE (observer, 2026-06-04):** the detached producer imports
`watchdog.py` at launch; Python won't hot-reload, so a `watchdog.py` change has NO
effect on a running producer until it's bounced. After this fix the producer was
restarted (pid 26401, `--workspace all`, single producer, journal/2026-06-04
populating, 45 surfaces). Anyone editing watchdog.py while a live producer runs
must kill + relaunch it.

### v0.5 review round (watchdog_reviewer / coxn) — addressed

Verdict was fix-then-ship; all findings resolved (97 tests, glyph clean):

- **BLOCKING — cursor advanced before summary success (data loss).** `digest`
  advances the journal cursor when it writes a digest FILE, so a failed LLM/append
  left content un-summarized AND un-retried. Fixed: digest files are now the
  durable unit, tracked in a `summary_state.json` manifest; a file is marked
  summarized ONLY after its bullets are appended. Per-file LLM errors are caught
  (reported in `failed`); append failure returns ok:false with nothing committed;
  `run_catchup` revisits orphan dates (no new journal bytes but unsummarized
  manifest entries). Tests prove a failed run retries the same digest next run.
- **Should-fix — plist XML injection.** `render_plist` now uses `plistlib.dumps`
  (was f-string); paths/scope with `&`/`<`/spaces produce a valid plist. Test
  parses the output with `plistlib.loads`.
- **Should-fix — `install --load` false success.** Returns ok:false / nonzero with
  stderr when `launchctl bootstrap` fails; emits `status_cmd`
  (`launchctl print gui/<uid>/<label>`, exit 0 ⇒ loaded) so consumers can tell
  loaded / plist-only / absent. SKILL single_summary_owner + run_worklog_summary
  guard now reference that check.
- **Should-fix — no lock around the run.** Added an advisory `fcntl.flock`
  (`summarizer.lock`); a concurrent run returns `{ok:true, skipped:'already_running'}`.
- **Should-fix — UUID scope baked into launchd.** `install` rejects a workspace
  UUID (the job has no caller context to resolve it) with a clear error.
- **Nit — resume_cmd not shell-quoted.** Now built with `shlex.quote`.
- **Nit — api_error token edge.** Added `too many requests` phrase matcher;
  documented + tested the accepted residual blind spot (a bare "<code> tokens …
  exceeded" with no rate-limit/HTTP phrase won't flag — rare).
- Reviewer-confirmed-fine (no change): config precedence, direct worklog append,
  skill-boundary separation, digest-text-to-LLM (redaction is upstream).

### v0.5 open / not-yet-done
- **Config now reads `~/genesis/.env`** (in addition to `~/.cmux-watchdog/summarizer.env`;
  env > summarizer.env > genesis). The user added the key(s) there. Verified
  WITHOUT reading the secrets file: `load_config(env={})` resolves `api_key present:
  True` and `OBSIDIAN -> /Users/nishantvarshney/obsidian` (tilde now expanded —
  `OBSIDIAN=~/obsidian` in the file would otherwise create a literal `~` dir;
  `load_config` runs `expanduser`/`expandvars`). NOTE TO SELF/AGENTS: never read
  `~/genesis/.env` directly — only the script consumes it.
- **Real DeepSeek HTTP round-trip still not exercised** — config resolution is
  verified, but no actual call to api.deepseek.com has been made (demo used a local
  mock). To go fully live: `summarize.py install --interval 3600 --workspace all
  --load`, then confirm a worklog section lands after the first fire.
- **Worklog write is direct file append, NOT the obsidian CLI** (deviation from the
  global "prefer obsidian CLI" pref) — chosen for robustness under launchd's
  minimal env where the CLI may not resolve. Revisit if the user wants CLI writes
  for the attached-consumer path.
- **`CMUX_WATCHDOG_HOME` is env-only** (not read from summarizer.env), so sandboxing
  the launchd job to a non-default state root needs a plist `EnvironmentVariables`
  block (prod uses the default `~/.cmux-watchdog`, so this is a non-issue there).
- **Capture-layer gap (observer-flagged, separate concern)**: today's
  `journal/2026-06-04/` was empty even with a live producer. Likely benign —
  `journal_surface` seeds a baseline on first sight and only appends NEW settled
  lines, so idle panes journal nothing (yesterday was full because of active work).
  Worth confirming the producer enumerates current in-scope agent panes. This is
  watchdog.py's capture layer, not the summarize layer; the autonomous summarizer
  produces real worklog content only once capture journals something.
- **Two producers were running** (pids 65663, 76972) at investigation time —
  violates the single-producer rule (double-journals). Live-ops cleanup for the
  observer; not a skill-code issue.

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

## v0.4 status — decoupled producer/consumer + handler hand-off (SKILL-only)

Run-model rework. **No `watchdog.py` changes** — all existing subcommands
(`scan` / `watch` / `digest` / `send-enter` / `resend` / `record-resolution`)
already provide every primitive; v0.4 only changes how the agent orchestrates
them. Design: `$OBSIDIAN/plans/cmux-watchdog-decoupled-design-2026-06-04.md`.

Replaces the old coupled model ("agent spawns its own `watch` and Monitors it")
with a split:

- **Producer** (always on, detached): `watch … >> ~/.cmux-watchdog/inbox/findings.ndjson`.
  Exactly one instance (dedup state lives in-process; a second double-journals).
  Captures/detects/journals + appends `summarize_due` ticks regardless of any agent.
- **Consumer** (this skill in an agent; may or may not be running). On attach:
  `ensure_producer_running` → `scan` catch-up → `run_worklog_summary` drain →
  Monitor-tail the inbox. Self-fixes safe findings; hands risky ones off.
- **Handler hand-off** (the two locked decisions, 2026-06-04): risky findings are
  **poked to a designated handler agent** (new `handler` param = tab title) **via
  the p2p skill, never blocking** on the user. Poke the *healthy handler*, not the
  stalled pane. Payload includes the exact `record-resolution` command so the
  handler closes the learning loop in its own turn. `peer_unknown` → leave in
  inbox, no tfork spawn. No handler configured → surface to user. `report_only` →
  nothing.

SKILL.glyph changes: new `handler` param + `ensure_producer_running` block + new
`inbox_model` context; `process_failure_finding` risky path rewritten (pause →
hand-off); `auto_only_safe` → `auto_safe_handoff_risky`; `binary_contract` /
`failure_signatures` touched up. Recompiled via `/glyph:compile`; `validate-output`
clean; `.claude/skills` is a symlink so the mirror is automatic.

### v0.4 open / not-yet-done

- **No live end-to-end test yet.** The decoupled flow is authored + compiled but
  not exercised against real cmux (detached producer → inbox file → consumer tail
  → handler poke). Needs a smoke run: start the producer, kill/restart a consumer,
  confirm attach-time `scan` catch-up + inbox tail + a real p2p poke land.
- **Handler-offline retry gap (accepted).** A poke that fails (`peer_unknown`)
  isn't retried until the finding clears+recurs or the next consumer attach-scan
  re-surfaces it. Revisit only if dropped risky findings bite.
- **`ensure_producer_running` race.** Two consumers attaching near-simultaneously
  could both `pgrep`-miss and launch a producer. Single-user reality makes this
  unlikely; add a lockfile only if it actually happens.

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

- **UUID-vs-ref default scope (pre-existing).** ✅ RESOLVED in v0.5 (see
  "watchdog.py fixes"). `filter_scope`/`_scope_matches` now resolve a workspace
  UUID → `workspace:N` ref via `cmux identify`, so bare `scan`/`watch`/`digest`
  match the caller's panes instead of degrading. (NB: the original note said it
  "would degrade to all" — in reality it matched ZERO, which is what silently
  broke overnight capture on 2026-06-04.)
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
