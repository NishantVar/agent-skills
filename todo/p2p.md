# p2p — backlog

_Last refreshed: 2026-06-20_

## Done

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
