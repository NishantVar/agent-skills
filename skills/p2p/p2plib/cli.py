"""argparse front door. `_touch_self` bumps `last_seen` at the top of
every invocation as a diagnostic heartbeat; routing does not depend
on it (a manifest-with-live-surface is always `live`)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import bootstrap, errors, registry, send, surface, transport


EXIT_OK = 0
EXIT_HANDOFF = 2  # ok:false in JSON
EXIT_SYSTEM = 1


def _print_json(obj: object) -> None:
    sys.stdout.write(json.dumps(obj, indent=2))
    sys.stdout.write("\n")


def _decorate_me(m: dict, surfaces: dict[str, dict]) -> dict:
    ref = m.get("surface_ref") or ""
    s = surfaces.get(ref, {})
    return {
        "title": m.get("title"),
        "surface_ref": ref,
        "workspace_ref": s.get("workspace_ref"),
        "workspace_title": s.get("workspace_title", ""),
    }


def _decorate_peer(m: dict, surfaces: dict[str, dict]) -> dict:
    out = _decorate_me(m, surfaces)
    out["last_seen"] = m.get("last_seen")
    return out


# ---------------- subcommands ----------------

def cmd_list(_args) -> int:
    """Human-debug only. NOT part of the agent-facing skill contract —
    SKILL.md teaches `send` as the single verb. This subcommand stays
    so a human can inspect registry state at the shell."""
    surf = surface.my_surface()
    tree = surface.cmux_tree()
    live = surface.live_surfaces(tree)
    surfaces = surface.surface_index(tree)
    manifests = registry.all_manifests(live, surfaces=surfaces)
    me = None
    peers = []
    for m in manifests:
        if m.get("surface_ref") == surf:
            me = _decorate_me(m, surfaces)
        else:
            peers.append(_decorate_peer(m, surfaces))
    _print_json({"me": me, "peers": peers})
    return EXIT_OK


def _read_body(args) -> str:
    if args.message_file:
        return Path(args.message_file).read_text()
    if args.message is not None:
        return args.message
    return ""


def _resolve_title_aliases(args) -> None:
    """One-release deprecation aliases. --my-name → --my-title and
    --bootstrap-suggested-name → --bootstrap-suggested-title. Emits a
    single-line warning to stderr so callers update."""
    if getattr(args, "my_name", None) and not args.my_title:
        print("warning: --my-name is deprecated; use --my-title",
              file=sys.stderr)
        args.my_title = args.my_name
    if (getattr(args, "bootstrap_suggested_name", None)
            and not args.bootstrap_suggested_title):
        print("warning: --bootstrap-suggested-name is deprecated; "
              "use --bootstrap-suggested-title", file=sys.stderr)
        args.bootstrap_suggested_title = args.bootstrap_suggested_name


def _build_rerun_argv(args) -> list[str]:
    """Reconstruct an argv that replays the same send. Every retryable
    handoff carries this so an envelope-only caller can rerun
    mechanically without re-deriving flags from the prose.

    BOTH --message and --message-file get preserved verbatim. SKILL.md
    teaches --message-file as the canonical path, but --message is
    still accepted by the CLI, so the rerun would otherwise drop the
    body source for inline-message callers and make `empty_message` /
    `title_collision` / `info_needed` non-replayable for them.
    """
    rerun: list[str] = ["agent_msg.py", "send"]
    if args.peer:
        rerun += ["--peer", args.peer]
    if args.peer_surface:
        rerun += ["--peer-surface", args.peer_surface]
    if args.my_title:
        rerun += ["--my-title", args.my_title]
    if args.bootstrap_suggested_title:
        rerun += ["--bootstrap-suggested-title",
                  args.bootstrap_suggested_title]
    if args.workspace:
        rerun += ["--workspace", args.workspace]
    if args.one_way:
        rerun += ["--one-way"]
    if args.message_file:
        rerun += ["--message-file", args.message_file]
    if args.message is not None:
        rerun += ["--message", args.message]
    return rerun


def cmd_send(args) -> int:
    _resolve_title_aliases(args)

    # --bootstrap-file fills defaults for --peer / --peer-surface /
    # --bootstrap-suggested-title when the agent has the bootstrap text
    # in a file rather than as individual flags.
    if args.bootstrap_file:
        text = Path(args.bootstrap_file).read_text()
        parsed = bootstrap.parse_bootstrap_text(text) or {}
        args.peer = args.peer or parsed.get("peer_title")
        args.peer_surface = args.peer_surface or parsed.get("peer_surface")
        args.bootstrap_suggested_title = (
            args.bootstrap_suggested_title
            or parsed.get("suggested_title"))

    body = _read_body(args)
    rerun = _build_rerun_argv(args)

    # Scrollback fallback only runs when neither --my-title nor
    # --bootstrap-suggested-title was supplied and the agent isn't
    # already registered. It's the deepest of three fallbacks.
    fallback_self_title = None
    if (not args.my_title and not args.bootstrap_suggested_title
            and registry.get_self(surface.my_surface()) is None):
        try:
            my_surf = surface.my_surface()
            if my_surf:
                tree = surface.cmux_tree()
                ws = surface.workspace_of(my_surf, tree)
                try:
                    text = transport.read_screen(my_surf, ws)
                except transport.TransportError:
                    text = ""
                parsed = (bootstrap.parse_bootstrap_text(text)
                          if text else None)
                if parsed:
                    fallback_self_title = (parsed.get("suggested_title")
                                           or None)
        except transport.TransportError:
            pass

    # --workspace handling: bare flag means scope to current workspace
    # (the default). --workspace all means global. --workspace <value>
    # accepts either a workspace_ref (workspace:N or UUID) or a title.
    # Titles are resolved against live workspaces; zero matches returns
    # workspace_unknown, multi-match returns workspace_ambiguous. The
    # original --workspace value (title preferred over ref) is preserved
    # for the peer_unknown spawn payload so tfork lands the new peer in
    # the right workspace.
    scope_workspace_ref: str | None
    workspace_for_spawn: str | None = None
    if args.workspace == "all":
        scope_workspace_ref = ""  # sentinel: global scope
    elif args.workspace:
        workspace_for_spawn = args.workspace
        if surface.is_workspace_ref(args.workspace):
            # Validate the ref points at a live workspace. Prefer the
            # title for the spawn payload so a downstream tfork lands
            # the new peer in the same workspace by name — but only if
            # the title is globally unique; otherwise keep the
            # unambiguous ref so tfork does not see workspace_ambiguous.
            ws_list = surface.list_workspaces()
            match = next((t for (r, t) in ws_list if r == args.workspace),
                         None)
            if match is None:
                _print_json(errors.workspace_unknown(args.workspace, rerun))
                return EXIT_HANDOFF
            scope_workspace_ref = args.workspace
            if match and sum(1 for (_, t) in ws_list if t == match) == 1:
                workspace_for_spawn = match
        else:
            ws_list = surface.list_workspaces()
            matches = [(r, t) for (r, t) in ws_list if t == args.workspace]
            if not matches:
                _print_json(errors.workspace_unknown(args.workspace, rerun))
                return EXIT_HANDOFF
            if len(matches) > 1:
                cands = [{"ref": r, "title": t} for (r, t) in matches]
                _print_json(errors.workspace_ambiguous(
                    args.workspace, cands, rerun))
                return EXIT_HANDOFF
            scope_workspace_ref = matches[0][0]
    else:
        scope_workspace_ref = None  # default: caller's own workspace

    try:
        result = send.send(
            peer=args.peer,
            body=body,
            my_title=args.my_title,
            fallback_self_title=fallback_self_title,
            rerun_argv=rerun,
            peer_surface=args.peer_surface,
            bootstrap_suggested_title=args.bootstrap_suggested_title,
            scope_workspace_ref=scope_workspace_ref,
            workspace_for_spawn=workspace_for_spawn,
            one_way=args.one_way,
        )
    except transport.TransportError as exc:
        _print_json({
            "ok": False, "code": "transport_failed",
            "human_message": f"cmux transport failed: {exc}",
            "agent_instruction": "Inspect cmux state and rerun.",
            "action_required": "none", "handoff_skill": None,
            "rerun_argv": rerun, "retryable": True,
        })
        return EXIT_HANDOFF
    _print_json(result)
    return EXIT_OK if result.get("ok") else EXIT_HANDOFF


def cmd_parse_incoming(_args) -> int:
    """Scrollback-only fallback. The primary inline-bootstrap path is
    on `send` via --peer-surface / --bootstrap-suggested-title /
    --bootstrap-file; this verb stays as a debug tool for the rare case
    where the agent can't read its own user prompt directly and needs
    to scrape scrollback."""
    surf = surface.my_surface()
    if surf is None:
        _print_json(errors.not_in_cmux())
        return EXIT_HANDOFF
    tree = surface.cmux_tree()
    ws = surface.workspace_of(surf, tree)
    try:
        text = transport.read_screen(surf, ws)
    except transport.TransportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_SYSTEM
    parsed = bootstrap.parse_bootstrap_text(text)
    if not parsed:
        print("error: no [p2p-bootstrap] block in scrollback",
              file=sys.stderr)
        return EXIT_SYSTEM
    _print_json(parsed)
    return EXIT_OK


# ---------------- dispatch ----------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent_msg")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)

    s = sub.add_parser("send")
    # --peer is not argparse-required because --bootstrap-file can
    # supply it. cmd_send validates manually.
    s.add_argument("--peer", default=None,
                   help="Tab title of the destination peer in your "
                        "workspace. Title is the single routing key.")
    s.add_argument("--peer-surface", default=None,
                   help="Skip title resolution and route directly. "
                        "Used when an inline bootstrap already gave "
                        "you the peer's surface, or to disambiguate "
                        "a peer_ambiguous handoff.")
    s.add_argument("--my-title", default=None,
                   help="Self title to register under on first call. "
                        "Cosmetically renames the cmux tab to match. "
                        "Ignored if already registered.")
    s.add_argument("--my-name", default=None,
                   help=argparse.SUPPRESS)  # deprecated alias
    s.add_argument("--bootstrap-suggested-title", default=None,
                   help="Self title precedence when --my-title is "
                        "absent and you have an inline bootstrap.")
    s.add_argument("--bootstrap-suggested-name", default=None,
                   help=argparse.SUPPRESS)  # deprecated alias
    s.add_argument("--bootstrap-file", default=None,
                   help="Read --peer / --peer-surface / "
                        "--bootstrap-suggested-title from this file.")
    s.add_argument("--workspace", default=None,
                   help="Scope title resolution. Default: caller's own "
                        "workspace. Pass `all` for global scope, or a "
                        "specific workspace_ref.")
    s.add_argument("--one-way", action="store_true",
                   help="Fire-and-forget. Frames the message as "
                        "`[from: X | one-way]` and (on first contact) "
                        "drops the bootstrap's reply request so the "
                        "receiver is not pulled into responding.")
    s.add_argument("--message")
    s.add_argument("--message-file")
    s.set_defaults(func=cmd_send)

    sub.add_parser("parse-incoming").set_defaults(func=cmd_parse_incoming)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Bump last_seen before dispatch as a diagnostic heartbeat.
    registry.touch_self(surface.my_surface())
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
