"""Put the skill directory on the import path so `import p2plib` works,
and isolate the registry to a per-test temp directory so tests can
mutate it without touching the user's real ~/.cmux/agents."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
for _path in (_HERE.parent, _HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


@pytest.fixture
def tmp_registry(tmp_path, monkeypatch):
    """Point p2plib.registry at a fresh per-test directory."""
    from p2plib import registry

    reg = tmp_path / "by-surface"
    reg.mkdir()
    monkeypatch.setattr(registry, "REGISTRY", reg)
    monkeypatch.setattr(registry, "LOCK_PATH", reg / ".lock")
    return reg
