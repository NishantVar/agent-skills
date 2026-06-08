"""afork CLI — parse the front-door flags, run the pipeline, print one JSON
object, and exit with a code that reflects the outcome.

    afork.py <runtime> [agent] [--permission {none,read-only,workspace-write}]
             [--model M] [--effort E] [--title T] [--cwd DIR]
             [--placement {right,left,top,bottom}] [--allow-unenforced]
"""

import argparse
import json

from . import run_afork
from .errors import EXIT_CODES, AforkError, err_bad_arguments


def build_parser():
    p = argparse.ArgumentParser(
        prog="afork",
        description="Front door for forking any coding agent (plain or "
                    "definition-backed) into a cmux pane: build a launch "
                    "command and hand it to tfork. Fails closed only when a "
                    "declared restriction can't be runtime-enforced.")
    p.add_argument("runtime", choices=["codex", "claude", "pi", "antigravity"],
                   help="Coding-agent runtime. codex/claude/pi launch (plain + "
                        "permission none); antigravity is unsupported.")
    p.add_argument("agent", nargs="?", default=None,
                   help="Optional agent definition to resolve under "
                        "<cwd>/.<runtime>/agents/. Omit for a plain agent.")
    p.add_argument("--permission", default=None,
                   choices=["none", "read-only", "workspace-write"],
                   help="Agnostic permission posture. Default (unset) resolves "
                        "to the definition's declaration, else none (yolo).")
    p.add_argument("--model", default=None,
                   help="Agnostic model; falls back to the runtime default.")
    p.add_argument("--effort", default=None,
                   help="Agnostic reasoning effort; falls back to the default.")
    p.add_argument("--title", default=None,
                   help="cmux tab title for the forked pane (defaults to the "
                        "agent name, else the runtime). Forwarded to tfork.")
    p.add_argument("--cwd", default=None,
                   help="Target repo whose agent ports are resolved and where "
                        "the agent runs. Defaults to the caller's cwd.")
    p.add_argument("--placement", default=None,
                   choices=["right", "left", "top", "bottom"],
                   help="Pane placement, forwarded to tfork.")
    p.add_argument("--allow-unenforced", action="store_true",
                   help="Explicitly proceed when a declared restriction cannot "
                        "be runtime-enforced. Off by default (fail-closed).")
    return p


def main(argv=None):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        # argparse already wrote usage to stderr; mirror tfork's JSON contract.
        print(json.dumps(err_bad_arguments("see usage above").handoff()))
        return EXIT_CODES["bad_arguments"]

    try:
        result = run_afork(
            runtime=args.runtime,
            agent=args.agent,
            permission=args.permission,
            model=args.model,
            effort=args.effort,
            title=args.title,
            cwd=args.cwd,
            placement=args.placement,
            allow_unenforced=args.allow_unenforced,
        )
    except AforkError as exc:
        print(json.dumps(exc.handoff(), indent=2))
        return EXIT_CODES.get(exc.code, 1)

    print(json.dumps(result, indent=2))
    return 0
