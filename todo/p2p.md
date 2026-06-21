# p2p — backlog

_Last refreshed: 2026-06-20_

## Done

- **Locality-aware scope resolution (peer titles AND `--workspace` titles).**
  Default-scope resolution (no explicit `--workspace`/`--window`) now cascades
  by locality instead of hard-scoping to the caller's workspace:
  caller's own workspace → other workspaces in the caller's window → other
  windows. A single live match at the closest tier wins; two-plus at a tier
  returns candidates (`peer_ambiguous`) rather than silently picking; a miss
  surfaces the caller's own-workspace siblings as `peer_not_found` candidates.
  A renamed former-holder in the caller's OWN workspace (tier 1) still wins
  over a live current-title match in a farther tier (returns `peer_renamed`) —
  conservative, and preserves the `in_scope_rename_wins` regression. The same
  locality applies to `--workspace <title>` (e.g. `$p2p renderer in HTML` →
  `--peer renderer --workspace HTML` finds the nearest workspace titled HTML
  with no manual cmux inspection). Implemented as `resolve.resolve_peer_local`
  (new `bounce_out_of_scope=False` flag on `resolve_peer` lets a tier descend
  instead of bouncing) and `surface.resolve_workspace_title`; wired through
  `send.py`/`cli.py`. Existing exact-surface behavior is unchanged: live
  `--peer-surface` sends directly ignoring stale scope hints, wrong-title
  `--peer-surface` returns `peer_surface_mismatch`, and missing `--peer-surface`
  with `--peer` recovers via the same scoped/locality resolution. An explicit
  `--workspace`/`--window` still forces a single scope (no cascade). PR #25.

- **Surface refs now recover when the exact pointer disappears; first contact
  can be scoped by window/workspace/title.**
  Added `--window` support alongside `--workspace` for first-contact title
  resolution and stale-surface recovery. A successful send still returns the
  exact `surface` ref to store for follow-up. If a later send supplies
  `--peer-surface` and that surface no longer exists, p2p now re-resolves the
  asserted `--peer` within the available workspace/window scope and returns the
  replacement `surface` plus `previous_surface`. Live-but-wrong surfaces still
  bounce as `peer_surface_mismatch` to avoid silently delivering to the wrong
  agent. First-contact bootstraps now carry `peer_workspace` and `peer_window`
  hints so replies can recover across scope boundaries if the original surface
  ref disappears.

- **Stale `--peer-surface` no longer silently misroutes (`peer_surface_mismatch`).**
  The explicit-surface path treated the surface ref as both address *and*
  identity: it routed to whatever tab occupied the ref and read the title off
  it, never checking against the `--peer` title the caller also asserted. A
  surface ref carried over from an older bootstrap (multi-producer setups,
  repurposed tabs) stays live but can hold a *different* agent → message
  delivered to the wrong producer, reported as `ok: true`. Now: when `--peer`
  (identity) is supplied alongside `--peer-surface` (address), `send` verifies
  the surface still bears that title (casefold) and otherwise returns a new
  **`peer_surface_mismatch`** handoff (`current_title` names who's actually
  there; `rerun_argv` strips `--peer-surface` so the replay re-resolves by
  (workspace, title)). `--peer-surface` alone still routes directly. The
  earlier "just include `--workspace`" theory was wrong — `--peer-surface`
  short-circuits before workspace scope is ever consulted.

- **p2p never spawns.** `send` no longer writes spawn-bootstrap payloads or
  returns a `peer_unknown`/tfork handoff. A title that matches no live tab now
  returns **`peer_not_found`**:
  - other registered agents live in scope → handoff carries them as
    `candidates` (so a misnamed `--peer` gets a "did you mean" instead of a
    duplicate spawn);
  - none → empty `candidates`, `action_required: spawn_externally`.
  The calling agent decides whether to retarget or spawn via tfork/afork.
  Removed: `errors.peer_unknown`, `bootstrap.build_spawn_bootstrap`,
  `bootstrap.write_spawn_payload`, the `workspace_for_spawn` threading.

## Open

- **Unregistered live agents are invisible to the candidate list.** Candidate
  detection is manifest-based: only agents that have registered with p2p are
  offered as `peer_not_found` candidates (this is how shells / non-agent panes
  are correctly excluded). An agent that is live but has never registered won't
  appear, so a misnamed `--peer` toward it still yields empty candidates. p2p
  has no reliable agent-vs-shell signal for unregistered surfaces; revisit if a
  better liveness/identity signal becomes available.
