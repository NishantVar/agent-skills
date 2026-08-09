"""Load and validate catalog.yaml — the machine-readable disruption catalog."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

VALID_CLASSIFICATIONS = {"pass_fail", "probe"}


@dataclass
class RunSettings:
    max_hops_per_step: int
    step_timeout_seconds: int
    ttl_seconds: int


@dataclass
class Step:
    id: int
    name: str
    classification: str
    prime: list[dict[str, Any]] = field(default_factory=list)
    pre_actions: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    assertions: list[dict[str, Any]] = field(default_factory=list)
    post_recovery_actions: list[dict[str, Any]] = field(default_factory=list)
    post_recovery_assertions: list[dict[str, Any]] = field(default_factory=list)
    cleanup: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Catalog:
    run_settings: RunSettings
    steps: list[Step]


def load_catalog(path: Path) -> Catalog:
    data = yaml.safe_load(path.read_text())
    rs = RunSettings(**data["run_settings"])
    steps = [Step(**s) for s in data["steps"]]
    return Catalog(run_settings=rs, steps=steps)


def validate_catalog(cat: Catalog) -> None:
    if not cat.steps:
        raise ValueError("catalog has no steps")
    prev_id = 0
    for s in cat.steps:
        if s.classification not in VALID_CLASSIFICATIONS:
            raise ValueError(
                f"step {s.id} ({s.name}) has invalid classification {s.classification!r}; "
                f"must be one of {sorted(VALID_CLASSIFICATIONS)}"
            )
        if s.id != prev_id + 1:
            raise ValueError(f"step id gap: expected {prev_id + 1}, got {s.id}")
        prev_id = s.id
