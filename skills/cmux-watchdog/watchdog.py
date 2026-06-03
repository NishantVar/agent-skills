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
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path


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

# Footer / status / mode chrome the agent UI paints around the composer. Used
# only by settled_lines (journaling), kept separate from _FOOTER_RE so detection
# is untouched. Shape-aware on purpose: real transcript prose that merely
# mentions "tokens" / "bypass" must NOT be discarded — only the UI's own hint
# and (volatile) status bars match, so overlap anchoring stays stable tick-to-tick.
_FOOTER_CHROME_RE = re.compile(
    r"\?\s*for shortcuts"                                   # claude/codex hint bar
    r"|\bfor newline\b|[⏎↵]"                                # newline hints
    r"|esc to interrupt"                                    # active hint
    r"|auto-?accept edits|bypass permissions"              # claude mode line
    r"|--\s*(?:INSERT|NORMAL|VISUAL)\s*--|⏵⏵"              # vim-mode / cycle marker
    r"|shift\+tab to cycle|←\s*for agents"                  # claude mode-line bits
    r"|\bctx:\s*\d|\bContext\s+\d+%\s+left"                 # context-% status bars
    r"|─.*\bWorked for\b",                                  # codex 'Worked for Xm Ys' rule
    re.IGNORECASE,
)


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
    label: str = ""              # granular sub-type; for api_error this is the
                                 # _API_ERROR_PATTERNS label the resolution store keys on
    known_resolution: str = ""   # set when a learned resolution graduated this finding


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
        label="unsent_p2p",
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
                    label=label,
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


def send_key(surface_ref: str, workspace_ref: str, key: str) -> None:
    _run_cmux("send-key", "--workspace", workspace_ref, "--surface", surface_ref, key)


def send_enter(surface_ref: str, workspace_ref: str) -> None:
    send_key(surface_ref, workspace_ref, "enter")


_SURFACE_REF_RE = re.compile(r"^surface:\d+$")


def _controller_surface_ref() -> str | None:
    """The surface:N ref of the watchdog's own controlling pane, so scans can
    skip it (that pane is where these very error strings get typed/discussed).
    CMUX_SURFACE_ID is inherited from the spawning agent; it may be a UUID while
    `cmux tree --all` yields surface:N refs, so a UUID is resolved through
    `cmux identify --surface <id>` -> caller.surface_ref. Returns None when the
    env is unset (skip nothing) or when resolution fails (degrade, never crash)."""
    sid = os.environ.get("CMUX_SURFACE_ID", "").strip()
    if not sid:
        return None
    if _SURFACE_REF_RE.match(sid):
        return sid
    try:
        out = _run_cmux("identify", "--surface", sid)
        ref = json.loads(out).get("caller", {}).get("surface_ref")
    except (CmuxError, json.JSONDecodeError, KeyError, AttributeError):
        return None
    return ref or None


# --------------------------------------------------------------------------
# Journaling — best-effort capture of newly-settled pane output. Pure helpers
# (settled_lines / append_new / slugify) are I/O-free so they unit-test against
# fixtures; the watch loop wires them to per-surface append-only log files.
# --------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Lowercase, collapse non-alphanumeric runs to a single '-', trim. No '_'
    survives, so it is safe to use slugs around the '__' filename delimiter."""
    return _SLUG_RE.sub("-", text.lower()).strip("-")


def settled_lines(screen: str) -> list[str]:
    """Strip volatile chrome from a screen capture and return the stable,
    redacted transcript lines — the inverse of _is_agent_output applied to the
    whole screen. Drops blanks, composer-box interior, box-only punctuation,
    footer/hint chrome, and spinner/active lines. Trailing whitespace is
    trimmed so capture padding does not perturb overlap anchoring."""
    out: list[str] = []
    for raw in screen.splitlines():
        if not raw.strip():
            continue
        if raw.lstrip()[:1] in ("│", "┃", "❯", "›"):
            continue  # composer box interior or prompt line
        if _BOX_ONLY_RE.match(raw):
            continue
        if _FOOTER_CHROME_RE.search(raw):
            continue
        if _ACTIVE_RE.search(raw):
            continue  # spinner / "esc to interrupt" — not settled output
        out.append(redact(raw.rstrip()))
    return out


def _run_end(haystack: list[str], run: list[str]) -> int | None:
    """Index just past the FIRST contiguous occurrence of `run` in `haystack`,
    or None. Earliest match aligns the anchor with prev's content so everything
    after it counts as new — and legitimately repeated lines are preserved."""
    n = len(run)
    for i in range(len(haystack) - n + 1):
        if haystack[i:i + n] == run:
            return i + n
    return None


def append_new(prev_settled: list[str], curr_settled: list[str]) -> tuple[list[str], bool]:
    """Overlap-anchored diff. Find the longest suffix of prev_settled that
    occurs as a contiguous run in curr_settled and return the curr lines after
    it, plus a `gap` flag. No hash-dedup — identical repeated lines survive.
    - prev empty (first capture): (curr, False) — seed, no gap.
    - anchor found: (lines after anchor, False); may be [] when nothing is new.
    - no anchor, prev non-empty: (curr, True) — over-capture beats silent loss.
    """
    if not prev_settled:
        return (list(curr_settled), False)
    for length in range(min(len(prev_settled), len(curr_settled)), 0, -1):
        end = _run_end(curr_settled, prev_settled[-length:])
        if end is not None:
            return (list(curr_settled[end:]), False)
    return (list(curr_settled), True)


def _state_root() -> Path:
    """Root for journal/digest/cursor state. CMUX_WATCHDOG_HOME overrides the
    default (~/.cmux-watchdog) — used by tests to avoid touching real state."""
    override = os.environ.get("CMUX_WATCHDOG_HOME")
    return Path(override) if override else Path.home() / ".cmux-watchdog"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _journal_path(s: "SurfaceRef", date: str) -> Path:
    fname = f"{slugify(s.workspace_title)}__{slugify(s.title)}__{s.surface_ref}.log"
    return _state_root() / "journal" / date / fname


def journal_surface(s: "SurfaceRef", screen: str, prev_settled: dict[str, list[str]],
                    date: str) -> None:
    """Diff this surface's screen against its last snapshot and append only the
    newly-settled (already-redacted) lines to its daily journal. Updates the
    per-surface snapshot in place. Silent best-effort: nothing new → no write."""
    settled = settled_lines(screen)
    new, gap = append_new(prev_settled.get(s.surface_ref, []), settled)
    prev_settled[s.surface_ref] = settled
    if not new:
        return
    path = _journal_path(s, date)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"# {datetime.now().isoformat(timespec='seconds')}\n")
        if gap:
            fh.write("# <gap: lines may be missing>\n")
        for line in new:
            fh.write(line + "\n")


# --- journal sidecar index -------------------------------------------------
# The journal filename slugifies titles (lossy), but digest must resolve scope
# against the SAME identity fields filter_scope uses (workspace_ref AND raw
# workspace_title) so digest --workspace X selects exactly what watch --workspace
# X journaled. Slugs can't recover a raw title, and raw titles aren't filename-
# safe, so identity lives in a per-day sidecar index keyed by journal basename.


def _journal_index_path(date: str) -> Path:
    return _state_root() / "journal" / date / "index.json"


def _load_journal_index(date: str) -> dict[str, dict]:
    try:
        return json.loads(_journal_index_path(date).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def update_journal_index(date: str, surfaces: list[SurfaceRef]) -> None:
    """Upsert the day's identity index for the given surfaces; rewrite only when
    something changed. Cheap and idempotent — safe to call every watch tick."""
    path = _journal_index_path(date)
    idx = _load_journal_index(date)
    changed = False
    for s in surfaces:
        name = _journal_path(s, date).name
        entry = {
            "workspace_ref": s.workspace_ref,
            "workspace_title": s.workspace_title,
            "surface_ref": s.surface_ref,
            "title": s.title,
        }
        if idx.get(name) != entry:
            idx[name] = entry
            changed = True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(idx), encoding="utf-8")
        tmp.replace(path)


# --- digest: per-surface byte cursor over the journals ---------------------

def _cursors_path() -> Path:
    return _state_root() / "cursors.json"


def _load_cursors() -> dict[str, int]:
    try:
        return json.loads(_cursors_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cursors(cursors: dict[str, int]) -> None:
    path = _cursors_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(cursors), encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------
# Learned-resolution store — maps a granular api-error label to the action that
# previously fixed it. Once recorded, a recurring finding with that label is
# graduated risky -> safe so the agent auto-applies the proven fix instead of
# pausing for the human again. Lives next to the cursors at _state_root().
# --------------------------------------------------------------------------

def _resolutions_path() -> Path:
    return _state_root() / "resolutions.json"


def _load_resolutions() -> dict[str, str]:
    try:
        return json.loads(_resolutions_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_resolution(label: str, action: str) -> None:
    res = _load_resolutions()
    res[label] = action
    path = _resolutions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(res), encoding="utf-8")
    tmp.replace(path)


def apply_known_resolution(f: Finding, resolutions: dict[str, str]) -> Finding:
    """Pure: if this finding's granular label has a stored resolution, return a
    graduated copy (tier safe, remediation = the proven action, known_resolution
    annotated). Otherwise return the finding unchanged. No I/O — the caller loads
    the store once and passes it in, keeping detection testable against a dict."""
    action = resolutions.get(f.label)
    if not action:
        return f
    return replace(f, tier="safe", remediation=action, known_resolution=action)


def _scope_matches(ws_ref: str, ws_title: str, scope: str | None) -> bool:
    """Mirror filter_scope() exactly so digest selects the same workspaces watch
    journaled: token in {workspace_ref, workspace_title}, or 'all', or the
    CMUX_WORKSPACE_ID default (degrading to all when there is no anchor)."""
    if scope == "all":
        return True
    if not scope:
        scope = os.environ.get("CMUX_WORKSPACE_ID", "")
        if not scope:
            return True  # no anchor — degrade to all, as filter_scope does
    return scope in (ws_ref, ws_title)


# --------------------------------------------------------------------------
# Subcommand implementations
# --------------------------------------------------------------------------

def _row(s: SurfaceRef, f: Finding) -> dict:
    return {
        "surface_ref": s.surface_ref,
        "workspace_ref": s.workspace_ref,
        "workspace_title": s.workspace_title,
        "title": s.title,
        **asdict(f),
    }


def _scan_surfaces(scope: str | None) -> list[dict]:
    surfaces = filter_scope(parse_tree(_run_cmux("tree", "--all")), scope)
    controller = _controller_surface_ref()
    if controller:
        surfaces = [s for s in surfaces if s.surface_ref != controller]
    resolutions = _load_resolutions()
    candidates: list[dict] = []
    for s in surfaces:
        try:
            screen = read_screen(s.surface_ref, s.workspace_ref)
        except CmuxError:
            continue  # degrade per-surface; a browser/dead surface is not fatal
        for f in detect(screen):
            candidates.append(_row(s, apply_known_resolution(f, resolutions)))
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
    prev_settled: dict[str, list[str]] = {}
    print(json.dumps({
        "event": "watching",
        "scope": args.workspace or os.environ.get("CMUX_WORKSPACE_ID") or "all",
        "interval": args.interval,
    }), flush=True)
    last_summary = time.monotonic()
    controller = _controller_surface_ref()
    while True:
        try:
            surfaces = filter_scope(parse_tree(_run_cmux("tree", "--all")), args.workspace)
        except CmuxError as e:
            print(json.dumps({"event": "error", "error": str(e)}), flush=True)
            time.sleep(args.interval)
            continue
        if controller:
            # never scan or journal the watchdog's own controlling pane — it is
            # where these error strings get typed/discussed, a false-positive trap.
            surfaces = [s for s in surfaces if s.surface_ref != controller]
        resolutions = _load_resolutions()  # cheap; picks up new record-resolution writes
        date = _today()
        candidates: list[dict] = []
        for s in surfaces:
            try:
                # one deeper read per tick, fed to BOTH detectors and journaler
                screen = read_screen(s.surface_ref, s.workspace_ref, lines=200)
            except CmuxError:
                continue  # degrade per-surface; a dead/browser surface is not fatal
            for f in detect(screen):
                candidates.append(_row(s, apply_known_resolution(f, resolutions)))
            journal_surface(s, screen, prev_settled, date)
        update_journal_index(date, surfaces)
        current = {(c["surface_ref"], c["signature"]) for c in candidates}
        for c in candidates:
            key = (c["surface_ref"], c["signature"])
            if key not in seen:
                print(json.dumps({"event": "finding", **c}), flush=True)
        seen = current  # drop cleared findings so a recurrence re-emits
        now = time.monotonic()
        if args.summary_interval > 0 and now - last_summary >= args.summary_interval:
            print(json.dumps({
                "event": "summarize_due",
                "date": _today(),
                "elapsed": round(now - last_summary, 1),
            }), flush=True)
            last_summary = now
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


def cmd_resend(args: argparse.Namespace) -> int:
    """Self-verifying resend for a stalled agent: recall the last input (Up) and
    submit it (Enter), then confirm the agent resumed — an active marker appeared
    or the screen changed. Mirrors send-enter: safe to no-op, reports what it saw."""
    try:
        before = read_screen(args.surface, args.workspace)
        send_key(args.surface, args.workspace, "up")
        send_key(args.surface, args.workspace, "enter")
        time.sleep(0.4)
        after = read_screen(args.surface, args.workspace)
    except CmuxError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    resumed = bool(_ACTIVE_RE.search(after)) or after != before
    print(json.dumps({
        "ok": True,
        "action": "resend",
        "resumed": resumed,
        "surface_ref": args.surface,
        "note": "Agent resumed after resend (Up then Enter)." if resumed
                else "Resend sent (Up then Enter) but no activity detected; inspect the pane.",
    }))
    return 0


def cmd_record_resolution(args: argparse.Namespace) -> int:
    """Persist that <action> resolved a finding with granular <label>, so a future
    recurrence graduates risky -> safe and auto-applies <action>."""
    _save_resolution(args.label, args.action)
    print(json.dumps({"ok": True, "label": args.label, "action": args.action}))
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    """Write each in-scope surface's unread journal lines (stored cursor → EOF)
    to a digest file, advance and persist its cursor, and report what moved.
    Globs the journal dir so a since-dead surface is still summarizable."""
    date = args.date or _today()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        print(json.dumps({"ok": False,
                          "error": f"invalid --date {date!r}; expected YYYY-MM-DD"}))
        return 1
    scope = args.workspace
    journal_dir = _state_root() / "journal" / date
    digest_dir = _state_root() / "digests" / date
    cursors = _load_cursors()
    index = _load_journal_index(date)
    surfaces: list[dict] = []

    files = sorted(journal_dir.glob("*.log")) if journal_dir.is_dir() else []
    for jf in files:
        meta = index.get(jf.name)
        if meta:
            ws_ref = meta["workspace_ref"]
            ws_title = meta["workspace_title"]
            surface_ref = meta["surface_ref"]
            title = meta["title"]
        else:
            # no index entry (legacy/hand-made journal): fall back to filename
            # slugs — scope still resolves for 'all'/no-anchor, just not raw titles.
            parts = jf.name[: -len(".log")].rsplit("__", 2)
            if len(parts) != 3:
                continue  # not one of ours
            ws_slug, title, surface_ref = parts
            ws_ref, ws_title = "", ws_slug
        if not _scope_matches(ws_ref, ws_title, scope):
            continue

        key = str(jf)
        size = jf.stat().st_size
        start = cursors.get(key, 0)
        if start > size:
            start = 0  # file was truncated/rotated under us — reread from top
        with jf.open("rb") as fh:
            fh.seek(start)
            data = fh.read()
        if not data:
            continue  # 0 unread — skip, write no digest file
        to_cursor = start + len(data)
        text = data.decode("utf-8", errors="replace")

        digest_dir.mkdir(parents=True, exist_ok=True)
        # surface_ref + cursor range make the name collision-proof: two surfaces
        # sharing a ws/title slug, or the same surface digested twice in one
        # minute, never alias onto one file (which would break exact-once).
        digest_name = (f"{datetime.now().strftime('%H-%M')}__{slugify(ws_title)}__"
                       f"{slugify(title)}__{slugify(surface_ref)}__"
                       f"{start}-{to_cursor}.txt")
        digest_file = digest_dir / digest_name
        digest_file.write_text(text, encoding="utf-8")

        # persist the cursor per file (not once at the end) so a crash mid-run
        # leaves at most the in-flight surface to re-digest, never silently drops.
        cursors[key] = to_cursor
        _save_cursors(cursors)
        surfaces.append({
            "surface_ref": surface_ref,
            "workspace_title": ws_title,
            "title": title,
            "digest_file": str(digest_file),
            "unread_line_count": len(text.splitlines()),
            "from_cursor": start,
            "to_cursor": to_cursor,
        })

    print(json.dumps({
        "ok": True,
        "date": date,
        "scope": scope or os.environ.get("CMUX_WORKSPACE_ID") or "all",
        "surfaces": surfaces,
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
    wp.add_argument("--summary-interval", type=float, default=3600.0,
                    help="seconds between summarize_due events (0 disables)")
    wp.set_defaults(func=cmd_watch)

    dp = sub.add_parser("digest", help="flush unread journal lines to digest files")
    dp.add_argument("--workspace", default=None,
                    help="workspace ref/title, or 'all'. Default: caller workspace.")
    dp.add_argument("--date", default=None, help="YYYY-MM-DD. Default: today.")
    dp.set_defaults(func=cmd_digest)

    ep = sub.add_parser("send-enter", help="safe remediation for unsent_p2p")
    ep.add_argument("--surface", required=True)
    ep.add_argument("--workspace", required=True)
    ep.set_defaults(func=cmd_send_enter)

    rp = sub.add_parser("resend", help="recall last input (Up) and resubmit (Enter); self-verifying")
    rp.add_argument("--surface", required=True)
    rp.add_argument("--workspace", required=True)
    rp.set_defaults(func=cmd_resend)

    rr = sub.add_parser("record-resolution",
                        help="persist the action that resolved a granular api-error label")
    rr.add_argument("--label", required=True,
                    help="granular api-error label (server_5xx / overloaded / rate_limit / api_error / connection / timeout)")
    rr.add_argument("--action", required=True, help="the action that worked, e.g. resend")
    rr.set_defaults(func=cmd_record_resolution)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
