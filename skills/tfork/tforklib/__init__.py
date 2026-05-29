"""tforklib — the deterministic terminal-fork engine behind the ``tfork`` skill.

The package is split by concern:

    errors       structured ``ForkError`` + failure-taxonomy factories
    registry     the self-building TOML classification map (a journal of
                 the latest authoritative label for each command word)
    classify     post-hoc ``classify_observed`` — label from what was seen
    terminal     the ``Terminal`` abstraction, the cmux backend, and the
                 sentinel-wrapper builder
    verify       ``verify_fork`` — the single post-spawn check that returns
                 (verified, foreground, exit_status, note)
    orchestrate  ``run_fork`` — the fork -> verify -> label -> persist flow
    cli          argument parsing and the ``main`` entry point

This module re-exports the public API so callers (and tests) can reach the
whole surface as ``tforklib.<name>``; the ``fork_terminal.py`` entry-point
script imports ``main`` from here.
"""

from .errors import (
    EXIT_CODES,
    ForkError,
    err_anchor_ambiguous,
    err_anchor_not_found,
    err_bad_arguments,
    err_no_terminal,
    err_spawn_failed,
    err_split_failed,
    err_surface_resolution_failed,
    err_workspace_ambiguous,
    err_workspace_anchor_conflict,
    err_workspace_unknown,
)
from .registry import REGISTRY_PATH, read_registry, write_registry_entry
from .classify import classify_observed
from .terminal import (
    SPLIT_DIRS,
    TERMINALS,
    CmuxTerminal,
    Terminal,
    is_workspace_ref,
    resolve_anchor,
    resolve_terminal,
)
from .verify import DEFAULT_DELAY, is_shell, verify_fork
from .orchestrate import run_fork
from .cli import PLACEMENT_CHOICES, main, parse_args

__all__ = [
    "EXIT_CODES",
    "ForkError",
    "err_anchor_ambiguous",
    "err_anchor_not_found",
    "err_bad_arguments",
    "err_no_terminal",
    "err_spawn_failed",
    "err_split_failed",
    "err_surface_resolution_failed",
    "err_workspace_ambiguous",
    "err_workspace_anchor_conflict",
    "err_workspace_unknown",
    "REGISTRY_PATH",
    "read_registry",
    "write_registry_entry",
    "classify_observed",
    "SPLIT_DIRS",
    "TERMINALS",
    "CmuxTerminal",
    "Terminal",
    "is_workspace_ref",
    "resolve_anchor",
    "resolve_terminal",
    "DEFAULT_DELAY",
    "is_shell",
    "verify_fork",
    "run_fork",
    "PLACEMENT_CHOICES",
    "main",
    "parse_args",
]
