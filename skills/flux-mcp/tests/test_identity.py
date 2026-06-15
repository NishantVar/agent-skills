import json
import subprocess
import sys
from pathlib import Path

from fluxmcplib import gateway, registry

# Make p2plib importable the same way the gateway does at runtime.
P2P_DIR = Path(__file__).resolve().parents[2] / "p2p"
sys.path.insert(0, str(P2P_DIR))
from p2plib import surface  # noqa: E402


def _completed(stdout):
    return subprocess.CompletedProcess([], 0, stdout, "")


def test_my_surface_trusts_tty_over_stale_identify(monkeypatch):
    # Forked-agent case: `cmux identify` reports a STALE surface, but the
    # controlling-tty walk reports the TRUE one. my_surface() must return tty.
    monkeypatch.delenv("AGENT_MSG_SURFACE_ID", raising=False)
    monkeypatch.setattr(
        surface, "_run",
        lambda *a, **k: _completed('{"caller": {"surface_ref": "surface:STALE"}}'),
    )
    monkeypatch.setattr(surface, "cmux_tree", lambda: {})
    monkeypatch.setattr(surface, "_surface_from_tty_walk",
                        lambda tree=None: "surface:TRUE")
    assert surface.my_surface() == "surface:TRUE"


def test_my_surface_honors_explicit_override(monkeypatch):
    # An explicit AGENT_MSG_SURFACE_ID short-circuits everything — this is the
    # var the flux-mcp gateway injects, so the server's resolution is authoritative.
    monkeypatch.setenv("AGENT_MSG_SURFACE_ID", "surface:OVERRIDE")
    assert surface.my_surface() == "surface:OVERRIDE"


def test_gateway_injects_resolved_surface_into_both_env_vars(fake_binaries):
    # A forked agent: resolve_surface yields the tty-corrected surface; the
    # gateway must inject THAT into both env vars, regardless of any stale value.
    rec = json.loads(gateway.run_tool(
        registry.TOOLS["p2p"], {"message": "x", "peer": "lead"},
        binaries_root=fake_binaries,
        resolve_surface=lambda: "surface:TRUE",
    ))
    assert rec["env_AGENT_MSG_SURFACE_ID"] == "surface:TRUE"
    assert rec["env_TFORK_SURFACE_ID"] == "surface:TRUE"
