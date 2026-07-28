# p2p — backlog

_Last refreshed: 2026-06-23_

## Done

- **Self-identity drift on re-tasked panes no longer silently misframes
  `[from: …]`.** A pane already registered under a prior role that replied
  to an inline bootstrap suggesting a different title was silently keeping
  the stale identity (`_ensure_self` short-circuited on the existing
  manifest, dropping `--bootstrap-suggested-title`), so every outgoing
  frame used the wrong prior role. Now a differing `--bootstrap-suggested-title`
  on an already-registered surface returns a new **`self_title_conflict`**
  handoff instead of silently keeping OR adopting it (adopting blindly would
  let a misrouted bootstrap — which routes by tab title — hijack a pane that
  legitimately holds another role). Resolution: an explicit, differing
  `--my-title` is now treated as a deliberate **re-identification**
  (re-register + tab rename, prior title preserved in `former_titles` for
  `peer_renamed` bridging) — the path the handoff points a genuinely
  re-tasked agent toward. The first-contact bootstrap trailer also tells a
  mis-targeted agent to bounce with a misroute notice rather than adopt.
  `registry.register` gained an optional `former_titles=`. Tests in
  `test_send.py` (conflict→handoff, my-title re-identify, matching-suggested
  no-op). The `peer_surface_mismatch` / stale-`--peer-surface` recovery was
  already correct and left untouched. NOTE: `SKILL.ir.json` is stale and
  predates this change (params/constraints already drifted) — a full
  `glyph icompile` + `validate-output` pass is owed separately.

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

- **Handle cmux paste-buffer races during parallel fan-out.** A Flux producer
  close-sweep fanned out p2p messages to five gate owners in parallel; two
  delivered, while three failed with `transport_failed` /
  `cmux paste-buffer failed: Buffer not found`. Sequential retries to the failed
  peers succeeded. This should be fixed in the p2p transport or helper flow, not
  preserved as global memory: parallel fan-out should avoid buffer-name races or
  automatically retry sequentially before surfacing a delivery failure.

- **Misrouted role-specific communication should make the recipient stand down,
  not act.** A Flux run produced a charter/brief mismatch: a pane's injected
  charter did not match the role named in the p2p brief, and a `title_collision`
  on the expected title suggested the real role-holder was already seated
  elsewhere. This should be handled at the p2p communication layer, not as
  Flux-local shared memory: when the incoming bootstrap, suggested title,
  asserted peer identity, or first-message role target conflicts with the
  recipient's current/injected identity, p2p should make the safe response
  obvious and preferably mechanical — report a misroute/identity conflict and
  stand down instead of answering the work request. Consider strengthening the
  bootstrap guidance and/or adding a first-contact handoff that tells the caller
  to retarget the already-seated role rather than letting the recipient infer
  the policy from prose.

- **Resolve the true surface id internally (kill the `cmux identify` workaround).**
  p2p addresses peers by `AGENT_MSG_SURFACE_ID`, but inherited cmux env vars
  (`CMUX_SURFACE_ID` / `WORKSPACE_ID`) can be **stale**, so reading one's own
  surface via `cmux identify` misroutes messages. Flux currently works around
  this at the brief level — its dispatch convention tells agents to source
  `AGENT_MSG_SURFACE_ID` from **`tfork`'s result** (the true forked surface),
  not `cmux identify`. The durable fix belongs here in the tooling: p2p should
  resolve the caller's true surface itself (e.g. from the authoritative cmux
  tree / pane-surface map rather than trusting inherited env), so the workaround
  becomes unnecessary and every consumer (incl. Flux operated repos) gets
  correct routing without a manual rule. Removing this need also lets Flux drop
  the cmux bullet from the dispatch conventions it seeds into operated repos.

- **Unregistered live agents are invisible to the candidate list.** Candidate
  detection is manifest-based: only agents that have registered with p2p are
  offered as `peer_not_found` candidates (this is how shells / non-agent panes
  are correctly excluded). An agent that is live but has never registered won't
  appear, so a misnamed `--peer` toward it still yields empty candidates. p2p
  has no reliable agent-vs-shell signal for unregistered surfaces; revisit if a
  better liveness/identity signal becomes available.
