# tfork todo

_Last meaningful refresh: 2026-06-22_

## Done

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
