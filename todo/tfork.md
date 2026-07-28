# tfork todo

_Last meaningful refresh: 2026-07-28_

## Done

- **Versioned `launch_outcome` + `--launch-contract`** (2026-07-28, branch
  `launch-contracts-01`). Issue 01 of the `agent-model-effort-policy` PRD.
  Every success result — and the three failure handoffs where a launch was
  mechanically attempted (`split_failed`, `window_create_failed`,
  `spawn_failed`) — now carries a `launch_outcome` object with exactly
  `version, state, reason_code, evidence_code, start_sentinel_seen,
  end_sentinel_seen, exit_status, foreground`. It is the only field a policy
  may branch on; the free-form `note` is never a policy input.
  - `state` ∈ `started | prework_failure | unknown`. `prework_failure` is the
    only state that licenses trying a different runtime or model. `unknown`
    can NEVER be elevated — no exit status, pane text, or note reading turns
    it into a failure. Retrying on `unknown` is how you get two live agents.
  - **tfork stays runtime-agnostic.** It holds no runtime or model table. The
    only trusted runtime-specific evidence comes from the `--launch-contract`
    sidecar afork wrote. A fork without one still runs and still reports an
    outcome, but degrades to `unknown` wherever it would have classified.
  - `verify.py` split into `observe_fork` (facts) + `verdict` (the human
    reading); `result.py` derives the outcome from the SAME observation, so
    the machine and human readings can never disagree. A test pins that the
    pane is read exactly once.
  - Delivery failures split: a failed `paste-buffer` means Enter was never
    sent ⇒ trusted `command_delivery_absent`/`prework_failure`/retryable. A
    failed `send-key` means the line was already in the pane and may have run
    ⇒ `delivery_ambiguous`/`unknown`/NOT retryable.
  - Pre-launch stops (`no_terminal`, `surface_resolution_failed`) and caller
    mistakes (bad arguments, anchor/workspace/window errors) carry no outcome
    at all — they never attempted a launch.
  - Tests: `tests/test_launch_outcome.py` (derivation matrix + contract-object
    invariants) and `tests/test_launch_outcome_wiring.py` (run_fork, CLI, and
    the failure handoffs).

### Open follow-ups

- **`tforklib/outcome.py` is byte-duplicated from `aforklib/`.** The skills
  install as independent symlinked directories, so neither can import the
  other. A test in *both* suites asserts byte identity — that is the only
  thing keeping the two halves of the contract in agreement. Collapse it if
  the skills ever gain a shared install root.

- **Default split fork no longer steals focus** (2026-06-22). `_new_split` now
  creates the split with `cmux new-split --focus false` instead of `--focus
  true`. The `--focus true` was load-bearing only because cmux instantiates a
  split's shell lazily (an unfocused split is a surface record with no shell).
  `_wait_ready` now wakes that lazy shell with a `cmux send-key --surface <ref>
  enter` after a failed read-screen poll — a keystroke brings the shell up
  *without* moving focus. Verified live: real fork into a split keeps the
  caller's focused workspace and still starts the agent/command. Eagerly-seeded
  panes (workspace/window placement) succeed on the first poll and never get
  the nudge. Tests in `tests/test_focus.py`. This is the universal default fix
  — every front door (incl. afork) inherits it; no new flags.

- **`--window` flag** (2026-06-18). Fork into a separate top-level window so
  spawning an agent doesn't steal focus / switch the caller's workspace.
  - `--window new` → fresh window (cmux `new-window` does not move focus),
    reuses the window's seeded workspace (renamed in place when `--workspace`
    is also given, so no orphan default workspace).
  - `--window <ref|index|UUID>` → targets an existing window, creating /
    reusing a workspace inside it.
  - Mutually exclusive with `--anchor`; composes with `--workspace` and
    `--placement`.
  - Result JSON gains a `window: {ref, created}` field (null when unused).
  - Backend: `CmuxTerminal.resolve_window`; `_cmux_tree` now requests
    `--id-format both` so a freshly-created window's UUID maps back to its
    tree node. Tests in `tests/test_window.py`.
  - Opt-in only — at the time, the default split path was left untouched.
    (Superseded 2026-06-22: the default split path is now no-focus too — see
    the focus entry above.)

## Known issues / follow-ups

- **cmux `close-window` ineffective in live testing** — during dev, `cmux
  close-window` returned `OK` but did not actually remove empty windows from
  the running cmux instance (`close-window` also rejects `window:N` refs,
  wanting a UUID). Left a few empty test windows behind. This is cmux-side,
  not tfork; worth reporting upstream if it recurs.
- Possible future toggle: `--window new --focus true` to opt into focusing
  the new window (default stays no-focus).
- Possible future toggle: a `--focus true` opt-in for the split path, for
  callers who *do* want the new split focused (default is now no-focus).
