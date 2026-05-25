"""Handoff JSON contract.

Every non-success path returns a JSON object with a stable shape so the
calling agent can act mechanically without parsing prose. See SKILL.md
for the field reference; the helpers here are the only places that
construct that shape.
"""

from __future__ import annotations

from typing import Any


def _base(code: str, human: str, instruction: str, *,
          action: str = "none", retryable: bool = False,
          handoff_skill: str | None = None,
          rerun_argv: list[str] | None = None,
          suggested_next_command: str | None = None,
          **extra: Any) -> dict:
    out: dict[str, Any] = {
        "ok": False,
        "code": code,
        "human_message": human,
        "agent_instruction": instruction,
        "action_required": action,
        "handoff_skill": handoff_skill,
        "rerun_argv": rerun_argv or [],
        "retryable": retryable,
    }
    if suggested_next_command:
        out["suggested_next_command"] = suggested_next_command
    out.update(extra)
    return out


def not_in_cmux() -> dict:
    return _base(
        "not_in_cmux",
        "This agent could not resolve its own cmux surface.",
        "Set AGENT_MSG_SURFACE_ID=surface:<N> in the environment and "
        "rerun. The agent is likely not running inside a cmux pane.",
        action="none",
    )


def empty_message() -> dict:
    return _base(
        "empty_message",
        "The supplied message body is empty.",
        "Write a non-empty message body to the file and rerun the same "
        "command.",
        action="none",
    )


def bad_name_format(name: str) -> dict:
    return _base(
        "bad_name_format",
        f"Name {name!r} is not lowercase snake_case.",
        "Pick a name matching [a-z][a-z0-9_]* and rerun with the new "
        "--my-name (or --name for register).",
        action="pick_self_name",
    )


def name_collision(name: str, holder_surface: str) -> dict:
    return _base(
        "name_collision",
        f"Name {name!r} is already held by a live agent at "
        f"{holder_surface}.",
        "Pick a different name and rerun.",
        action="pick_self_name",
        holder_surface=holder_surface,
    )


def name_collision_stale(name: str, holder_surface: str) -> dict:
    return _base(
        "name_collision_stale",
        f"Name {name!r} is held by a stale agent at {holder_surface}; "
        "the surface is alive but the agent has been idle past the "
        "TTL.",
        "Pick a different name to avoid claim ambiguity, or address the "
        "stale agent and have it re-touch its manifest first.",
        action="pick_self_name",
        holder_surface=holder_surface,
    )


def info_needed(missing: list[str], rerun_argv: list[str]) -> dict:
    return _base(
        "info_needed",
        "Missing required input: " + ", ".join(missing),
        "Supply the missing flags and rerun the same subcommand.",
        action="register" if "self_name" in missing else "none",
        rerun_argv=rerun_argv,
        missing=missing,
    )


def peer_unknown(peer: str, payload_file: str, rerun_argv: list[str]) -> dict:
    return _base(
        "peer_unknown",
        f"Peer {peer!r} is not running in cmux. A spawn-bootstrap "
        f"payload has been written to {payload_file}.",
        f"Invoke the tfork skill to spawn an agent that reads "
        f"{payload_file} as its first user-turn prompt. The new agent "
        "will register itself, parse the bootstrap, and reply. p2p does "
        "not name a specific tfork flag — pass the payload via whatever "
        "delayed-input mechanism that skill currently exposes.",
        action="spawn_peer",
        handoff_skill="tfork",
        retryable=True,
        payload_file=payload_file,
        rerun_argv=rerun_argv,
    )


def peer_ambiguous(peer: str, candidates: list[dict]) -> dict:
    return _base(
        "peer_ambiguous",
        f"Tab title {peer!r} matches more than one surface across "
        "workspaces.",
        "Re-address the peer using its registered manifest name "
        "(which is unique), or rerun with --peer <original-or-label> "
        "--peer-surface <candidates[i].ref> to route by surface "
        "directly. Bare `surface:N` strings are NOT accepted as --peer.",
        action="none",
        candidates=candidates,
    )
