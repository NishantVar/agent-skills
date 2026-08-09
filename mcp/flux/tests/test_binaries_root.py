"""Guard the gateway's default binaries root after the mcp/flux relocation.

The gateway subprocesses p2p/afork/tfork resolved against DEFAULT_BINARIES_ROOT.
If the relocation's path math is wrong, this resolves to the wrong dir and the
wrapped binaries silently can't be found. Pin it to the repo's skills/ tree.
"""

from fluxmcplib import gateway


def test_default_binaries_root_points_at_repo_skills():
    root = gateway.DEFAULT_BINARIES_ROOT
    assert root.name == "skills", f"expected skills/, got {root}"
    # The three wrapped binaries must be resolvable under it.
    assert (root / "p2p" / "agent_msg.py").is_file()
    assert (root / "afork" / "afork.py").is_file()
    assert (root / "tfork" / "fork_terminal.py").is_file()
