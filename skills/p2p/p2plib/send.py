"""Send orchestration: self check -> resolve -> dispatch -> return JSON.

Single-identifier model: the cmux tab title is the routing key. There
is no manifest `name` field anymore — `title` IS the identity.

Self-naming precedence on first send (no existing manifest):
  1. --my-title (explicit caller choice; triggers tab rename + register)
  2. --bootstrap-suggested-title (from an inbound bootstrap)
  3. scrollback-derived fallback (from a [p2p-bootstrap] block in the
     agent's own scrollback when neither flag is given)
  4. current cmux tab title — but ONLY if it isn't a generic spawn
     default like "claude" / "codex" / empty. Generic titles trigger
     info_needed targeted at the CALLING AGENT to pick a meaningful
     name from its role context.

The non-trivial branches:
  * `kind="unknown"` writes a fresh spawn payload to /tmp under O_EXCL
    0600 and returns a `peer_unknown` handoff with `payload_file` and
    `handoff_skill="tfork"`. The CALLING AGENT invokes tfork — this
    module never shells out to tfork.
  * `kind="stale"` and `kind=live, title==addressed` both send a
    bootstrap into the live peer when the manifest is stale (so the
    peer can re-touch); otherwise a plain `[from: X]` message.
  * `kind="renamed"` returns a `peer_renamed` handoff carrying every
    candidate surface whose `former_titles` includes the addressed
    title. Caller picks whether the rename signals the same agent
    (retry against current_title / --peer-surface) or a role change
    (treat as unknown).
"""

from __future__ import annotations

from . import bootstrap as _bootstrap
from . import errors, registry, resolve, surface, transport


# Spawn-default titles that aren't meaningful identities. The agent
# must pick a real title; do not adopt these as the wire identity.
GENERIC_TITLES = frozenset({
    "", "claude", "claude-code", "codex", "gemini", "shell", "bash",
    "zsh",
})


def _success(addressed: str, title: str | None, surf: str,
             resolved_by: str, peer_status: str, kind: str,
             one_way: bool = False) -> dict:
    return {
        "ok": True,
        "peer": addressed,
        "title": title,
        "surface": surf,
        "resolved_by": resolved_by,
        "peer_status": peer_status,
        "kind": kind,
        "one_way": one_way,
    }


def _resolved_by(source: str | None) -> str:
    return source or ""


def _frame(me_title: str, body: str, one_way: bool) -> str:
    """`[from: X] body` or `[from: X | one-way] body`. The pipe-form
    marker is part of the wire contract — receivers read it inline to
    know no reply is expected. Slash commands are passed verbatim by
    the caller and never reach this helper."""
    tag = f"{me_title} | one-way" if one_way else me_title
    return f"[from: {tag}] {body}"


def _ensure_self(my_surface: str | None,
                 my_title: str | None,
                 bootstrap_suggested_title: str | None,
                 fallback_self_title: str | None,
                 live_set: set[str],
                 surfaces: dict[str, dict],
                 rerun_argv: list[str]) -> tuple[dict | None, dict | None]:
    """Returns (self_manifest, handoff). Exactly one is non-None.

    Precedence: existing manifest > --my-title > bootstrap-suggested >
    scrollback-fallback > current cmux title (if meaningful) >
    info_needed targeted at the calling agent.

    The current cmux tab title is adopted ONLY when it isn't a generic
    spawn default (`claude`, etc.). Generic titles never become the
    wire identity — they're opaque to peers reading `[from: ...]`.
    """
    if my_surface is None:
        return None, errors.not_in_cmux()

    existing = registry.get_self(my_surface)
    if existing is not None:
        # Already registered: --my-title on a subsequent call is a
        # no-op. Renaming mid-session breaks peers that route by the
        # prior title.
        return existing, None

    workspace_ref = (surfaces.get(my_surface) or {}).get("workspace_ref")
    current_title = (surfaces.get(my_surface) or {}).get("title", "")

    chosen = my_title or bootstrap_suggested_title or fallback_self_title
    if chosen is None:
        if current_title and current_title not in GENERIC_TITLES:
            chosen = current_title
        else:
            return None, errors.info_needed(["self_title"], rerun_argv)

    # Probe for collision BEFORE renaming so a title_collision handoff
    # doesn't leave the caller's cmux tab visibly renamed while the
    # manifest stays unregistered. The check inside register() is the
    # authoritative backstop; this probe just avoids the common
    # already-held case.
    if chosen != current_title:
        holder = registry.would_collide(chosen, my_surface, workspace_ref,
                                        live_set, surfaces)
        if holder is not None:
            return None, errors.title_collision(
                chosen, workspace_ref or "", holder,
                rerun_argv=rerun_argv)
        transport.rename_tab(my_surface, workspace_ref, chosen)
        # Reflect the rename in the in-memory snapshot so subsequent
        # sweeps (register-time AND the read-side sweep in `send`)
        # don't mis-interpret it as an external rename and rewrite the
        # manifest title back / push our chosen title onto former_titles.
        existing_surf = surfaces.get(my_surface)
        if existing_surf is not None:
            surfaces[my_surface] = {**existing_surf, "title": chosen}

    m, err = registry.register(chosen, my_surface, workspace_ref,
                               live_set, surfaces)
    if err:
        kind = err["kind"]
        if kind == "title_collision":
            return None, errors.title_collision(
                chosen, err["workspace_ref"], err["holder_surface"],
                rerun_argv=rerun_argv)
        if kind == "not_in_cmux":
            return None, errors.not_in_cmux()
        return None, errors.info_needed(["self_title"], rerun_argv)
    return m, None


def _send_to_explicit_surface(*, peer: str, body: str, me: dict,
                              peer_surface: str,
                              surfaces: dict[str, dict],
                              manifests: list[dict],
                              rerun_argv: list[str],
                              one_way: bool) -> dict:
    """Reply path: caller supplied --peer-surface (typically from an
    inline bootstrap). Skip resolution; route directly. Plain message
    framing — the peer already initiated contact, so no re-bootstrap."""
    s = surfaces.get(peer_surface)
    if s is None:
        # Surface no longer in cmux tree; fall back to spawn-bootstrap.
        payload_text = _bootstrap.build_spawn_bootstrap(
            peer_title=me["title"],
            peer_surface=me["surface_ref"],
            suggested_title=peer,
            first_message=body,
            one_way=one_way,
        )
        payload_file = _bootstrap.write_spawn_payload(peer, payload_text)
        return errors.peer_unknown(peer, payload_file, rerun_argv)

    by_surface = {m.get("surface_ref"): m for m in manifests}
    m = by_surface.get(peer_surface)
    title = m.get("title") if m else s.get("title", "")
    is_stale = bool(m) and m.get("status") == "stale"

    if transport.is_command(body.strip()):
        text = body.strip()
    else:
        text = _frame(me["title"], body, one_way)
    transport.send_buffer(peer_surface, s.get("workspace_ref"), text)

    return _success(
        addressed=peer,
        title=title,
        surf=peer_surface,
        resolved_by="explicit_surface",
        peer_status=("stale" if is_stale else "live"),
        kind="message",
        one_way=one_way,
    )


def send(peer: str | None, body: str,
         my_title: str | None,
         fallback_self_title: str | None,
         rerun_argv: list[str],
         peer_surface: str | None = None,
         bootstrap_suggested_title: str | None = None,
         scope_workspace_ref: str | None = None,
         one_way: bool = False) -> dict:
    """Orchestrator. `peer_surface` skips title resolution and routes
    directly — used when the caller already knows the peer's surface
    (e.g. from an inline [p2p-bootstrap] block).
    `bootstrap_suggested_title` takes registration precedence over the
    scrollback-derived `fallback_self_title`.
    `scope_workspace_ref` scopes title resolution to one workspace;
    when None, defaults to the caller's own workspace. Pass an
    explicit sentinel to widen scope — see cli.py."""
    if not body.strip():
        return errors.empty_message(rerun_argv=rerun_argv)
    if not peer:
        return errors.info_needed(["peer"], rerun_argv)

    my_surf = surface.my_surface()
    tree = surface.cmux_tree()
    live = surface.live_surfaces(tree)
    surfaces = surface.surface_index(tree)

    me, handoff = _ensure_self(
        my_surf, my_title, bootstrap_suggested_title,
        fallback_self_title, live, surfaces, rerun_argv)
    if handoff is not None:
        return handoff
    assert me is not None

    # Read-side enumeration also passes `surfaces=` so the in-place
    # rename promotion (manifest.title <- current cmux title, prior
    # title appended to former_titles) happens promptly. Without this,
    # peer_renamed would only fire after some other agent triggered a
    # register-time sweep on the renamed peer's workspace.
    manifests = registry.all_manifests(live, surfaces=surfaces)

    # Self may have been promoted by the sweep too (cmux tab renamed
    # externally between our last registration and this send).
    # _ensure_self short-circuits on the existing manifest without
    # checking against the current cmux title, so `me` can carry the
    # stale title. Refresh from the post-sweep set so framing uses
    # the current identity rather than emitting `[from: <old>]`.
    if my_surf:
        for m in manifests:
            if m.get("surface_ref") == my_surf:
                me = m
                break

    if peer_surface:
        return _send_to_explicit_surface(
            peer=peer, body=body, me=me,
            peer_surface=peer_surface, surfaces=surfaces,
            manifests=manifests, rerun_argv=rerun_argv,
            one_way=one_way)

    # Default scope: caller's own workspace. The caller can widen by
    # passing scope_workspace_ref explicitly (via --workspace at the
    # CLI). cli.py threads a sentinel value when --workspace=all is
    # requested; here we treat None as "use mine".
    scope = scope_workspace_ref
    if scope is None:
        scope = (surfaces.get(my_surf or "") or {}).get("workspace_ref")

    r = resolve.resolve_peer(peer, manifests, surfaces,
                             scope_workspace_ref=scope)

    if r.kind == "ambiguous":
        return errors.peer_ambiguous(peer, r.candidates,
                                     caller_workspace_ref=scope,
                                     rerun_argv=rerun_argv)

    if r.kind == "renamed":
        return errors.peer_renamed(peer, r.candidates,
                                   caller_workspace_ref=scope,
                                   rerun_argv=rerun_argv)

    if r.kind == "unknown":
        payload_text = _bootstrap.build_spawn_bootstrap(
            peer_title=me["title"],
            peer_surface=me["surface_ref"],
            suggested_title=peer,
            first_message=body,
            one_way=one_way,
        )
        payload_file = _bootstrap.write_spawn_payload(peer, payload_text)
        return errors.peer_unknown(peer, payload_file, rerun_argv)

    assert r.surface_ref is not None
    addressed_string = peer
    # Bootstrap when (a) the peer has a stale manifest (so it
    # re-touches itself) or (b) no manifest exists at all (first
    # contact — the peer doesn't know who we are or that p2p is in
    # play, so the bootstrap text invites it to register and reply).
    is_bootstrap = r.kind in ("stale", "live_first_contact")

    if is_bootstrap:
        text = _bootstrap.build_bootstrap(
            peer_title=me["title"],
            peer_surface=me["surface_ref"],
            suggested_title=r.title or addressed_string,
            first_message=body,
            one_way=one_way,
        )
        transport.send_buffer(r.surface_ref, r.workspace_ref, text)
        kind_out = "bootstrap"
    else:
        if transport.is_command(body.strip()):
            text = body.strip()
        else:
            text = _frame(me["title"], body, one_way)
        transport.send_buffer(r.surface_ref, r.workspace_ref, text)
        kind_out = "message"

    return _success(
        addressed=addressed_string,
        title=r.title,
        surf=r.surface_ref,
        resolved_by=_resolved_by(r.source),
        peer_status=("stale" if r.kind == "stale" else "live"),
        kind=kind_out,
        one_way=one_way,
    )
