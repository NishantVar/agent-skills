"""Conservative regex-based secret redaction.

Patterns are deliberately tight. False positives are preferable to leaking
real secrets into a calling agent's context or into the screen-hash input.
"""

from __future__ import annotations

import re


_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SK_TOKEN",       re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("AWS_ACCESS_KEY", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GH_TOKEN",       re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("SLACK_TOKEN",    re.compile(r"xox[bopa]-[A-Za-z0-9-]{10,}")),
    ("BEARER",         re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}")),
    ("PASSWORD",       re.compile(r"""password\s*[:=]\s*('|")?[^\s'"]{4,}('|")?""", re.IGNORECASE)),
]


def redact(text: str) -> tuple[str, list[str]]:
    """Return (redacted_text, applied) where `applied` is a list of
    "<KIND>:<count>" strings. Originals never appear in `redacted_text`."""
    applied: list[str] = []
    out = text
    for kind, pat in _PATTERNS:
        hits = pat.findall(out)
        if not hits:
            continue
        applied.append(f"{kind}:{len(hits)}")
        out = pat.sub(f"<REDACTED:{kind}>", out)
    return out, applied
