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


def title_collision(title: str, workspace_ref: str,
                    holder_surface: str) -> dict:
    return _base(
        "title_collision",
        f"Tab title {title!r} is already held by another live tab at "
        f"{holder_surface} in workspace {workspace_ref}.",
        "Pick a different --my-title and rerun. Titles must be unique "
        "within a workspace; routing is by (workspace, title).",
        action="pick_self_title",
        holder_surface=holder_surface,
        workspace_ref=workspace_ref,
    )


def info_needed(missing: list[str], rerun_argv: list[str]) -> dict:
    needs_self_title = "self_title" in missing
    if needs_self_title:
        # Target the calling AGENT, not the human. The agent has role
        # context (what it's doing, who spawned it, the conversation) and
        # is entirely capable of choosing a meaningful title like
        # `qa_lead` or `reviewer`. `agent_<surface_num>` is opaque
        # garbage for every downstream reader; do not paper over the
        # question with a meaningless default.
        instruction = (
            "Pick a stable snake_case title that reflects your role "
            "(e.g., `qa_lead`, `reviewer`, `builder`, `p2p_tester`) "
            "and rerun with --my-title <t>. Do NOT ask the human — "
            "choose yourself from your own role context. Once chosen, "
            "the title is sticky for this agent's lifetime."
        )
        action = "pick_self_title"
    else:
        instruction = ("Supply the missing flags and rerun the same "
                       "subcommand.")
        action = "none"
    return _base(
        "info_needed",
        "Missing required input: " + ", ".join(missing),
        instruction,
        action=action,
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


def peer_ambiguous(peer: str, candidates: list[dict],
                   caller_workspace_ref: str | None = None,
                   rerun_argv: list[str] | None = None) -> dict:
    """Two shapes of ambiguity collapse into this one code:
      (a) The title doesn't exist in the caller's workspace but does
          exist elsewhere — most commonly len(candidates)==1 in another
          workspace. The default-scope policy treats this as ambiguous
          so the caller must opt in via --workspace.
      (b) The title matches more than one live surface (whether all
          elsewhere or split). The wording branches so single-elsewhere
          gets a clearer message; the retry path is the same.

    Envelope is `action_required=pick_candidate`, `retryable=True`. The
    `agent_instruction` describes a mechanical retry (pick a candidate,
    add --peer-surface or --workspace), so the envelope must say so —
    leaving action=none / retryable=false would make a caller that
    reads only the envelope (ignoring prose) treat this as terminal.
    """
    rerun_argv = rerun_argv or []
    single_elsewhere = (
        len(candidates) == 1
        and caller_workspace_ref is not None
        and candidates[0].get("workspace_ref") != caller_workspace_ref
    )
    if single_elsewhere:
        c = candidates[0]
        ws_title = c.get("workspace_title") or ""
        ws_ref = c.get("workspace_ref") or ""
        human = (
            f"Tab title {peer!r} is not in your workspace "
            f"({caller_workspace_ref}). One match in another workspace: "
            f"{ws_title} ({ws_ref}) at {c.get('ref')}."
        )
    else:
        human = (
            f"Tab title {peer!r} matches more than one live surface "
            "(across workspaces, or within one if cmux allowed "
            "duplicates)."
        )
    return _base(
        "peer_ambiguous",
        human,
        "Rerun with --peer <title> --peer-surface <candidates[i].ref> "
        "to route by surface directly, or with --workspace <ref> to "
        "scope the title match to a specific workspace. Bare "
        "`surface:N` strings are NOT accepted as --peer.",
        action="pick_candidate",
        retryable=True,
        rerun_argv=rerun_argv,
        candidates=candidates,
    )
