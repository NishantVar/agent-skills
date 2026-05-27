"""Argument parsing and the ``main`` entry point.

Invocation contract::

    fork_terminal.py
        --placement {right,left,top,bottom,new-workspace}
        [--anchor <surface-ref-or-tab-name>]
        [--type {agent,command}]
        [--delay N]
        -- <command...>

Everything after ``--`` is the command (an alias or a literal command, free
to contain its own flags and spaces); its first word is the registry key.
``--anchor`` accepts either a ``surface:N`` ref or a cmux tab title; without
it, the new pane is placed next to the caller's own surface.

On success ``main`` prints, on stdout, and exits 0 with::

    {"ok": true, "session": "<surface-ref>", "ran": "<word>",
     "type": "<agent|command>", "verified": <bool>,
     "foreground": "<process-or-null>", "exit_status": <int-or-null>,
     "note": "<one-line description of what was observed>"}

``verified`` may be false: the command was forked, its pane was left open,
and the note explains what tfork saw. The agent then decides what to do —
re-running is forbidden by contract.

On failure it prints a handoff object and exits non-zero::

    {"ok": false, "code": "...", "human_message": "...",
     "agent_instruction": "...", "retryable": <bool>,
     "suggested_next_command": "..."}
"""

import argparse
import json

from .errors import EXIT_CODES, ForkError, err_bad_arguments
from .orchestrate import run_fork
from .terminal import NEW_WORKSPACE, SPLIT_DIRS

PLACEMENT_CHOICES = SPLIT_DIRS + (NEW_WORKSPACE,)


class _ForkArgParser(argparse.ArgumentParser):
    """Argparse that raises a structured ``bad_arguments`` handoff instead of
    printing plain usage text and exiting 2."""

    def error(self, message):
        raise err_bad_arguments(message)


def _nonneg_int(value):
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not an integer")
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"'{value}' is negative")
    return parsed


def parse_args(argv):
    # add_help is kept on purpose: ``--help`` prints argparse usage text and
    # exits 0. It is the one human-facing path that does not emit a JSON
    # object — every actual fork invocation still prints exactly one. The
    # front-door skill never passes --help.
    parser = _ForkArgParser(prog="fork_terminal.py", add_help=True,
                            description="Deterministic terminal fork.")
    parser.add_argument("--placement", choices=PLACEMENT_CHOICES,
                        default="right",
                        help="where the new pane opens (default: right)")
    parser.add_argument("--anchor", default=None,
                        help="surface ref or tab title to place next to; "
                             "default: the caller's own surface")
    parser.add_argument("--type", choices=("agent", "command"), default=None,
                        help="force the type label; otherwise post-hoc")
    parser.add_argument("--title", default=None,
                        help="rename the new tab to this title after fork, "
                             "so it is immediately p2p-addressable")
    parser.add_argument("--delay", type=_nonneg_int, default=None,
                        help="seconds to wait before reading the new pane")
    parser.add_argument("command", nargs="*",
                        help="the command, after a '--' separator")
    return parser.parse_args(argv)


def main(argv=None):
    try:
        args = parse_args(argv)
        result = run_fork(args.command, placement=args.placement,
                          anchor=args.anchor, type_override=args.type,
                          title=args.title, delay=args.delay)
    except ForkError as exc:
        print(json.dumps(exc.handoff()))
        return EXIT_CODES.get(exc.code, 1)
    print(json.dumps(result))
    return 0
