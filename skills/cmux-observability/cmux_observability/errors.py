"""Typed errors and the Failure record used in the Snapshot.

`Failure` is a non-exception data record attached to a Snapshot when a
component degraded but did not block the rest of the snapshot. Real
exceptions are reserved for programmer error and unrecoverable conditions.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Failure:
    component: str            # "cmux" | "read_screen" | "git" | "discovery" | "config" | "summarize_io"
    target: str | None
    message: str
    fatal: bool = False       # v1 has no fatal=True paths by design


class CmuxUnavailable(Exception):
    """Raised when the cmux CLI cannot be invoked or returns non-zero on a
    call where it should not. Callers catch this and degrade."""


class ContractViolation(Exception):
    """Raised when the JSON contract from the calling agent is malformed in
    a way that cannot be partially salvaged. Wraps the offending entry."""
