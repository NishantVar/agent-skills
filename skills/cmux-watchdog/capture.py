"""Dashboard-oriented cmux capture + classification layer.

Watchdog is the single place that reads and classifies cmux. This module owns
the *dashboard* capture path (the `snapshot` subcommand): a full cross-workspace
parse of `tree --all` (terminals AND browsers), `top --all` (cmux tags +
cpu/mem), the cmux `version`, tag→surface pairing, heuristic type classification
of untagged terminals, and the v1.2 scrollback state ladder. The output is a
versioned capture envelope that observability rebuilds its Snapshot from with
zero cmux calls.

Pure by construction: every function here takes already-captured stdout strings
or an injected `read_screen` callable, so the whole layer unit-tests against
fixtures without a live cmux. The thin cmux subprocess wiring lives in
watchdog.py's `snapshot` command, which feeds this module.

Ported from observability's `collector/cmux.py` (parsers), `normalize.py` (tag
pairing) and `cli._classify_from_scrollback` (the state ladder) — consolidated
here so observability stops reading cmux.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from classify import classify_from_scrollback, state_from_scrollback
from redact import redact_meta, screen_hash


CAPTURE_SCHEMA_VERSION = 1


# --------------------------------------------------------------------------
# Models — mirror observability's Snapshot *input* model so the envelope maps
# 1:1 and observability rebuilds Workspace/Surface/Agent with no cmux calls.
# --------------------------------------------------------------------------


@dataclass
class CapSurface:
    ref: str
    pane_ref: str
    workspace_ref: str
    kind: str                                # "terminal" | "browser"
    title: str
    tty: str | None = None
    cwd: str | None = None                   # nullable: tree/top never populate it
    cpu_pct: float | None = None
    mem_bytes: int | None = None
    is_agent: bool = False


@dataclass
class CapWorkspace:
    ref: str
    title: str
    window_ref: str
    surfaces: list[CapSurface] = field(default_factory=list)


@dataclass
class CapAgent:
    surface_ref: str
    workspace_ref: str
    type: str                                # claude_code | codex | gemini | unknown_agent
    type_source: str                         # cmux_tag | heuristic
    type_confidence: float
    state: str                               # running | needs_input | idle | unknown
    state_source: str                        # cmux_tag | heuristic | scrollback
    pid: int | None = None


@dataclass
class CapFailure:
    component: str
    target: str | None
    message: str
    fatal: bool = False


@dataclass
class Capture:
    """Per-surface redacted scrollback + the metadata the summary contract needs.
    Observability never sees raw text — only this."""
    surface_ref: str
    redacted_scrollback: str
    screen_hash: str
    redactions_applied: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# tree --all parse — dashboard variant: keeps terminals AND browsers, plus
# pane_ref / window_ref / tty. (Ported from observability collector/cmux.py.)
# --------------------------------------------------------------------------

_WINDOW_RE    = re.compile(r"\bwindow (window:\d+)")
_WORKSPACE_RE = re.compile(r'\bworkspace (workspace:\d+)\s+"([^"]*)"')
_PANE_RE      = re.compile(r"\bpane (pane:\d+)")
_SURFACE_RE   = re.compile(
    r'\bsurface (surface:\d+)\s+\[(terminal|browser)\]\s+"([^"]*)"'
    r'(?:.*?\btty=(\S+))?'
)


def parse_tree(stdout: str) -> list[CapWorkspace]:
    """Parse `cmux tree --all` into Workspaces with their Surfaces attached.
    Pane refs are stored on each Surface for back-refs; browsers are kept."""
    workspaces: list[CapWorkspace] = []
    cur_window: str | None = None
    cur_workspace: CapWorkspace | None = None
    cur_pane_ref: str | None = None

    for raw in stdout.splitlines():
        line = raw.strip()
        if not line:
            continue

        m = _WINDOW_RE.search(line)
        if m and " workspace " not in line:
            cur_window = m.group(1)
            continue

        m = _WORKSPACE_RE.search(line)
        if m:
            cur_workspace = CapWorkspace(
                ref=m.group(1),
                title=m.group(2),
                window_ref=cur_window or "window:?",
                surfaces=[],
            )
            workspaces.append(cur_workspace)
            cur_pane_ref = None
            continue

        m = _PANE_RE.search(line)
        if m and " surface " not in line:
            cur_pane_ref = m.group(1)
            continue

        m = _SURFACE_RE.search(line)
        if m and cur_workspace is not None and cur_pane_ref is not None:
            ref, kind, title, tty = m.groups()
            cur_workspace.surfaces.append(CapSurface(
                ref=ref,
                pane_ref=cur_pane_ref,
                workspace_ref=cur_workspace.ref,
                kind=kind,
                title=title,
                tty=tty,
            ))

    return workspaces


# --------------------------------------------------------------------------
# top --all parse — cmux tags + per-surface cpu/mem. (Ported verbatim.)
# --------------------------------------------------------------------------


@dataclass
class TagLine:
    kind: str            # "claude_code" | "codex" | "gemini" | ...
    state: str           # raw cmux state string, e.g. "Running" / "Needs input"
    pid: int | None


@dataclass
class SurfaceStats:
    cpu_pct: float
    mem_bytes: int


@dataclass
class TopResult:
    tags_by_workspace: dict[str, list[TagLine]] = field(default_factory=dict)
    stats_by_surface: dict[str, SurfaceStats] = field(default_factory=dict)


_TOP_WORKSPACE_RE = re.compile(r"workspace (workspace:\d+)")
_TOP_TAG_RE       = re.compile(r'\btag\s+(\S+)\s+"([^"]+)"\s+pid=(\d+)')
_TOP_SURFACE_RE   = re.compile(
    r"^\s*([\d.]+)%\s+([\d.]+)\s+(KB|MB|GB|B)\s+\d+\s+.*\bsurface (surface:\d+)"
)


def _to_bytes(value: float, unit: str) -> int:
    mul = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}[unit]
    return int(value * mul)


def parse_top(stdout: str) -> TopResult:
    """Parse `cmux top --all`. `tag <kind> "<state>" pid=N` lines attach to the
    most recently seen workspace line."""
    result = TopResult()
    cur_workspace: str | None = None

    for raw in stdout.splitlines():
        m = _TOP_WORKSPACE_RE.search(raw)
        if m:
            cur_workspace = m.group(1)
            continue

        m = _TOP_TAG_RE.search(raw)
        if m and cur_workspace is not None:
            kind, state, pid_s = m.groups()
            result.tags_by_workspace.setdefault(cur_workspace, []).append(
                TagLine(kind=kind, state=state, pid=int(pid_s))
            )
            continue

        m = _TOP_SURFACE_RE.match(raw)
        if m:
            cpu_s, mem_s, unit, surface_ref = m.groups()
            result.stats_by_surface[surface_ref] = SurfaceStats(
                cpu_pct=float(cpu_s),
                mem_bytes=_to_bytes(float(mem_s), unit),
            )

    return result


# --------------------------------------------------------------------------
# Tag → surface pairing. (Ported from observability normalize.py.)
# --------------------------------------------------------------------------


def _normalize_state(raw: str) -> str:
    raw = raw.strip().lower()
    if raw == "running":
        return "running"
    if "input" in raw:
        return "needs_input"
    if raw in ("idle", "waiting"):
        return "idle"
    return "unknown"


def build_tag_agents(
    workspaces: list[CapWorkspace], top: TopResult,
) -> list[CapAgent]:
    """Attach cpu/mem to surfaces and create cmux_tag agents by pairing each tag
    with the most likely surface in its workspace. Untagged surfaces are NOT
    promoted here (the heuristic path handles those)."""
    for w in workspaces:
        for s in w.surfaces:
            stats = top.stats_by_surface.get(s.ref)
            if stats is not None:
                s.cpu_pct = stats.cpu_pct
                s.mem_bytes = stats.mem_bytes

    agents: list[CapAgent] = []
    workspace_index = {w.ref: w for w in workspaces}

    for ws_ref, tags in top.tags_by_workspace.items():
        ws = workspace_index.get(ws_ref)
        if ws is None:
            continue
        used: set[str] = set()
        # Tags only ever belong to terminal surfaces; browsers stay renderable
        # non-agent surfaces and must never be paired (parse_tree keeps browsers
        # in ws.surfaces, so both passes filter on kind == "terminal").
        terminals = [s for s in ws.surfaces if s.kind == "terminal"]
        for tag in tags:
            picked = None
            # Pass A: exact tag.kind match in the surface title.
            for s in terminals:
                if s.ref in used:
                    continue
                if tag.kind in s.title.lower():
                    picked = s
                    break
            # Pass B: fall back to the first unused terminal surface.
            if picked is None:
                for s in terminals:
                    if s.ref not in used:
                        picked = s
                        break
            if picked is None:
                continue
            used.add(picked.ref)
            picked.is_agent = True
            agents.append(CapAgent(
                surface_ref=picked.ref,
                workspace_ref=ws.ref,
                type=tag.kind,
                type_source="cmux_tag",
                type_confidence=1.0,
                state=_normalize_state(tag.state),
                state_source="cmux_tag",
                pid=tag.pid,
            ))

    return agents


# --------------------------------------------------------------------------
# Scrollback state ladder. (Ported from observability cli._classify_from_scrollback.)
# --------------------------------------------------------------------------


def classify_states_from_scrollback(
    agents: list[CapAgent], screens: dict[str, str], failures: list[CapFailure],
) -> None:
    """Apply the v1.2 scrollback state precedence ladder in place over `agents`.

    Skips agents with no entry in `screens`. Runs after heuristic promotion so
    heuristic-promoted agents (state=unknown) are considered. May append a
    non-fatal state_classifier Failure when scrollback overrides a cmux_tag.
    """
    for a in agents:
        tail = screens.get(a.surface_ref)
        if not tail:
            continue
        state, conf = state_from_scrollback(tail, a.type)
        if state == "unknown" or conf < 0.5:
            continue
        if a.state == "needs_input":
            # cmux_tag already detected the strongest user-impact signal.
            continue
        prior_state = a.state
        prior_source = a.state_source
        if state == "needs_input" and conf >= 0.7:
            if prior_source == "cmux_tag":
                failures.append(CapFailure(
                    component="state_classifier",
                    target=a.surface_ref,
                    message=(
                        f"scrollback overrode cmux_tag={prior_state!r} "
                        f"→ needs_input"
                    ),
                    fatal=False,
                ))
            a.state = "needs_input"
            a.state_source = "scrollback"
        elif a.state == "unknown" and conf >= 0.5:
            a.state = state
            a.state_source = "scrollback"


# --------------------------------------------------------------------------
# Scrollback byte cap — same tail-truncation contract observability shipped, so
# summary cache keys stay comparable. (Ported from summarize_io._truncate_scrollback.)
# --------------------------------------------------------------------------


def cap_scrollback(redacted: str, cap: int) -> str:
    """Cap `redacted` to at most `cap` bytes of UTF-8, keeping the tail. A
    trailer recording the pre-truncation byte length counts against the cap."""
    raw = redacted.encode("utf-8")
    if len(raw) <= cap:
        return redacted
    trailer = f"\n…[truncated, original {len(raw)} bytes]\n"
    trailer_bytes = trailer.encode("utf-8")
    body_budget = cap - len(trailer_bytes)
    if body_budget <= 0:
        return trailer_bytes[-cap:].decode("utf-8", errors="ignore")
    body = raw[-body_budget:].decode("utf-8", errors="ignore")
    return body + trailer


# --------------------------------------------------------------------------
# Orchestrator — the full capture/classification pass. Pure given an injected
# read_screen. Mirrors observability collect's classification portion exactly.
# --------------------------------------------------------------------------

# Heuristic promotion threshold: a single brand mention (confidence < 0.7) is
# too weak to drag a plain shell into the agent set.
_HEURISTIC_MIN_CONFIDENCE = 0.7


def classify_surfaces(
    *,
    workspaces: list[CapWorkspace],
    top: TopResult,
    read_screen,
    max_scrollback_bytes: int = 4096,
) -> tuple[list[CapAgent], list[Capture], list[CapFailure]]:
    """Run the full capture+classification pass.

    `read_screen(surface_ref, workspace_ref) -> str` is injected (may raise — a
    read failure degrades that surface only); the read depth (`--lines`) is
    baked into that closure by the caller. Returns (agents, captures,
    failures). `workspaces` is mutated in place (cpu/mem + is_agent flags).
    """
    failures: list[CapFailure] = []
    agents = build_tag_agents(workspaces, top)

    screens: dict[str, str] = {}

    # Read scrollback for tagged running/needs_input agents.
    for a in agents:
        if a.state in ("running", "needs_input"):
            try:
                screens[a.surface_ref] = read_screen(a.surface_ref, a.workspace_ref)
            except Exception as e:                       # degrade per-surface
                failures.append(CapFailure(
                    component="read_screen", target=a.surface_ref,
                    message=str(e), fatal=False,
                ))

    # Heuristic: classify untagged terminal surfaces from their scrollback.
    agent_refs = {a.surface_ref for a in agents}
    for w in workspaces:
        for s in w.surfaces:
            if s.ref in agent_refs or s.kind != "terminal":
                continue
            try:
                tail = read_screen(s.ref, s.workspace_ref)
            except Exception as e:                       # degrade per-surface
                failures.append(CapFailure(
                    component="read_screen", target=s.ref,
                    message=str(e), fatal=False,
                ))
                continue
            kind, confidence = classify_from_scrollback(tail)
            if kind is None or confidence < _HEURISTIC_MIN_CONFIDENCE:
                continue
            s.is_agent = True
            screens[s.ref] = tail
            agents.append(CapAgent(
                surface_ref=s.ref,
                workspace_ref=w.ref,
                type=kind,
                type_source="heuristic",
                type_confidence=confidence,
                state="unknown",
                state_source="heuristic",
                pid=None,
            ))

    # v1.2 scrollback state ladder (runs after heuristic promotion).
    classify_states_from_scrollback(agents, screens, failures)

    # Redact every read screen into a Capture (the sole place raw text exists).
    # screen_hash is computed over the CAPPED payload — the exact bytes that ship
    # to (and are summarized by) the agent — NOT the full pre-truncation read
    # that observability hashed before this consolidation. Intentional: the cache
    # key matches what the summarizer actually saw. Cache semantics shift only for
    # screens that exceed the byte cap — a change ABOVE the retained tail no longer
    # invalidates the summary, but the summarizer never saw that region anyway.
    captures: list[Capture] = []
    for ref, raw in screens.items():
        redacted, applied = redact_meta(raw)
        capped = cap_scrollback(redacted, max_scrollback_bytes)
        captures.append(Capture(
            surface_ref=ref,
            redacted_scrollback=capped,
            screen_hash=screen_hash(capped),
            redactions_applied=applied,
        ))

    return agents, captures, failures


# --------------------------------------------------------------------------
# Capture envelope — the versioned cross-skill wire contract.
# --------------------------------------------------------------------------


def build_envelope(
    *,
    workspaces: list[CapWorkspace],
    agents: list[CapAgent],
    captures: list[Capture],
    failures: list[CapFailure],
    host: str,
    cmux_version: str | None,
    captured_at: str,
    scope: str,
) -> dict:
    """Assemble the capture envelope dict (the watchdog→observability contract)."""
    return {
        "capture_schema_version": CAPTURE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "host": host,
        "cmux_version": cmux_version,
        "scope": scope,
        "workspaces": [asdict(w) for w in workspaces],
        "agents": [asdict(a) for a in agents],
        "captures": [asdict(c) for c in captures],
        "failures": [asdict(f) for f in failures],
    }


# Required (non-defaulted) fields per nested record. Kept in lockstep with the
# observability-side validator (ingest.py) — the golden fixture is the contract
# test that keeps both honest. Missing/mistyped nested fields raise ValueError
# here rather than crashing the downstream dataclass mapper with a TypeError.
_REQUIRED_WORKSPACE = ("ref", "title", "window_ref")
_REQUIRED_SURFACE = ("ref", "pane_ref", "workspace_ref", "kind", "title")
_REQUIRED_AGENT = (
    "surface_ref", "workspace_ref", "type", "type_source",
    "type_confidence", "state", "state_source",
)
_REQUIRED_CAPTURE = ("surface_ref", "redacted_scrollback", "screen_hash")


def _require(obj, fields, where: str) -> None:
    if not isinstance(obj, dict):
        raise ValueError(f"{where} must be a JSON object, got {type(obj).__name__}")
    for f in fields:
        if f not in obj:
            raise ValueError(f"{where} missing required field {f!r}")


def validate_envelope(envelope: dict) -> None:
    """Reject envelopes this reader can't safely consume. A mismatched MAJOR
    version is fatal, and so is any structurally malformed record (missing
    required nested fields) — both raise ValueError so callers return a clean
    error instead of crashing. Additive minor fields are tolerated."""
    if not isinstance(envelope, dict):
        raise ValueError("capture envelope must be a JSON object")
    ver = envelope.get("capture_schema_version")
    if ver is None:
        raise ValueError("capture envelope missing capture_schema_version")
    if not isinstance(ver, int):
        raise ValueError(
            f"capture_schema_version must be an int, got {type(ver).__name__}"
        )
    if ver != CAPTURE_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported capture_schema_version {ver}: this build speaks "
            f"v{CAPTURE_SCHEMA_VERSION}"
        )
    for key in ("workspaces", "agents", "captures"):
        if not isinstance(envelope.get(key), list):
            raise ValueError(f"capture envelope missing list field {key!r}")

    for i, w in enumerate(envelope["workspaces"]):
        _require(w, _REQUIRED_WORKSPACE, f"workspaces[{i}]")
        surfaces = w.get("surfaces", [])
        if not isinstance(surfaces, list):
            raise ValueError(f"workspaces[{i}].surfaces must be a list")
        for j, s in enumerate(surfaces):
            _require(s, _REQUIRED_SURFACE, f"workspaces[{i}].surfaces[{j}]")
    for i, a in enumerate(envelope["agents"]):
        _require(a, _REQUIRED_AGENT, f"agents[{i}]")
    for i, c in enumerate(envelope["captures"]):
        _require(c, _REQUIRED_CAPTURE, f"captures[{i}]")
