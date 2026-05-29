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
    """Terminal: the calling process cannot mutate its own environment
    to recover. The prose is honest about that — no mechanical retry
    is possible from where the caller stands, so action_required=none
    and retryable=false."""
    return _base(
        "not_in_cmux",
        "This agent could not resolve its own cmux surface.",
        "Terminal — do not retry this command as-is. The calling "
        "process cannot fix its own environment. To use p2p, relaunch "
        "this agent inside a cmux pane (the cmux wrapper sets "
        "AGENT_MSG_SURFACE_ID for child processes), or have the "
        "spawner export AGENT_MSG_SURFACE_ID=surface:<N> before "
        "starting the agent.",
        action="none",
        retryable=False,
    )


def empty_message(rerun_argv: list[str] | None = None) -> dict:
    """Body was empty after stripping. The prose instruction names a
    mechanical retry (rewrite the file, rerun), so the envelope
    reflects that — action_required=rewrite_message, retryable=True,
    rerun_argv populated."""
    return _base(
        "empty_message",
        "The supplied message body is empty.",
        "Write a non-empty message body to the file and rerun the same "
        "command.",
        action="rewrite_message",
        retryable=True,
        rerun_argv=rerun_argv or [],
    )


def title_collision(title: str, workspace_ref: str,
                    holder_surface: str,
                    rerun_argv: list[str] | None = None) -> dict:
    """Another live agent in the workspace already holds `title`.
    Mechanical retry: pick a different --my-title and rerun. Envelope
    matches: retryable=True with rerun_argv populated. The agent must
    pick a fresh title from its own role context (do NOT bounce to the
    human) — see also info_needed(self_title) instructional wording."""
    return _base(
        "title_collision",
        f"Tab title {title!r} is already held by another live tab at "
        f"{holder_surface} in workspace {workspace_ref}.",
        "Pick a different --my-title (snake_case, role-reflective — "
        "choose from your own role context, do not ask the human) and "
        "rerun. Titles must be unique within a workspace; routing is "
        "by (workspace, title).",
        action="pick_self_title",
        retryable=True,
        rerun_argv=rerun_argv or [],
        holder_surface=holder_surface,
        workspace_ref=workspace_ref,
    )


def info_needed(missing: list[str], rerun_argv: list[str]) -> dict:
    """Both branches describe a mechanical retry. Envelope reflects
    that — retryable=True, rerun_argv carried. action_required is
    branch-specific so a caller reading only envelope fields can route
    on action alone."""
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
        action = "provide_input"
    return _base(
        "info_needed",
        "Missing required input: " + ", ".join(missing),
        instruction,
        action=action,
        retryable=True,
        rerun_argv=rerun_argv,
        missing=missing,
    )


def peer_unknown(peer: str, payload_file: str, rerun_argv: list[str],
                 workspace: str | None = None) -> dict:
    """``workspace`` is the original ``--workspace <value>`` the caller
    passed (title preferred over ref for stability). When set, the
    bootstrap-payload tfork handoff also asks the caller to pass
    ``--workspace <value>`` to tfork so the spawned peer lands in the
    right workspace. None means no workspace pinning — tfork spawns
    next to the caller as it always has."""
    if workspace:
        ws_clause = (
            f" Also pass --workspace {workspace} to tfork so the spawned "
            f"peer lands in the workspace the original send targeted."
        )
    else:
        ws_clause = ""
    return _base(
        "peer_unknown",
        f"Peer {peer!r} is not running in cmux. A spawn-bootstrap "
        f"payload has been written to {payload_file}.",
        f"Invoke the tfork skill to spawn an agent that reads "
        f"{payload_file} as its first user-turn prompt. The new agent "
        "will register itself, parse the bootstrap, and reply. p2p does "
        "not name a specific tfork flag — pass the payload via whatever "
        "delayed-input mechanism that skill currently exposes."
        + ws_clause,
        action="spawn_peer",
        handoff_skill="tfork",
        retryable=True,
        payload_file=payload_file,
        workspace=workspace,
        rerun_argv=rerun_argv,
    )


def workspace_unknown(requested: str,
                      rerun_argv: list[str] | None = None) -> dict:
    """``--workspace <value>`` did not resolve to a live workspace.
    Either ``value`` was a ref (workspace:N or UUID) that no longer
    exists, or it was a title with zero matches. p2p never silently
    falls back to the caller's workspace — that would mask a typo."""
    return _base(
        "workspace_unknown",
        f"No cmux workspace matched {requested!r}.",
        "Do not retry verbatim. Pick a valid workspace title or ref "
        "(see `cmux list-workspaces`) and rerun with --workspace "
        "<value>, drop --workspace to scope to your own workspace, or "
        "pass --workspace all for global scope.",
        action="pick_workspace",
        retryable=True,
        rerun_argv=rerun_argv or [],
        requested=requested,
    )


def workspace_ambiguous(requested: str, candidates: list[dict],
                        rerun_argv: list[str] | None = None) -> dict:
    """``--workspace <title>`` matched two or more live workspaces.
    ``candidates`` is a list of ``{ref, title}``."""
    return _base(
        "workspace_ambiguous",
        f"Workspace title {requested!r} matches more than one live "
        f"workspace ({len(candidates)} candidates).",
        "Do not retry verbatim. Pick one of the listed refs and rerun "
        "with --workspace <ref>.",
        action="pick_candidate",
        retryable=True,
        rerun_argv=rerun_argv or [],
        candidates=candidates,
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


def peer_renamed(peer: str, candidates: list[dict],
                 caller_workspace_ref: str | None = None,
                 rerun_argv: list[str] | None = None) -> dict:
    """No live tab in scope matches `peer`, but one or more live
    surfaces in scope have `peer` in their `former_titles` — the tab
    was renamed (typically the human clicking the title in cmux).

    Each candidate carries `current_title` (the new tab title) and
    `former_title` (the matched prior title — what the caller actually
    addressed). Live current-title matches always win at the resolver
    layer; this handoff only fires when no current match exists.

    Envelope mirrors peer_ambiguous: `action_required=confirm_rename`,
    `retryable=True`, `rerun_argv` populated. The retry is mechanical
    (pick a candidate, rerun with current_title or --peer-surface) so
    the envelope says so — a caller reading only envelope fields must
    reach the same decision as one parsing the prose.
    """
    rerun_argv = rerun_argv or []
    if len(candidates) == 1:
        c = candidates[0]
        ws_ref = c.get("workspace_ref") or ""
        human = (
            f"No live tab titled {peer!r} in your workspace "
            f"({caller_workspace_ref or ws_ref}). Surface previously "
            f"registered under {peer!r} is still live at {c.get('ref')}, "
            f"now titled {c.get('current_title')!r}."
        )
    else:
        human = (
            f"No live tab titled {peer!r}; {len(candidates)} live "
            f"surfaces previously held that title and have since been "
            "renamed."
        )
    return _base(
        "peer_renamed",
        human,
        "If the same agent is the intended target, rerun with --peer "
        "<candidates[i].current_title> or --peer-surface "
        "<candidates[i].ref>. The rename may signal a role change — "
        "verify intent (read recent scrollback or ask the peer) "
        "before resending sensitive content. Otherwise treat as "
        "peer_unknown and spawn via tfork.",
        action="confirm_rename",
        retryable=True,
        rerun_argv=rerun_argv,
        candidates=candidates,
    )
