# p2p — backlog

_Last refreshed: 2026-06-09_

## Done

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
