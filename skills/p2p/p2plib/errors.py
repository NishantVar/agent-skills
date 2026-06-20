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


def peer_not_found(peer: str, candidates: list[dict] | None = None,
                   caller_workspace_ref: str | None = None,
                   rerun_argv: list[str] | None = None) -> dict:
    """No live agent holds the addressed title in scope. p2p NEVER
    spawns and never writes a spawn payload — it only reports the miss
    and (when other registered agents are live in scope) lists them so
    the caller can correct a misnamed --peer.

    Two shapes share this code:
      (a) ``candidates`` non-empty — registered agents are live in
          scope under different titles. The addressed title was almost
          certainly a misname; spawning would duplicate a real agent.
          The retry is mechanical (rerun --peer / --peer-surface) →
          action_required=pick_candidate, retryable=True.
      (b) ``candidates`` empty — no registered agent is reachable under
          any title in scope. There is no in-p2p retry; if a peer is
          wanted the caller spawns one itself via tfork / afork and
          sends again. action_required=spawn_externally.
    """
    candidates = candidates or []
    rerun_argv = rerun_argv or []
    scope = caller_workspace_ref or "scope"
    if candidates:
        human = (
            f"No live agent titled {peer!r} in {scope}, but "
            f"{len(candidates)} other registered agent(s) are live "
            f"there. {peer!r} was likely a misname."
        )
        instruction = (
            "Did you mean one of the listed candidates? Rerun with "
            "--peer <candidates[i].title> (or --peer-surface "
            "<candidates[i].ref> to route by surface directly). p2p "
            "does NOT spawn agents — do not start a new agent just "
            "because the title missed; that would duplicate a live "
            "peer. If none of the candidates is the intended peer and "
            "you genuinely need a NEW one, spawn it yourself via the "
            "tfork or afork skill (give it a --title) and then send to "
            "that title."
        )
        action = "pick_candidate"
    else:
        human = (
            f"No live agent titled {peer!r} in {scope}."
        )
        instruction = (
            "p2p does NOT spawn agents. If you want a peer here, spawn "
            "one yourself via the tfork or afork skill (give it a "
            "--title), then send to that title. Do not retry this "
            "command verbatim — there is no agent to deliver to yet."
        )
        action = "spawn_externally"
    return _base(
        "peer_not_found",
        human,
        instruction,
        action=action,
        retryable=True,
        rerun_argv=rerun_argv,
        candidates=candidates,
    )


def _drop_flag(argv: list[str], flag: str) -> list[str]:
    """Return argv with `flag` and its value removed. Used so a
    mismatch handoff's rerun_argv replays a CORRECTED command rather
    than the stale one that just failed."""
    out: list[str] = []
    skip = False
    for tok in argv:
        if skip:
            skip = False
            continue
        if tok == flag:
            skip = True
            continue
        out.append(tok)
    return out


def peer_surface_mismatch(peer: str, peer_surface: str,
                          current_title: str,
                          rerun_argv: list[str] | None = None) -> dict:
    """--peer-surface is an ADDRESS; --peer is an IDENTITY assertion.
    The surface ref is live but now holds a different title than the
    caller addressed — the ref is almost certainly stale (a bootstrap
    peer_surface carried over from an older message, or a tab whose
    occupant changed in a multi-producer setup). Delivering anyway
    would silently misroute to the wrong agent while reporting success,
    so p2p bounces instead.

    The rerun_argv strips --peer-surface so the mechanical replay
    re-resolves by title and any explicit workspace/window scope rather
    than re-trusting the same stale ref."""
    rerun_argv = rerun_argv or []
    return _base(
        "peer_surface_mismatch",
        f"--peer-surface {peer_surface} is live but holds title "
        f"{current_title!r}, not the addressed {peer!r}. The surface "
        "ref is likely stale (a bootstrap peer_surface from an older "
        "message, or the tab's occupant changed).",
        "Do not trust the stale surface. Rerun WITHOUT --peer-surface, "
        "with --peer <title> alone, to re-resolve by title; add "
        "--workspace <ref> and/or --window <ref> if the peer is outside "
        "your default scope. If you actually meant the agent now at "
        "that surface, address it by its real current title instead.",
        action="reresolve_by_title",
        retryable=True,
        rerun_argv=_drop_flag(rerun_argv, "--peer-surface"),
        peer_surface=peer_surface,
        current_title=current_title,
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


def window_unknown(requested: str,
                   rerun_argv: list[str] | None = None) -> dict:
    """``--window <value>`` did not resolve to a live cmux window."""
    return _base(
        "window_unknown",
        f"No cmux window matched {requested!r}.",
        "Do not retry verbatim. Pick a valid window ref, UUID, or "
        "index (see `cmux list-windows`) and rerun with --window "
        "<value>, drop --window to use the default scope, or pass "
        "--window all for global window scope.",
        action="pick_window",
        retryable=True,
        rerun_argv=rerun_argv or [],
        requested=requested,
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
        "to route by surface directly, or with --window <ref> and/or "
        "--workspace <ref> to scope the title match. Bare "
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
        "before resending sensitive content. If the rename is a role "
        "change and no live tab now fits, p2p does not spawn — start a "
        "fresh peer yourself via tfork / afork if you need one.",
        action="confirm_rename",
        retryable=True,
        rerun_argv=rerun_argv,
        candidates=candidates,
    )
