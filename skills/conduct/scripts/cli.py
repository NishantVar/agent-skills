"""conduct CLI — parse the verb + flags, run the orchestration, print exactly
one JSON envelope on stdout, and exit with a code reflecting the outcome.

    conduct.py status   (--agent surface:N | --all)
    conduct.py claim     --agent surface:N
    conduct.py register  --from-fork <tfork-json>      # alias of claim
    conduct.py release   --agent surface:N
    conduct.py clear     (--agent surface:N | --all)
    conduct.py compact   (--agent surface:N | --all)
    conduct.py exit      (--agent surface:N | --all)
    conduct.py kill      (--agent surface:N | --all)
    conduct.py interrupt (--agent surface:N | --all)

--agent accepts a `surface:N` short ref (resolved to a UUID at call time) or a
surface UUID directly (durable across workspace/window moves).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Tuple

from core import LIFECYCLE_VERBS, run_claim, run_lifecycle, run_release, run_status
from errors import EXIT_CODES, bad_arguments


def _print(obj) -> None:
    sys.stdout.write(json.dumps(obj, indent=2))
    sys.stdout.write("\n")


def _from_fork_ref(
    path_or_json: str,
) -> Tuple[Optional[str], Optional[dict]]:
    """Extract a surface ref from tfork's result JSON (the
    `register --from-fork` alias). tfork returns `session: surface:N`; accept a
    few shapes for robustness. Returns (ref, error_dict)."""
    raw = path_or_json
    # Allow either an inline JSON string or a path to a file holding it.
    try:
        with open(path_or_json, "r") as f:
            raw = f.read()
    except (OSError, ValueError):
        pass
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None, bad_arguments(
            "--from-fork must be tfork's result JSON (inline or a file path)")
    if not isinstance(data, dict):
        return None, bad_arguments("--from-fork JSON must be an object")
    ref = (data.get("session") or data.get("surface")
           or data.get("surface_ref") or data.get("uuid")
           or data.get("surface_id"))
    if not ref:
        return None, bad_arguments(
            "--from-fork JSON has no session/surface/surface_ref field")
    return ref, None


def _exit_for(result: dict) -> int:
    if result.get("ok"):
        return 0
    return EXIT_CODES.get(result.get("code", ""), 1)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="conduct",
        description="cmux control plane: read fleet status and issue runtime-"
                    "aware lifecycle control over the agents you own. Never "
                    "spawns, never messages, never shells out to other skills.")
    sub = p.add_subparsers(dest="verb", required=True)

    def add_target(sp, with_all=True):
        sp.add_argument("--agent", default=None,
                        help="Target: a `surface:N` short ref (resolved to a "
                             "UUID at call time) or a surface UUID directly.")
        if with_all:
            sp.add_argument("--all", action="store_true",
                            help="Operate over your OWNED SET only — never an "
                                 "ungated workspace/all broadcast.")

    s = sub.add_parser("status", help="Per-agent context-pct + runtime + state "
                                      "over one owned agent or your owned set.")
    add_target(s)

    c = sub.add_parser("claim", help="Eagerly claim ownership without a "
                                     "control verb.")
    add_target(c, with_all=False)

    r = sub.add_parser("register", help="Alias of claim that reads tfork's "
                                        "result JSON.")
    r.add_argument("--from-fork", dest="from_fork", required=True,
                   help="tfork's result JSON (inline string or file path); the "
                        "`session: surface:N` field is claimed.")

    rel = sub.add_parser("release", help="Drop a claim (enables transfer / "
                                         "teardown).")
    add_target(rel, with_all=False)

    for verb in LIFECYCLE_VERBS:
        lp = sub.add_parser(verb, help=f"Inject the runtime's {verb} action.")
        add_target(lp)

    return p


def _rerun_argv(verb: str, args) -> list:
    out = ["conduct.py", verb]
    if getattr(args, "agent", None):
        out += ["--agent", args.agent]
    if getattr(args, "all", False):
        out += ["--all"]
    if getattr(args, "from_fork", None):
        out += ["--from-fork", args.from_fork]
    return out


def main(argv=None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # --help / -h exits 0 with usage already on stdout; let it through.
        if exc.code in (0, None):
            return 0
        _print(bad_arguments("see usage above"))
        return EXIT_CODES["bad_arguments"]

    verb = args.verb
    rerun = _rerun_argv(verb, args)

    if verb == "status":
        if not args.agent and not args.all:
            result = bad_arguments("status needs --agent <ref> or --all")
        elif args.agent and args.all:
            result = bad_arguments("pass only one of --agent or --all")
        else:
            result = run_status(agent_ref=args.agent, all_owned=args.all,
                                rerun_argv=rerun)

    elif verb == "claim":
        if not args.agent:
            result = bad_arguments("claim needs --agent <ref>")
        else:
            result = run_claim(args.agent, rerun_argv=rerun)

    elif verb == "register":
        ref, err = _from_fork_ref(args.from_fork)
        if err is not None or ref is None:
            result = err if err is not None else bad_arguments(
                "--from-fork did not yield a surface ref")
        else:
            result = run_claim(ref, rerun_argv=rerun)

    elif verb == "release":
        if not args.agent:
            result = bad_arguments("release needs --agent <ref>")
        else:
            result = run_release(args.agent, rerun_argv=rerun)

    elif verb in LIFECYCLE_VERBS:
        if not args.agent and not args.all:
            result = bad_arguments(f"{verb} needs --agent <ref> or --all")
        elif args.agent and args.all:
            result = bad_arguments("pass only one of --agent or --all")
        else:
            result = run_lifecycle(verb, agent_ref=args.agent,
                                   all_owned=args.all, rerun_argv=rerun)
    else:
        result = bad_arguments(f"unknown verb {verb!r}")

    _print(result)
    return _exit_for(result)


if __name__ == "__main__":
    sys.exit(main())
