# flux-mcp — todo

_Last refreshed: 2026-06-16_

Home: `mcp/flux/` (NOT a skill — outside `skills/`, no `SKILL.md`). Docs: `mcp/flux/README.md`.
Register: `./install.sh mcp [claude|codex|all]`.
Design: `$OBSIDIAN/plans/flux-mcp-design-2026-06-15.md`
Plan: `$OBSIDIAN/plans/flux-mcp-impl-plan-2026-06-15.md`
Packaging plan: `$OBSIDIAN/plans/flux-mcp-packaging-plan-2026-06-16.md`

## Done
- 2026-06-16 — Packaging: relocated `skills/flux-mcp/` → `mcp/flux/` so it is no
  longer discovered as a Skill-tool skill; fixed the gateway/identity binaries-root
  depth (`parents[3]/skills`); added one-step MCP registration via `install.sh mcp`
  (claude mcp add + idempotent codex config.toml block); removed stale skill
  symlinks; SKILL.md → README.md. Spec §3/§6/§10 updated. Tests: 29 passed.

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
- 2026-06-15 — E2E Claude (acceptance #5/#7) PASSED, headless `claude -p` with
  `--strict-mcp-config`, `--disallowedTools Bash Write Edit`:
  - Orchestrator scope, Bash+Write denied, only `mcp__flux__*` allowed: agent
    invoked `mcp__flux__p2p` (returned real `peer_not_found` code) AND
    `mcp__flux__tfork` (forked a real pane, `tfork_ok=true`, `session=surface:224`),
    while Bash was BLOCKED. This is the §7 payoff: messaging + forking with shell off.
  - Comms scope: `mcp__flux__tfork` and `mcp__flux__afork` are UNAVAILABLE (not in
    the agent's tool list); `mcp__flux__p2p` works. Confirms scope gating end-to-end.
- 2026-06-15 — E2E Codex (acceptance #6) PASSED, interactive `codex` under
  `--sandbox read-only`, isolated `CODEX_HOME`, flux comms MCP:
  - Agent called `flux.p2p` (one-time approval granted at the TUI prompt); the tool
    returned `{"ok": true, "resolved_by": "title_in_workspace", "surface": "surface:205"}`
    and the message was DELIVERED to `flux_mcp_impl` — a real agent→agent p2p
    round-trip through the MCP tool with the codex shell write-blocked.
  - NOTE (codex limitation, not flux): non-interactive `codex exec` blanket-cancels
    ALL MCP tool calls before reaching the server (`user cancelled MCP tool call`,
    ~0ms), regardless of `approval_policy`. Confirmed non-flux-specific via a benign
    `whoami` MCP control (also cancelled). The flux server itself starts + connects
    fine under the read-only sandbox; codex exec just can't auto-grant MCP approval.
    Interactive codex (the real Flux reviewer scenario) works with one approval.
