# cmux-observability — todo

Open work items for the `cmux-observability` skill. Update as items land or new ones surface. Last refreshed 2026-05-28 at v1.2 sign-off.

## ✅ Architecture change LANDED (2026-06-04): pure view layer — branch feat/cmux-capture-layer
cmux-watchdog is now the sole cmux reader/classifier; this skill is a **pure view
layer**. Implemented:
- `collect` no longer reads cmux. It ingests cmux-watchdog's **capture envelope**
  (`--input <path>` or stdin) via `ingest.py` (deterministic mapper -> Snapshot,
  `validate_capture_envelope` rejects unsupported `capture_schema_version` majors).
  The agent runs `watchdog.py snapshot` and pipes it in (skill-boundary: obs never
  shells out to watchdog).
- `summarize_io.pending_for_agent`/`attach_cached_summaries` gained a
  `redaction_meta` param: the envelope's `screen_hash` + `redactions_applied` are
  authoritative; obs never re-redacts/re-hashes and never sees raw text.
- DELETED: `collector/cmux.py`, `normalize.py`, `collector/classify.py`, and the
  cmux/classifier tests (test_collector_cmux, test_normalize, test_classify,
  test_state_classifier, test_classifier_integration, test_cli_state_wiring) —
  the v1.2 classifier + its tests now live in watchdog (`classify.py`,
  `test_state_wiring.py`). KEPT: `collector/discovery.py` + `collector/git.py`
  (git/productivity, not cmux), themes, finalize, render.
- test_cli/test_cli_finalize rewritten to feed envelopes; `test_capture_contract.py`
  asserts golden ingest + **zero cmux calls**. Obs suite **140 passed**.
- SKILL.glyph desc → pure view layer consuming the envelope; recompiled + validate
  clean. Shared golden fixture: `tests/fixtures/golden_snapshot.json` (byte-identical
  to watchdog's, regen via `skills/cmux-watchdog/tests/gen_golden.py`).

Design doc: `$OBSIDIAN/plans/cmux-capture-layer-design-2026-06-04.md`. The v1.2
classifier items below are now the spec of record FOR WATCHDOG (where the code
moved); kept here for history.

## Status of in-flight work

- **v1.1 — PR #18** (`feat/cmux-observability-dashboard-v1.1`): open, awaiting merge.
- **v1.2 scrollback classifier — PR #19** (`feat/cmux-observability-scrollback-state`, stacked on #18): open, signed off by qa_lead, 199 tests passing. HEAD `862c579`.
  - Final smoke envelope: `agents_total=32`, `running=0`, `needs_input=4`, `idle=28`, `unknown=0`. Artifacts at `/tmp/cmux-v1.2-smoke.{html,json}` run-id `b5b41efb05a7` (volatile — `/tmp` may not survive reboot).
  - Spec doc of record: `$OBSIDIAN/plans/cmux-observability-scrollback-state-design-2026-05-28.md`.

## v1.1.1 — small UX/correctness follow-ups (deferred from v1.1)

These were known-deferred at v1.1 cut. None block v1.2; pick up after the stack lands.

### 1. Hide/placeholder empty expanded workspace cards under active filter
When a state filter is active (e.g. "running"), workspace cards that have zero matching agents still render expanded with zero rows. Either collapse them, hide them, or show a "no agents matching filter" placeholder. UX call: probably hide; show "N workspaces hidden by filter" footer line.

### 2. Tag non-agent rows `data-state="unknown"` explicitly
Non-agent surfaces (terminal panes, browser previews, "no screen access" rows) currently render without an explicit `data-state` attribute. Set `data-state="unknown"` so the unknown-bucket CSS selector catches them uniformly and the unknown counter is consistent with what's on screen.

### 3. Promote copy-ref chips to real `<button>` + wire clipboard
The `⧉` chips next to each surface/workspace ref are currently styled `<span>`s with no click handler. Make them `<button>` elements, add `aria-label="Copy {ref}"`, wire `navigator.clipboard.writeText`, flash a 1-second confirmation. Keep the same visual chip styling.

### 4. T18 footer (deferred from v1.1)
Footer row with: snapshot timestamp, cmux version + commit, host, and the re-run command. Most of this is already in the hero block as plain text; T18 wants it pinned to a real `<footer>` with a `kbd`-styled command and a copy button. Check the v1.1 plan for the exact field list.

### 5. T19 keyboard shortcuts (deferred from v1.1)
- `f` → focus state filter
- `/` → focus search (if/when search lands)
- `r` → re-run hint (just shows the command, doesn't execute — security)
- `?` → keyboard shortcut help overlay
- `Esc` → close overlay / clear filter

Document in T18 footer.

## v1.2.1 — codex needs_input recall gap (filed during v1.2 sign-off)

**Problem.** Codex agents sometimes end their narrative with an inline question like `Tell me which to save: 1, 2, all, or none.` — no `Question:` prefix, no numbered `› 1.` confirm card. Current codex `needs_input` patterns don't catch this style, so the pane falls to `idle` via the chrome-alone fallback at 0.6 confidence.

**Observed example.** v1.2 smoke surface:160 — narrative ended with the "Tell me which to save" line, classifier returned `idle/scrollback` (0.6). Visually that's a needs-input state; UX impact is low (agent shows in idle bucket; Nishant opens the pane and sees the question immediately), but it's a real recall gap.

**Proposed heuristic.**
```
codex NEEDS_INPUT (additional rule):
  - last non-empty narrative line ends with `?`
  - AND no `─ Worked for` marker anywhere in tail window
  - AND codex chrome present
  → (needs_input, 0.5)
```

**Risk.** False positives on rhetorical questions in agent narrative. Needs a small fixture set:
- Positive: 2-3 codex panes ending with real questions to the user.
- Negative: 2-3 codex panes where the agent self-poses a question mid-narrative and then continues with an answer (these should stay idle).

**Out of scope for v1.2.** Filed as v1.2.1.

## Monitor (not yet actionable)

### State window sizing under pane-shape drift
The 24-line / 2-KB tail window is heuristic. Very long single lines (codex horizontal-rule continuations are ~80–300 chars each) could in principle consume the byte budget; in practice Worked-for + chrome stays well inside the window today. Act if classifier false-idle rate on codex climbs, or if a new agent kind ships with wider chrome.

### Pyright `reportMissingImports` noise on classifier tests
Editable-install + `_json_path` convention; pre-existing across the branch. Act when the broader repo Pyright config is normalized.

### gemini classification still punted
No gemini-specific patterns; gemini panes resolve via generic patterns or fall to unknown. No live gemini surfaces during Phase B capture window. When a live gemini corpus is available: same shape as the codex Phase B work — capture, derive patterns, pin fixtures.

## Shipped

- 2026-05-28 · v1.2 scrollback-driven state classifier — PR #19 (HEAD `862c579`). Landing review: `$OBSIDIAN/plans/cmux-observability-scrollback-state-v1.2-review-2026-05-28.html`.
- 2026-05-28 · Phase E follow-up: codex idle relaxation + chrome-only fallback — `0f9f314` + `862c579` (closed qa_lead HOLD on surface:160 + Reviewer P2/P3).

## Spec/coverage drift to watch

- The 15th fixture `tests/fixtures/scrollback/codex_idle__chrome_only_no_worked_for.txt` was added late by Monitor at Reviewer's request to cover the chrome-alone `(idle, 0.6)` fallback branch (previously unexercised). If anyone tightens the chrome-alone fallback later, that fixture is the canary.
- Confidence calibration table in the spec doc (running=0.9, needs_input=0.5–0.8 max-weight, idle=0.7, chrome-alone-idle=0.6) is the contract — don't drift without updating the spec.

## How to resume

1. Read `$OBSIDIAN/plans/cmux-observability-scrollback-state-design-2026-05-28.md` for v1.2 design context.
2. Read `$OBSIDIAN/plans/cmux-observability-dashboard-v1.1-plan-2026-05-27.md` for v1.1 plan (T18/T19 originate there).
3. PR #18 → PR #19 stack on GitHub.
4. Branch worktree: `/Users/nishantvarshney/.config/superpowers/worktrees/agent-skills/feat-cmux-observability` (v1.1 branch); v1.2 branch is `feat/cmux-observability-scrollback-state`.
5. After #18 merges, rebase #19 to main.

## Live agents at pause time

These were last seen alive in cmux. Nishant did not authorize shutdown — they're left running per the HARD RULE in CLAUDE.md.

- **qa_lead** — surface:128 (this agent)
- **Monitor** — surface:67, workspace:17 (v1.2 implementer)
- Reviewer, builder, plus various other workspace agents — see live dashboard at `/tmp/cmux-v1.2-smoke.html` for the full set as of run-id `b5b41efb05a7`.
