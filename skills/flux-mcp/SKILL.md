---
name: flux-mcp
description: >-
  Stdio MCP server that wraps the p2p, afork, and tfork skill binaries as typed
  tools so Flux agents can message and fork peers with Bash and Write disabled.
  Not invoked via the Skill tool — wired into a host as an MCP server.
---

## What it is

`flux-mcp` is a **gateway MCP server**, not a Skill-tool skill. Hosts (Claude Code, Codex) spawn it per session over stdio. It subprocesses the existing `p2p`, `afork`, and `tfork` skill binaries and returns their JSON output verbatim. No auto-chaining, no business logic — the calling agent decides what to do with each response.

## Invocation

```
python3 <skill-dir>/flux_mcp.py --scope {comms|orchestrator}
```

Stdlib-only (Python 3.x standard library); no `mcp` package or third-party dependencies needed.

## Tools and scopes

| Scope | Tools exposed | Intended for |
|---|---|---|
| `comms` | `p2p` | Every agent (default) |
| `orchestrator` | `p2p`, `afork`, `tfork` | Leads and producers |

For per-tool argument semantics, read each wrapped skill's own `SKILL.md` (`skills/p2p`, `skills/afork`, `skills/tfork`) — do not duplicate them here. Quick reference for required args:

- **p2p** — `message` (string); usually also `peer` (string surface or agent name).
- **afork** — `runtime` (string, e.g. `claude`, `codex`).
- **tfork** — `command` (string).

## Boundary rule (spec §8)

The server **never auto-chains**. It returns each binary's JSON verbatim, including handoff objects (e.g. p2p's `peer_not_found`, afork's `ready_to_fork`). The calling agent reads the response and decides the next call. This mirrors the skills' own inter-skill boundary rule — skills hand off, they do not chain.

## Identity and surface resolution (spec §5)

On each tool call the server resolves the caller's cmux surface via `p2plib/surface.py:my_surface()` and injects it into `AGENT_MSG_SURFACE_ID` and `TFORK_SURFACE_ID` for the wrapped subprocess call. This ensures a forked agent with a stale `CMUX_SURFACE_ID` in its environment still routes correctly.

**Daemonized-host fallback (spec §5):** if a host daemonizes or double-forks the server (reparenting the process to pid 1), the PPID chain breaks and the controlling-tty walk cannot resolve the surface. In that case set `AGENT_MSG_SURFACE_ID` at fork time from tfork's creation-time session ref. This path has not been observed on Claude Code or Codex.

## Claude Code wiring (spec §6/§7)

Add an `mcpServers` entry to `.claude/settings.json` (project) or `~/.claude/settings.json` (user):

```json
{
  "mcpServers": {
    "flux": {
      "type": "stdio",
      "command": "python3",
      "args": ["/Users/<you>/.claude/skills/flux-mcp/flux_mcp.py", "--scope", "orchestrator"]
    }
  }
}
```

Use an **absolute** path — `args` are passed to `python3` literally and are not tilde-expanded.

**Per-agent restriction** via agent frontmatter `tools: mcp__flux__p2p` and/or `permissions.deny`. Claude Code has true per-agent MCP gating; `deny` beats `allow`. This is the payoff: agents can run with `Bash` and `Write` denied or omitted, and only `mcp__flux__*` allowed — constraining what a forked agent can do to messaging and forking only.

## Codex wiring (spec §6)

Add entries to `~/.codex/config.toml`:

```toml
[mcp_servers.flux_comms]
command = "python3"
args = ["/path/to/flux_mcp.py", "--scope", "comms"]

[mcp_servers.flux_orchestrator]
command = "python3"
args = ["/path/to/flux_mcp.py", "--scope", "orchestrator"]
```

Codex has no per-agent MCP gating at the host level, so forked Codex agents are bound to the right server by `afork` injecting the server config (`-c` override) at fork time. This is a parked follow-up (see `todo/flux-mcp.md`). The server runs **outside** Codex's command sandbox, so it works under `--sandbox read-only` while the agent's shell is write-blocked.

## Runtime pinning (spec §11)

The server is stdlib-only by design (no MCP SDK). Pin the interpreter in the host config to a specific Python 3.x to avoid breakage from system upgrades.
