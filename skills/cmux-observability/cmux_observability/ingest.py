"""Ingest a watchdog capture envelope into a Snapshot — the deterministic
mapper that replaces the cmux collector.

This is the consuming half of the watchdog→observability contract. Observability
no longer reads cmux: watchdog's `snapshot` subcommand produces a versioned
capture envelope, and this module rebuilds the Snapshot *input* model from it
with ZERO cmux calls. Per the skill-boundary rule, observability never invokes
watchdog — the calling agent runs `watchdog.py snapshot` and pipes the envelope
in. The validator + this mapper are observability's own implementation of the
contract; the shared golden fixture keeps both sides honest.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime

from .errors import Failure
from .model import SCHEMA_VERSION, Agent, Snapshot, Surface, Workspace


# The capture envelope's own wire version (NOT Snapshot.schema_version, which
# versions the rendered/persisted model). Reject unsupported majors.
SUPPORTED_CAPTURE_MAJOR = 1


# Required (non-defaulted) fields per nested record. Kept in lockstep with the
# watchdog-side validator (capture.validate_envelope); the golden fixture is the
# shared contract test. Validating here means a malformed surface returns a clean
# {ok:false,error} from `collect` instead of crashing the dataclass mapper.
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


def validate_capture_envelope(env: dict) -> None:
    """Reject a capture envelope this build cannot safely consume. A mismatched
    MAJOR `capture_schema_version` is fatal, and so is any structurally malformed
    record (missing required nested fields) — both raise ValueError so `collect`
    returns a clean error rather than a traceback. Additive minor fields are
    tolerated by the field-filtering mapper below."""
    if not isinstance(env, dict):
        raise ValueError("capture envelope must be a JSON object")
    ver = env.get("capture_schema_version")
    if ver is None:
        raise ValueError("capture envelope missing capture_schema_version")
    if not isinstance(ver, int):
        raise ValueError(
            f"capture_schema_version must be an int, got {type(ver).__name__}"
        )
    if ver != SUPPORTED_CAPTURE_MAJOR:
        raise ValueError(
            f"unsupported capture_schema_version {ver}: this build speaks "
            f"v{SUPPORTED_CAPTURE_MAJOR}"
        )
    for key in ("workspaces", "agents", "captures"):
        if not isinstance(env.get(key), list):
            raise ValueError(f"capture envelope missing list field {key!r}")

    for i, w in enumerate(env["workspaces"]):
        _require(w, _REQUIRED_WORKSPACE, f"workspaces[{i}]")
        surfaces = w.get("surfaces", [])
        if not isinstance(surfaces, list):
            raise ValueError(f"workspaces[{i}].surfaces must be a list")
        for j, s in enumerate(surfaces):
            _require(s, _REQUIRED_SURFACE, f"workspaces[{i}].surfaces[{j}]")
    for i, a in enumerate(env["agents"]):
        _require(a, _REQUIRED_AGENT, f"agents[{i}]")
    for i, c in enumerate(env["captures"]):
        _require(c, _REQUIRED_CAPTURE, f"captures[{i}]")


_SURFACE_FIELDS = {f.name for f in fields(Surface)}
_AGENT_FIELDS = {f.name for f in fields(Agent)}


def _surface(d: dict) -> Surface:
    return Surface(**{k: v for k, v in d.items() if k in _SURFACE_FIELDS})


def _agent(d: dict) -> Agent:
    return Agent(**{k: v for k, v in d.items() if k in _AGENT_FIELDS})


def ingest(env: dict) -> tuple[Snapshot, dict[str, str], dict[str, dict]]:
    """Validate and rebuild the Snapshot input model from a capture envelope.

    Returns ``(snapshot, screens, redaction_meta)`` where:
      * ``screens`` maps surface_ref → the already-redacted scrollback watchdog
        captured (observability never sees raw text);
      * ``redaction_meta`` maps surface_ref → ``{screen_hash, redactions_applied}``
        — the authoritative cache key + redaction list watchdog computed.
    """
    validate_capture_envelope(env)

    workspaces = [
        Workspace(
            ref=w["ref"], title=w["title"], window_ref=w["window_ref"],
            surfaces=[_surface(s) for s in w.get("surfaces", [])],
        )
        for w in env["workspaces"]
    ]
    agents = [_agent(a) for a in env["agents"]]
    failures = [
        Failure(
            component=f["component"], target=f.get("target"),
            message=f["message"], fatal=f.get("fatal", False),
        )
        for f in env.get("failures", [])
    ]

    snap = Snapshot(
        schema_version=SCHEMA_VERSION,
        captured_at=datetime.fromisoformat(env["captured_at"]),
        host=env["host"],
        cmux_version=env.get("cmux_version"),
        workspaces=workspaces,
        agents=agents,
        themes=[],
        productivity=None,
        history=None,
        failures=failures,
    )

    screens = {c["surface_ref"]: c["redacted_scrollback"] for c in env["captures"]}
    redaction_meta = {
        c["surface_ref"]: {
            "screen_hash": c["screen_hash"],
            "redactions_applied": c.get("redactions_applied", []),
        }
        for c in env["captures"]
    }
    return snap, screens, redaction_meta
