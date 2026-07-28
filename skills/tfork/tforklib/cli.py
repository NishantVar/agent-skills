"""Argument parsing and the ``main`` entry point.

Invocation contract::

    fork_terminal.py
        [--placement {right,left,top,bottom}]
        [--workspace <title-or-ref>]
        [--window {new|<ref>}]
        [--anchor <surface-ref-or-tab-name>]
        [--type {agent,command}]
        [--delay N]
        [--launch-contract <path>]
        -- <command...>

Everything after ``--`` is the command (an alias or a literal command, free
to contain its own flags and spaces); its first word is the registry key.
``--anchor`` accepts either a ``surface:N`` ref or a cmux tab title; without
it, the new pane is placed next to the caller's own surface. ``--workspace``
accepts a cmux workspace title or ref (created when a title doesn't match);
mutually exclusive with ``--anchor``. ``--window`` opens the fork in a
separate top-level window — ``new`` creates a fresh one (without stealing
focus from the caller's window), or a window ref/index/UUID targets an
existing one; it composes with ``--workspace`` and is mutually exclusive
with ``--anchor``. ``--launch-contract`` points at the 0600 sidecar afork
wrote for this attempt; it is optional and never fatal.

On success ``main`` prints, on stdout, and exits 0 with::

    {"ok": true, "session": "<surface-ref>", "ran": "<word>",
     "type": "<agent|command>", "verified": <bool>,
     "foreground": "<process-or-null>", "exit_status": <int-or-null>,
     "launch_outcome": {"version": 1, "state": "...", "reason_code": ...,
                        "evidence_code": "...", "start_sentinel_seen": <bool>,
                        "end_sentinel_seen": <bool>,
                        "exit_status": <int-or-null>,
                        "foreground": "<process-or-null>"},
     "note": "<one-line description of what was observed>"}

``verified`` and ``note`` are the human-facing reading; ``launch_outcome`` is
the machine-facing one and is the only field policy may branch on. Its
``state`` is ``started``, ``prework_failure``, or ``unknown``; only
``prework_failure`` licenses trying a different runtime or model, and the
free-form ``note`` must never be parsed to reach that conclusion.

``verified`` may be false: the command was forked, its pane was left open,
and the note explains what tfork saw. The agent then decides what to do —
re-running is forbidden by contract.

On failure it prints a handoff object and exits non-zero::

    {"ok": false, "code": "...", "human_message": "...",
     "agent_instruction": "...", "retryable": <bool>,
     "suggested_next_command": "..."}

The three failure codes where a launch was attempted and mechanically failed
(``split_failed``, ``window_create_failed``, ``spawn_failed``) also carry a
``launch_outcome`` in that object.
"""

import argparse
import json

from .errors import EXIT_CODES, ForkError, err_bad_arguments
from .orchestrate import run_fork
from .terminal import SPLIT_DIRS

PLACEMENT_CHOICES = SPLIT_DIRS


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
                        default=None,
                        help="where the new pane opens (default: right "
                             "when --workspace is absent; otherwise fresh "
                             "pane in the target workspace)")
    parser.add_argument("--workspace", default=None,
                        help="cmux workspace title or ref; created when "
                             "a title doesn't match. Mutually exclusive "
                             "with --anchor.")
    parser.add_argument("--window", default=None,
                        help="open the fork in a window instead of the "
                             "caller's: 'new' creates a fresh window; a "
                             "window ref/index/UUID targets an existing one. "
                             "Combine with --workspace to name the workspace. "
                             "Mutually exclusive with --anchor.")
    parser.add_argument("--anchor", default=None,
                        help="surface ref or tab title to place next to; "
                             "default: the caller's own surface. Mutually "
                             "exclusive with --workspace.")
    parser.add_argument("--cwd", default=None,
                        help="working directory the forked command runs in; "
                             "default: the caller's cwd. Path is expanded "
                             "and must exist as a directory.")
    parser.add_argument("--type", choices=("agent", "command"), default=None,
                        help="force the type label; otherwise post-hoc")
    parser.add_argument("--title", default=None,
                        help="rename the new tab to this title after fork, "
                             "so it is immediately p2p-addressable")
    parser.add_argument("--delay", type=_nonneg_int, default=None,
                        help="seconds to wait before reading the new pane")
    parser.add_argument("--launch-contract", default=None,
                        help="path to the launch-contract sidecar afork wrote "
                             "for this attempt. Optional; without it no "
                             "runtime-specific evidence can be trusted and "
                             "ambiguous launches report state 'unknown'.")
    parser.add_argument("command", nargs="*",
                        help="the command, after a '--' separator")
    return parser.parse_args(argv)


def main(argv=None):
    try:
        args = parse_args(argv)
        result = run_fork(args.command, placement=args.placement,
                          anchor=args.anchor, type_override=args.type,
                          title=args.title, delay=args.delay,
                          workspace=args.workspace, cwd=args.cwd,
                          window=args.window,
                          launch_contract=args.launch_contract)
    except ForkError as exc:
        print(json.dumps(exc.handoff()))
        return EXIT_CODES.get(exc.code, 1)
    print(json.dumps(result))
    return 0
