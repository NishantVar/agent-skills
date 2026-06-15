# flux-mcp — todo

_Last refreshed: 2026-06-15_

Design: `$OBSIDIAN/plans/flux-mcp-design-2026-06-15.md`
Plan: `$OBSIDIAN/plans/flux-mcp-impl-plan-2026-06-15.md`

## Parked / follow-ups
- afork `-c` server-config injection for codex per-agent binding (spec §6/§11).
- Pi extension-tool integration (spec §10, out of scope for MVP).
- Daemonized-host identity fallback: set AGENT_MSG_SURFACE_ID from tfork's
  creation-time session ref at fork time (spec §5; not observed on claude/codex).

## Live verification log
- 2026-06-15 — Live identity verification (spec §5 / acceptance #4) PASSED from a
  cmux pane via `flux_mcp.py --scope comms`:
  - Normal case: p2p `peer_not_found` handoff returned VERBATIM through the tool;
    surface resolved correctly (candidate `flux_lead`@`surface:132` in `workspace:18`,
    the real sibling); message delivered via a server-owned temp file; no
    surface-resolution warning on stderr.
  - Stale-env case (`CMUX_SURFACE_ID=surface:99999`): identical correct resolution
    (candidate `flux_lead`), proving the controlling-tty walk corrected the stale
    env. No warning on stderr.
- E2E Claude / E2E Codex (acceptance #5/#6): pending (Task 8).
