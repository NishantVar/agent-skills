# flux-mcp — Flux comms/fork MCP server

`flux-mcp` is a **stdio MCP gateway server**, not a Skill-tool skill. It lives in
`mcp/flux/` (deliberately outside `skills/`) so the repo installer never lists it
as a skill. Hosts (Claude Code, Codex) spawn it per session over stdio. It
subprocesses the existing `p2p`, `afork`, and `tfork` skill binaries under
`skills/` and returns their JSON output verbatim. No auto-chaining, no business
logic — the calling agent decides what to do with each response.

## Install / register (one step)

From the repo root:

```
./install.sh mcp all          # register for claude AND codex
./install.sh mcp claude       # claude only
./install.sh mcp codex        # codex only
```

This runs `claude mcp add flux …` (user scope, `--scope orchestrator`) and writes
the codex `[mcp_servers.flux_comms]` / `[mcp_servers.flux_orchestrator]` tables to
`~/.codex/config.toml` — no manual JSON/TOML copy-paste. Re-running is idempotent
(the codex block is delimited by `# >>> flux-mcp` markers and rewritten in place;
the claude entry is removed-then-added). The command also prunes any stale
`~/.<agent>/skills/flux-mcp` skill symlink left by an older install.

## Invocation (what the registration wires up)

```
python3 <repo>/mcp/flux/flux_mcp.py --scope {comms|orchestrator}
```

Stdlib-only (Python 3.x standard library; no `mcp` package or third-party
dependencies). Pin the host's `python3` to a stable 3.x to avoid breakage from
system upgrades (spec §11).

## Tools and scopes

| Scope | Tools exposed | Intended for |
|---|---|---|
| `comms` | `p2p` | Every agent (default) |
| `orchestrator` | `p2p`, `afork`, `tfork` | Leads and producers |

For per-tool argument semantics, read each wrapped skill's own `SKILL.md`
(`skills/p2p`, `skills/afork`, `skills/tfork`) — they are not duplicated here.
Quick reference for required args:

- **p2p** — `message` (string); usually also `peer` (destination cmux tab title). Route directly by surface with `peer_surface` (a `surface:N` ref) instead of/alongside `peer`.
- **afork** — `runtime` (string, e.g. `claude`, `codex`).
- **tfork** — `command` (string).

## Boundary rule (spec §8)

The server **never auto-chains**. It returns each binary's JSON verbatim,
including handoff objects (e.g. p2p's `peer_not_found`, afork's `ready_to_fork`).
The calling agent reads the response and decides the next call. This mirrors the
skills' own inter-skill boundary rule — skills hand off, they do not chain.

## Identity and surface resolution (spec §5)

On each tool call the server resolves the caller's cmux surface via
`p2plib/surface.py:my_surface()` and injects it into `AGENT_MSG_SURFACE_ID` and
`TFORK_SURFACE_ID` for the wrapped subprocess call. This ensures a forked agent
with a stale `CMUX_SURFACE_ID` in its environment still routes correctly.

**Daemonized-host fallback (spec §5):** if a host daemonizes or double-forks the
server (reparenting the process to pid 1), the PPID chain breaks and the
controlling-tty walk cannot resolve the surface. In that case set
`AGENT_MSG_SURFACE_ID` at fork time from tfork's creation-time session ref. This
path has not been observed on Claude Code or Codex.

## Claude Code per-agent gating (spec §6/§7)

The `./install.sh mcp claude` registration adds a single `flux` server at
`--scope orchestrator`. Restrict individual agents via agent frontmatter
`tools: mcp__flux__p2p` and/or `permissions.deny`. Claude Code has true per-agent
MCP gating; `deny` beats `allow`. This is the payoff: agents can run with `Bash`
and `Write` denied or omitted, and only `mcp__flux__*` allowed — constraining a
forked agent to messaging and forking only.

## Codex binding (spec §6)

`./install.sh mcp codex` writes both `[mcp_servers.flux_comms]` and
`[mcp_servers.flux_orchestrator]`. Codex has no per-agent MCP gating at the host
level, so forked Codex agents are bound to the right server by `afork` injecting
the server config (`-c` override) at fork time — a parked follow-up (see
`todo/flux-mcp.md`). The server runs **outside** Codex's command sandbox, so it
works under `--sandbox read-only` while the agent's shell is write-blocked.
