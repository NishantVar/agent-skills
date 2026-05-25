"""argparse front door. `_touch_self` heartbeats at the top of every
invocation so a stale-marked agent revives the moment it wakes up."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import bootstrap, errors, registry, send, surface


EXIT_OK = 0
EXIT_HANDOFF = 2  # ok:false in JSON
EXIT_NOT_REGISTERED = 4
EXIT_SYSTEM = 1


def _print_json(obj: object) -> None:
    sys.stdout.write(json.dumps(obj, indent=2))
    sys.stdout.write("\n")


def _decorate_me(m: dict, surfaces: dict[str, dict]) -> dict:
    ref = m.get("surface_ref") or ""
    s = surfaces.get(ref, {})
    return {
        "name": m.get("name"),
        "surface_ref": ref,
        "workspace_ref": s.get("workspace_ref"),
        "workspace_title": s.get("workspace_title", ""),
        "status": m.get("status") or "live",
    }


def _decorate_peer(m: dict, surfaces: dict[str, dict]) -> dict:
    out = _decorate_me(m, surfaces)
    out["last_seen"] = m.get("last_seen")
    return out


# ---------------- subcommands ----------------

def cmd_whoami(_args) -> int:
    surf = surface.my_surface()
    m = registry.get_self(surf)
    if not m:
        return EXIT_NOT_REGISTERED
    _print_json(m)
    return EXIT_OK


def cmd_register(args) -> int:
    surf = surface.my_surface()
    if surf is None:
        _print_json(errors.not_in_cmux())
        return EXIT_HANDOFF
    tree = surface.cmux_tree()
    live = surface.live_surfaces(tree)
    surfaces = surface.surface_index(tree)
    m, err = registry.register(args.name, surf, live)
    if err:
        kind = err["kind"]
        if kind == "bad_name_format":
            _print_json(errors.bad_name_format(args.name))
        elif kind == "name_collision":
            _print_json(errors.name_collision(args.name,
                                              err["holder_surface"]))
        elif kind == "name_collision_stale":
            _print_json(errors.name_collision_stale(args.name,
                                                    err["holder_surface"]))
        elif kind == "not_in_cmux":
            _print_json(errors.not_in_cmux())
        return EXIT_HANDOFF
    assert m is not None
    ws = surfaces.get(surf, {}).get("workspace_ref")
    from .transport import rename_tab
    rename_tab(surf, ws, args.name)
    _print_json(m)
    return EXIT_OK


def cmd_list(_args) -> int:
    surf = surface.my_surface()
    tree = surface.cmux_tree()
    live = surface.live_surfaces(tree)
    surfaces = surface.surface_index(tree)
    manifests = registry.all_manifests(live)
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


def cmd_send(args) -> int:
    body = _read_body(args)
    rerun = ["agent_msg.py", "send", "--peer", args.peer]
    if args.my_name:
        rerun += ["--my-name", args.my_name]
    if args.message_file:
        rerun += ["--message-file", args.message_file]

    fallback_self_name = None
    if not args.my_name and registry.get_self(surface.my_surface()) is None:
        # Try scrollback for a bootstrap that suggests a self name.
        try:
            tree = surface.cmux_tree()
            ws = surface.workspace_of(surface.my_surface() or "", tree)
            text = ""
            if surface.my_surface():
                from .transport import read_screen, TransportError
                try:
                    text = read_screen(surface.my_surface() or "", ws)
                except TransportError:
                    text = ""
            parsed = bootstrap.parse_bootstrap_text(text) if text else None
            if parsed:
                fallback_self_name = parsed.get("suggested_name") or None
        except Exception:
            pass

    try:
        result = send.send(
            peer=args.peer,
            body=body,
            my_name=args.my_name,
            fallback_self_name=fallback_self_name,
            rerun_argv=rerun,
        )
    except Exception as exc:  # transport errors land here
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


def cmd_parse_incoming(args) -> int:
    """Three modes, in precedence order:
      1. Explicit --peer-name + --peer-surface (the inline-prompt
         primary path).
      2. --bootstrap-file, parsed as bootstrap text.
      3. Scrollback scan (fallback).
    """
    if args.peer_name and args.peer_surface:
        out = {"peer_name": args.peer_name,
               "peer_surface": args.peer_surface}
        if args.bootstrap_suggested_name:
            out["suggested_name"] = args.bootstrap_suggested_name
        _print_json(out)
        return EXIT_OK
    if args.bootstrap_file:
        text = Path(args.bootstrap_file).read_text()
        parsed = bootstrap.parse_bootstrap_text(text)
        if not parsed:
            print("error: no [p2p-bootstrap] block in file",
                  file=sys.stderr)
            return EXIT_SYSTEM
        _print_json(parsed)
        return EXIT_OK
    surf = surface.my_surface()
    if surf is None:
        _print_json(errors.not_in_cmux())
        return EXIT_HANDOFF
    tree = surface.cmux_tree()
    ws = surface.workspace_of(surf, tree)
    from .transport import read_screen, TransportError
    try:
        text = read_screen(surf, ws)
    except TransportError as exc:
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

    sub.add_parser("whoami").set_defaults(func=cmd_whoami)

    s = sub.add_parser("register")
    s.add_argument("--name", required=True)
    s.set_defaults(func=cmd_register)

    sub.add_parser("list").set_defaults(func=cmd_list)

    s = sub.add_parser("send")
    s.add_argument("--peer", required=True)
    s.add_argument("--my-name", default=None)
    s.add_argument("--message")
    s.add_argument("--message-file")
    s.set_defaults(func=cmd_send)

    s = sub.add_parser("parse-incoming")
    s.add_argument("--peer-name", default=None)
    s.add_argument("--peer-surface", default=None)
    s.add_argument("--bootstrap-suggested-name", default=None)
    s.add_argument("--bootstrap-file", default=None)
    s.set_defaults(func=cmd_parse_incoming)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Heartbeat before dispatch so a stale agent revives on any call.
    registry.touch_self(surface.my_surface())
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
