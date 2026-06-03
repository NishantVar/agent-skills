#!/usr/bin/env python3
"""cmux-watchdog — deterministic pane-failure detector and safe remediator.

Mechanical work only: enumerate cmux surfaces in scope, read each screen,
match known failure signatures, and (for the one safe case) press Enter on a
stuck composer. All judgement — confirming a finding, deciding whether to
retry an API error, or respawning a dead agent — is left to the calling
coding agent. This binary never composes a p2p message and never forks an
agent; it returns findings the agent acts on.

Subcommands
-----------
scan        One-shot. Print a JSON object {ok, run_id, scope, scanned,
            candidates:[...]} describing every detected failure in scope.
watch       Loop. Emit newline-delimited JSON (one object per *newly*
            detected failure) for consumption by the agent's Monitor tool.
            Re-emits a finding only after it has cleared and recurred.
send-enter  The single safe remediation. Re-reads the surface, confirms an
            unsent p2p frame is still in the composer, presses Enter, and
            re-reads to confirm it cleared. Pressing Enter on already-empty
            input is a no-op, so this is self-verifying and idempotent.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass


# --------------------------------------------------------------------------
# Redaction — tight patterns; false positives beat leaking a real secret into
# the calling agent's context via an evidence snippet.
# --------------------------------------------------------------------------

_REDACT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SK_TOKEN",       re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("AWS_ACCESS_KEY", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GH_TOKEN",       re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("SLACK_TOKEN",    re.compile(r"xox[bopa]-[A-Za-z0-9-]{10,}")),
    ("BEARER",         re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}")),
    ("PASSWORD",       re.compile(r"""password\s*[:=]\s*('|")?[^\s'"]{4,}('|")?""", re.IGNORECASE)),
]


def redact(text: str) -> str:
    out = text
    for kind, pat in _REDACT_PATTERNS:
        out = pat.sub(f"<REDACTED:{kind}>", out)
    return out


# --------------------------------------------------------------------------
# Detection — pure functions over screen text. No I/O here so they are unit
# testable against fixtures.
# --------------------------------------------------------------------------

# A p2p wire frame: "[from: builder] body" or "[from: builder | one-way] body".
_FRAME_RE = re.compile(r"\[from:\s*[^\]]+\]")

# Markers that mean the agent is actively processing — if any appears below a
# frame, the Enter landed and the agent is working; not a stuck composer.
_ACTIVE_RE = re.compile(
    r"(esc to interrupt|interrupt\b|Running…|Working…|Thinking…|Compacting|"
    r"[⠀-⣿])",  # braille spinner glyphs
    re.IGNORECASE,
)

# Known API / transport failure signatures. Order matters only for the label.
_API_ERROR_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("overloaded",     re.compile(r"overloaded_error|\boverloaded\b", re.IGNORECASE)),
    ("rate_limit",     re.compile(r"rate[ _]?limit|\b429\b", re.IGNORECASE)),
    ("server_5xx",     re.compile(r"\b5(00|02|03|29)\b|internal server error|bad gateway|service unavailable", re.IGNORECASE)),
    ("api_error",      re.compile(r"\bAPI Error\b|api_error", re.IGNORECASE)),
    ("connection",     re.compile(r"connection error|ECONNRESET|ETIMEDOUT|ENOTFOUND|socket hang up|fetch failed|getaddrinfo", re.IGNORECASE)),
    ("timeout",        re.compile(r"request timed out|\btimeout\b", re.IGNORECASE)),
]

# How many lines from the bottom count as "the composer / live viewport".
_TAIL_WINDOW = 30

# Footer / hint chrome that appears below the composer but is not agent output.
_FOOTER_RE = re.compile(
    r"\?\s*for shortcuts|for newline|⏎|↵|\btokens?\b|auto-?accept|bypass",
    re.IGNORECASE,
)
# A line that is only box-drawing / prompt punctuation carries no agent output.
_BOX_ONLY_RE = re.compile(r"^[\s│┃╭╮╰╯─━┄┈>›·•＞]*$")


def _is_agent_output(line: str) -> bool:
    """True when a line below a frame looks like real agent output (so the
    message was submitted), as opposed to composer chrome or the message's
    own wrapped continuation inside the input box."""
    stripped = line.strip()
    if not stripped:
        return False
    if line.lstrip().startswith(("│", "┃")):
        return False  # interior of the input box — message wrap, not output
    if _BOX_ONLY_RE.match(line):
        return False
    if _FOOTER_RE.search(line):
        return False
    return any(ch.isalnum() for ch in stripped)


@dataclass
class Finding:
    signature: str        # "unsent_p2p" | "api_error"
    tier: str             # "safe" | "risky"
    remediation: str      # "send_enter" | "retry_or_resend" | ...
    detail: str           # one-line human explanation
    evidence: str         # redacted snippet the agent can confirm against


def _tail(lines: list[str], n: int) -> list[str]:
    return lines[-n:] if len(lines) > n else lines


def detect_unsent_p2p(screen: str) -> Finding | None:
    """A p2p frame sitting in the composer with nothing active below it means
    the message text was pasted but the final Enter never registered."""
    lines = screen.rstrip("\n").splitlines()
    if not lines:
        return None
    window = _tail(lines, _TAIL_WINDOW)
    frame_idxs = [i for i, ln in enumerate(window) if _FRAME_RE.search(ln)]
    if not frame_idxs:
        return None
    below = window[frame_idxs[-1] + 1:]
    if any(_ACTIVE_RE.search(ln) for ln in below):
        return None  # agent is processing — Enter landed
    if any(_is_agent_output(ln) for ln in below):
        return None  # agent already responded — message was submitted
    frame_line = window[frame_idxs[-1]].strip()
    return Finding(
        signature="unsent_p2p",
        tier="safe",
        remediation="send_enter",
        detail="A p2p frame is sitting unsent in the composer (final Enter likely dropped).",
        evidence=redact(frame_line)[:200],
    )


def detect_api_error(screen: str) -> Finding | None:
    """A known API / transport error string near the bottom of the viewport."""
    lines = screen.rstrip("\n").splitlines()
    window = _tail(lines, _TAIL_WINDOW)
    for i, ln in enumerate(window):
        for label, pat in _API_ERROR_PATTERNS:
            if pat.search(ln):
                snippet = "\n".join(window[max(0, i - 1): i + 2])
                return Finding(
                    signature="api_error",
                    tier="risky",
                    remediation="retry_or_resend",
                    detail=f"Possible API/transport error ({label}) in recent output.",
                    evidence=redact(snippet)[:400],
                )
    return None


def detect(screen: str) -> list[Finding]:
    findings: list[Finding] = []
    for fn in (detect_unsent_p2p, detect_api_error):
        f = fn(screen)
        if f is not None:
            findings.append(f)
    return findings


# --------------------------------------------------------------------------
# cmux CLI wrappers
# --------------------------------------------------------------------------

class CmuxError(RuntimeError):
    pass


def _run_cmux(*args: str) -> str:
    if shutil.which("cmux") is None:
        raise CmuxError("cmux binary not on PATH")
    try:
        cp = subprocess.run(["cmux", *args], check=False, text=True, capture_output=True)
    except OSError as e:
        raise CmuxError(str(e)) from e
    if cp.returncode != 0:
        raise CmuxError(f"cmux {' '.join(args)!r} exited {cp.returncode}: {cp.stderr.strip()}")
    return cp.stdout


@dataclass
class SurfaceRef:
    surface_ref: str
    workspace_ref: str
    workspace_title: str
    title: str


_WORKSPACE_RE = re.compile(r'\bworkspace (workspace:\d+)\s+"([^"]*)"')
_SURFACE_RE = re.compile(r'\bsurface (surface:\d+)\s+\[(terminal|browser)\]\s+"([^"]*)"')


def parse_tree(stdout: str) -> list[SurfaceRef]:
    """Parse `cmux tree --all` into terminal surfaces with their workspace."""
    surfaces: list[SurfaceRef] = []
    cur_ws_ref = cur_ws_title = ""
    for raw in stdout.splitlines():
        line = raw.strip()
        m = _WORKSPACE_RE.search(line)
        if m:
            cur_ws_ref, cur_ws_title = m.group(1), m.group(2)
            continue
        m = _SURFACE_RE.search(line)
        if m and cur_ws_ref:
            ref, kind, title = m.groups()
            if kind == "terminal":
                surfaces.append(SurfaceRef(ref, cur_ws_ref, cur_ws_title, title))
    return surfaces


def filter_scope(surfaces: list[SurfaceRef], scope: str | None) -> list[SurfaceRef]:
    """scope is None (caller workspace), 'all', a workspace ref, or a title."""
    if scope == "all":
        return surfaces
    if scope is None:
        scope = os.environ.get("CMUX_WORKSPACE_ID", "")
        if not scope:
            return surfaces  # no anchor — degrade to all rather than nothing
    return [
        s for s in surfaces
        if scope in (s.workspace_ref, s.workspace_title)
    ]


def read_screen(surface_ref: str, workspace_ref: str, lines: int = 120) -> str:
    return _run_cmux(
        "read-screen", "--workspace", workspace_ref,
        "--surface", surface_ref, "--lines", str(lines),
    )


def send_enter(surface_ref: str, workspace_ref: str) -> None:
    _run_cmux("send-key", "--workspace", workspace_ref, "--surface", surface_ref, "enter")


# --------------------------------------------------------------------------
# Subcommand implementations
# --------------------------------------------------------------------------

def _scan_surfaces(scope: str | None) -> list[dict]:
    surfaces = filter_scope(parse_tree(_run_cmux("tree", "--all")), scope)
    candidates: list[dict] = []
    for s in surfaces:
        try:
            screen = read_screen(s.surface_ref, s.workspace_ref)
        except CmuxError:
            continue  # degrade per-surface; a browser/dead surface is not fatal
        for f in detect(screen):
            row = {
                "surface_ref": s.surface_ref,
                "workspace_ref": s.workspace_ref,
                "workspace_title": s.workspace_title,
                "title": s.title,
                **asdict(f),
            }
            candidates.append(row)
    return candidates


def cmd_scan(args: argparse.Namespace) -> int:
    run_id = secrets.token_hex(6)
    try:
        candidates = _scan_surfaces(args.workspace)
    except CmuxError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    print(json.dumps({
        "ok": True,
        "run_id": run_id,
        "scope": args.workspace or os.environ.get("CMUX_WORKSPACE_ID") or "all",
        "candidates": candidates,
    }))
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    seen: set[tuple[str, str]] = set()
    print(json.dumps({
        "event": "watching",
        "scope": args.workspace or os.environ.get("CMUX_WORKSPACE_ID") or "all",
        "interval": args.interval,
    }), flush=True)
    while True:
        try:
            candidates = _scan_surfaces(args.workspace)
        except CmuxError as e:
            print(json.dumps({"event": "error", "error": str(e)}), flush=True)
            time.sleep(args.interval)
            continue
        current = {(c["surface_ref"], c["signature"]) for c in candidates}
        for c in candidates:
            key = (c["surface_ref"], c["signature"])
            if key not in seen:
                print(json.dumps({"event": "finding", **c}), flush=True)
        seen = current  # drop cleared findings so a recurrence re-emits
        time.sleep(args.interval)


def cmd_send_enter(args: argparse.Namespace) -> int:
    """Self-verifying: only press Enter when an unsent frame is still present;
    re-read afterward to confirm it cleared."""
    try:
        before = read_screen(args.surface, args.workspace)
    except CmuxError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    if detect_unsent_p2p(before) is None:
        print(json.dumps({
            "ok": True, "action": "noop",
            "note": "No unsent p2p frame in composer; nothing to send.",
            "surface_ref": args.surface,
        }))
        return 0
    try:
        send_enter(args.surface, args.workspace)
        time.sleep(0.4)
        after = read_screen(args.surface, args.workspace)
    except CmuxError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    cleared = detect_unsent_p2p(after) is None
    print(json.dumps({
        "ok": True,
        "action": "sent_enter",
        "cleared": cleared,
        "surface_ref": args.surface,
        "note": "Composer cleared after Enter." if cleared
                else "Frame still present after Enter; inspect the pane manually.",
    }))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="watchdog", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("scan", help="one-shot scan, print JSON candidates")
    sp.add_argument("--workspace", default=None,
                    help="workspace ref/title, or 'all'. Default: caller workspace.")
    sp.set_defaults(func=cmd_scan)

    wp = sub.add_parser("watch", help="loop and emit NDJSON findings")
    wp.add_argument("--workspace", default=None,
                    help="workspace ref/title, or 'all'. Default: caller workspace.")
    wp.add_argument("--interval", type=float, default=6.0, help="seconds between scans")
    wp.set_defaults(func=cmd_watch)

    ep = sub.add_parser("send-enter", help="safe remediation for unsent_p2p")
    ep.add_argument("--surface", required=True)
    ep.add_argument("--workspace", required=True)
    ep.set_defaults(func=cmd_send_enter)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
