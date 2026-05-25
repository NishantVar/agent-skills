"""Send orchestration: self check -> resolve -> dispatch -> return JSON.

The two non-trivial branches:

  * `kind="unknown"` writes a fresh spawn payload to /tmp under O_EXCL
    0600 and returns a `peer_unknown` handoff with `payload_file` and
    `handoff_skill="tfork"`. The CALLING AGENT invokes tfork — this
    module never shells out to tfork.

  * `kind="stale"` and `kind=live, canonical=None` (tab-first-contact)
    both send a bootstrap into the live peer. The stale variant uses
    `manifest.name` as `suggested_name` so the peer keeps its prior
    identity on re-registration; the tab-first-contact variant uses the
    addressed string because we have no manifest to draw from.
"""

from __future__ import annotations

from . import bootstrap as _bootstrap
from . import errors, registry, resolve, surface, transport


def _success(addressed: str, canonical: str | None, surf: str,
             resolved_by: str, peer_status: str, kind: str,
             one_way: bool = False) -> dict:
    return {
        "ok": True,
        "peer": addressed,
        "canonical_name": canonical,
        "surface": surf,
        "resolved_by": resolved_by,
        "peer_status": peer_status,
        "kind": kind,
        "one_way": one_way,
    }


def _frame(me_name: str, body: str, one_way: bool) -> str:
    """`[from: X] body` or `[from: X | one-way] body`. The pipe-form
    marker is part of the wire contract — receivers read it inline to
    know no reply is expected. Slash commands are passed verbatim by the
    caller and never reach this helper."""
    tag = f"{me_name} | one-way" if one_way else me_name
    return f"[from: {tag}] {body}"


def _resolved_by(source: str | None) -> str:
    return {
        "name": "manifest_name",
        "tab_with_manifest": "tab_title_to_manifest",
        "tab_first_contact": "tab_title_first_contact",
    }.get(source or "", source or "")


def _default_self_name(my_surface: str) -> str:
    """`agent_<surface_num>` from `surface:<num>`. Surface IDs are unique
    within a cmux instance, so this default is collision-free by
    construction and stable for the agent's lifetime."""
    suffix = my_surface.split(":", 1)[-1] if ":" in my_surface else my_surface
    return f"agent_{suffix}"


def _ensure_self(my_surface: str | None, my_name: str | None,
                 fallback_suggested: str | None,
                 live_set: set[str],
                 rerun_argv: list[str]) -> tuple[dict | None, dict | None]:
    """Returns (self_manifest, handoff). Exactly one is non-None on
    error paths; both populated on success when self was just
    registered.

    Auto-derives `agent_<surface_num>` when neither --my-name nor an
    inline-bootstrap suggested_name was supplied. Self-naming should
    never bounce a decision back to the user — peer routing keys are
    plumbing, not a thing the human needs to pick.
    """
    if my_surface is None:
        return None, errors.not_in_cmux()

    existing = registry.get_self(my_surface)
    if existing is not None:
        # Already registered: --my-name on a subsequent call is a no-op.
        # Renaming mid-session breaks peers that route by the prior name.
        return existing, None

    chosen = my_name or fallback_suggested or _default_self_name(my_surface)

    m, err = registry.register(chosen, my_surface, live_set)
    if err:
        kind = err["kind"]
        if kind == "bad_name_format":
            return None, errors.bad_name_format(chosen)
        if kind == "name_collision":
            return None, errors.name_collision(chosen, err["holder_surface"])
        if kind == "name_collision_stale":
            return None, errors.name_collision_stale(
                chosen, err["holder_surface"])
        if kind == "not_in_cmux":
            return None, errors.not_in_cmux()
        return None, errors.info_needed(["self_name"], rerun_argv)
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
            peer_name=me["name"],
            peer_surface=me["surface_ref"],
            suggested_name=peer,
            first_message=body,
            one_way=one_way,
        )
        payload_file = _bootstrap.write_spawn_payload(peer, payload_text)
        return errors.peer_unknown(peer, payload_file, rerun_argv)

    by_surface = {m.get("surface_ref"): m for m in manifests}
    m = by_surface.get(peer_surface)
    canonical = m.get("name") if m else None
    is_stale = bool(m) and m.get("status") == "stale"

    if transport.is_command(body.strip()):
        text = body.strip()
    else:
        text = _frame(me["name"], body, one_way)
    transport.send_buffer(peer_surface, s.get("workspace_ref"), text)

    return _success(
        addressed=peer,
        canonical=canonical,
        surf=peer_surface,
        resolved_by="explicit_surface",
        peer_status=("stale" if is_stale else "live"),
        kind="message",
        one_way=one_way,
    )


def send(peer: str | None, body: str, my_name: str | None,
         fallback_self_name: str | None,
         rerun_argv: list[str],
         peer_surface: str | None = None,
         bootstrap_suggested_name: str | None = None,
         one_way: bool = False) -> dict:
    """Orchestrator. `peer_surface` skips name/tab resolution and routes
    directly — used when the caller already knows the peer's surface
    (e.g. from an inline [p2p-bootstrap] block). `bootstrap_suggested_name`
    takes registration precedence over the scrollback-derived
    `fallback_self_name`. `one_way=True` marks the message as
    fire-and-forget: receivers see `[from: X | one-way]` and (for first
    contact) a bootstrap that omits the reply request."""
    if not body.strip():
        return errors.empty_message()
    if not peer:
        return errors.info_needed(["peer"], rerun_argv)

    my_surf = surface.my_surface()
    tree = surface.cmux_tree()
    live = surface.live_surfaces(tree)
    surfaces = surface.surface_index(tree)

    # Registration precedence: explicit --my-name beats the bootstrap's
    # suggested name, which beats whatever the scrollback fallback found.
    chosen_self = my_name or bootstrap_suggested_name or fallback_self_name
    me, handoff = _ensure_self(my_surf, chosen_self, None,
                               live, rerun_argv)
    if handoff is not None:
        return handoff
    assert me is not None

    manifests = registry.all_manifests(live)

    if peer_surface:
        return _send_to_explicit_surface(
            peer=peer, body=body, me=me,
            peer_surface=peer_surface, surfaces=surfaces,
            manifests=manifests, rerun_argv=rerun_argv,
            one_way=one_way)

    r = resolve.resolve_peer(peer, manifests, surfaces)

    if r.kind == "ambiguous":
        return errors.peer_ambiguous(peer, r.candidates)

    if r.kind == "unknown":
        payload_text = _bootstrap.build_spawn_bootstrap(
            peer_name=me["name"],
            peer_surface=me["surface_ref"],
            suggested_name=peer,
            first_message=body,
            one_way=one_way,
        )
        payload_file = _bootstrap.write_spawn_payload(peer, payload_text)
        return errors.peer_unknown(peer, payload_file, rerun_argv)

    assert r.surface_ref is not None
    addressed_string = peer
    is_bootstrap = (r.kind == "stale"
                    or (r.kind == "live" and r.canonical_name is None))

    if is_bootstrap:
        suggested = (r.canonical_name
                     if r.kind == "stale" else addressed_string)
        text = _bootstrap.build_bootstrap(
            peer_name=me["name"],
            peer_surface=me["surface_ref"],
            suggested_name=suggested,
            first_message=body,
            one_way=one_way,
        )
        transport.send_buffer(r.surface_ref, r.workspace_ref, text)
        kind_out = "bootstrap"
    else:
        if transport.is_command(body.strip()):
            text = body.strip()
        else:
            text = _frame(me["name"], body, one_way)
        transport.send_buffer(r.surface_ref, r.workspace_ref, text)
        kind_out = "message"

    return _success(
        addressed=addressed_string,
        canonical=r.canonical_name,
        surf=r.surface_ref,
        resolved_by=_resolved_by(r.source),
        peer_status=("stale" if r.kind == "stale" else "live"),
        kind=kind_out,
        one_way=one_way,
    )
