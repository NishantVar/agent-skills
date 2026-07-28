"""tforklib — the deterministic terminal-fork engine behind the ``tfork`` skill.

The package is split by concern:

    errors       structured ``ForkError`` + failure-taxonomy factories
    registry     the self-building TOML classification map (a journal of
                 the latest authoritative label for each command word)
    classify     post-hoc ``classify_observed`` — label from what was seen
    terminal     the ``Terminal`` abstraction, the cmux backend, and the
                 sentinel-wrapper builder
    outcome      the versioned launch-outcome contract, kept byte-identical
                 with ``aforklib/outcome.py`` so both halves agree
    verify       ``observe_fork`` (one pane snapshot) + ``verdict`` (the
                 human-facing (verified, foreground, exit_status, note))
    result       ``derive_launch_outcome`` — the machine-facing reading of
                 that same snapshot, combined with afork's sidecar
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
    err_window_anchor_conflict,
    err_window_create_failed,
    err_window_unknown,
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
from .outcome import (
    CONTRACT_VERSION,
    EVIDENCE_CODES,
    REASON_CODES,
    STATES,
    launch_outcome,
    load_sidecar,
    prework_failure,
    unknown,
)
from .verify import DEFAULT_DELAY, Observation, is_shell, observe_fork, verdict, verify_fork
from .result import derive_launch_outcome
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
    "err_window_anchor_conflict",
    "err_window_create_failed",
    "err_window_unknown",
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
    "CONTRACT_VERSION",
    "EVIDENCE_CODES",
    "REASON_CODES",
    "STATES",
    "launch_outcome",
    "load_sidecar",
    "prework_failure",
    "unknown",
    "DEFAULT_DELAY",
    "Observation",
    "is_shell",
    "observe_fork",
    "verdict",
    "verify_fork",
    "derive_launch_outcome",
    "run_fork",
    "PLACEMENT_CHOICES",
    "main",
    "parse_args",
]
