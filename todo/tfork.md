# tfork todo

_Last meaningful refresh: 2026-06-18_

## Done

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
  - Opt-in only — the default split / `--workspace` paths are unchanged
    (per user decision; we did NOT also change the default-fork focus
    behavior).

## Known issues / follow-ups

- **cmux `close-window` ineffective in live testing** — during dev, `cmux
  close-window` returned `OK` but did not actually remove empty windows from
  the running cmux instance (`close-window` also rejects `window:N` refs,
  wanting a UUID). Left a few empty test windows behind. This is cmux-side,
  not tfork; worth reporting upstream if it recurs.
- Possible future toggle: `--window new --focus true` to opt into focusing
  the new window (default stays no-focus).
- Deferred: the default split path uses `cmux new-split --focus true`
  (load-bearing for lazy shell instantiation). If focus-steal on plain forks
  is still a complaint, revisit whether that focus can be released after the
  shell comes up.
