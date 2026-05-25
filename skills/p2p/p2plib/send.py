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
             resolved_by: str, peer_status: str, kind: str) -> dict:
    return {
        "ok": True,
        "peer": addressed,
        "canonical_name": canonical,
        "surface": surf,
        "resolved_by": resolved_by,
        "peer_status": peer_status,
        "kind": kind,
    }


def _resolved_by(source: str | None) -> str:
    return {
        "name": "manifest_name",
        "tab_with_manifest": "tab_title_to_manifest",
        "tab_first_contact": "tab_title_first_contact",
    }.get(source or "", source or "")


def _ensure_self(my_surface: str | None, my_name: str | None,
                 fallback_suggested: str | None,
                 live_set: set[str],
                 rerun_argv: list[str]) -> tuple[dict | None, dict | None]:
    """Returns (self_manifest, handoff). Exactly one is non-None on
    error paths; both populated on success when self was just
    registered.

    `fallback_suggested` is the bootstrap-derived suggested_name when
    --my-name wasn't supplied and self isn't registered.
    """
    if my_surface is None:
        return None, errors.not_in_cmux()

    existing = registry.get_self(my_surface)
    if existing is not None:
        # Already registered: --my-name on a subsequent call is a no-op.
        # Renaming mid-session breaks peers that route by the prior name.
        return existing, None

    chosen = my_name or fallback_suggested
    if not chosen:
        return None, errors.info_needed(["self_name"], rerun_argv)

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


def send(peer: str, body: str, my_name: str | None,
         fallback_self_name: str | None,
         rerun_argv: list[str]) -> dict:
    if not body.strip():
        return errors.empty_message()

    my_surf = surface.my_surface()
    tree = surface.cmux_tree()
    live = surface.live_surfaces(tree)
    surfaces = surface.surface_index(tree)

    me, handoff = _ensure_self(my_surf, my_name, fallback_self_name,
                               live, rerun_argv)
    if handoff is not None:
        return handoff
    assert me is not None

    manifests = registry.all_manifests(live)
    r = resolve.resolve_peer(peer, manifests, surfaces)

    if r.kind == "ambiguous":
        return errors.peer_ambiguous(peer, r.candidates)

    if r.kind == "unknown":
        payload_text = _bootstrap.build_spawn_bootstrap(
            peer_name=me["name"],
            peer_surface=me["surface_ref"],
            suggested_name=peer,
            first_message=body,
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
        )
        transport.send_buffer(r.surface_ref, r.workspace_ref, text)
        kind_out = "bootstrap"
    else:
        if transport.is_command(body.strip()):
            text = body.strip()
        else:
            text = f"[from: {me['name']}] {body}"
        transport.send_buffer(r.surface_ref, r.workspace_ref, text)
        kind_out = "message"

    return _success(
        addressed=addressed_string,
        canonical=r.canonical_name,
        surf=r.surface_ref,
        resolved_by=_resolved_by(r.source),
        peer_status=("stale" if r.kind == "stale" else "live"),
        kind=kind_out,
    )
