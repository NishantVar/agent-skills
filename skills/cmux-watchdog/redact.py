"""Secret redaction + screen hashing for the cmux capture layer.

Watchdog is the sole cmux reader, so it is also the sole place raw pane text
exists. Redaction happens here before any text leaves the process (into a
Finding's evidence snippet, a journal line, or the snapshot envelope shipped to
observability). Patterns are deliberately tight — false positives beat leaking
a real secret downstream.

`redact_meta(text) -> (redacted, applied)` is the rich form (carries the list
of `"<KIND>:<count>"` strings the snapshot contract needs). `redact(text) ->
str` is the thin wrapper kept for the evidence/journal callers that only want
the masked text. `screen_hash(redacted)` is the cache key observability stores.
"""

from __future__ import annotations

import hashlib
import re


_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SK_TOKEN",       re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("AWS_ACCESS_KEY", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GH_TOKEN",       re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("SLACK_TOKEN",    re.compile(r"xox[bopa]-[A-Za-z0-9-]{10,}")),
    ("BEARER",         re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}")),
    ("PASSWORD",       re.compile(r"""password\s*[:=]\s*('|")?[^\s'"]{4,}('|")?""", re.IGNORECASE)),
]


def redact_meta(text: str) -> tuple[str, list[str]]:
    """Return (redacted_text, applied) where `applied` lists "<KIND>:<count>"
    for each pattern that fired. Originals never appear in `redacted_text`."""
    applied: list[str] = []
    out = text
    for kind, pat in _PATTERNS:
        hits = pat.findall(out)
        if not hits:
            continue
        applied.append(f"{kind}:{len(hits)}")
        out = pat.sub(f"<REDACTED:{kind}>", out)
    return out, applied


def redact(text: str) -> str:
    """Thin wrapper for callers that only want the masked text."""
    return redact_meta(text)[0]


def screen_hash(redacted_text: str) -> str:
    """sha256 hex of the (already-redacted) screen text — the summary cache key."""
    return hashlib.sha256(redacted_text.encode("utf-8")).hexdigest()
