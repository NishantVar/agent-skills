"""Tests for the dashboard capture/classification layer.

Ported from observability's test_collector_cmux.py (parsers),
test_normalize.py (tag pairing), and test_classifier_integration.py
(end-to-end ladder) — the migrated safety net for the consolidated layer.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import capture as cap  # noqa: E402


SCROLLBACK = Path(__file__).parent / "fixtures" / "scrollback"


# --- parse_tree -----------------------------------------------------------

def test_parse_tree_basic(fixture_dir: Path):
    text = (fixture_dir / "cmux_tree_basic.txt").read_text()
    workspaces = cap.parse_tree(text)
    assert [w.ref for w in workspaces] == ["workspace:2", "workspace:17"]

    meta = workspaces[0]
    assert meta.title == "Meta Eval"
    assert meta.window_ref == "window:1"
    assert [s.ref for s in meta.surfaces] == ["surface:2", "surface:3"]
    s2 = meta.surfaces[0]
    assert s2.kind == "terminal"
    assert s2.title == "design_coordinator"
    assert s2.tty == "ttys005"
    assert s2.pane_ref == "pane:2"
    assert s2.workspace_ref == "workspace:2"


def test_parse_tree_handles_focused_active_here_annotations(fixture_dir: Path):
    text = (fixture_dir / "cmux_tree_renamed.txt").read_text()
    workspaces = cap.parse_tree(text)
    assert len(workspaces) == 1
    surfaces = workspaces[0].surfaces
    assert [s.ref for s in surfaces] == ["surface:67", "surface:68"]
    assert surfaces[0].title == "observability_designer"


def test_parse_tree_keeps_browser_surfaces():
    text = (
        'window window:1\n'
        '├── workspace workspace:1 "WS"\n'
        '│   ├── pane pane:1\n'
        '│   │   └── surface surface:1 [terminal] "term" tty=ttys001\n'
        '│   └── pane pane:2\n'
        '│       └── surface surface:2 [browser] "Docs"\n'
    )
    workspaces = cap.parse_tree(text)
    kinds = {s.ref: s.kind for s in workspaces[0].surfaces}
    assert kinds == {"surface:1": "terminal", "surface:2": "browser"}


# --- parse_top ------------------------------------------------------------

def test_parse_top_with_tags(fixture_dir: Path):
    text = (fixture_dir / "cmux_top_with_tags.txt").read_text()
    result = cap.parse_top(text)
    assert set(result.tags_by_workspace.keys()) == {"workspace:12", "workspace:15"}
    tags12 = result.tags_by_workspace["workspace:12"]
    assert tags12[0].kind == "claude_code"
    assert tags12[0].state == "Needs input"
    assert tags12[0].pid == 87611
    s39 = result.stats_by_surface["surface:39"]
    assert s39.cpu_pct == 1.1
    assert s39.mem_bytes == int(980.1 * 1024 * 1024)


def test_parse_top_no_tags_returns_empty_tag_map(fixture_dir: Path):
    text = (fixture_dir / "cmux_top_no_tags.txt").read_text()
    result = cap.parse_top(text)
    assert result.tags_by_workspace == {}
    assert "surface:39" in result.stats_by_surface


# --- build_tag_agents (normalize pairing) ---------------------------------

def test_build_tag_agents_attaches_type_and_state(fixture_dir: Path):
    tree = cap.parse_tree((fixture_dir / "cmux_tree_with_tagged_ws.txt").read_text())
    top = cap.parse_top((fixture_dir / "cmux_top_with_tags.txt").read_text())
    agents = cap.build_tag_agents(tree, top)
    assert len(agents) == 2

    a12 = next(a for a in agents if a.workspace_ref == "workspace:12")
    assert a12.surface_ref == "surface:39"
    assert a12.type == "claude_code"
    assert a12.type_source == "cmux_tag"
    assert a12.type_confidence == 1.0
    assert a12.state == "needs_input"
    assert a12.state_source == "cmux_tag"
    assert a12.pid == 87611

    a15 = next(a for a in agents if a.workspace_ref == "workspace:15")
    assert a15.state == "running"
    assert a15.pid == 90828


def test_build_tag_agents_does_not_promote_untagged(fixture_dir: Path):
    tree = cap.parse_tree((fixture_dir / "cmux_tree_basic.txt").read_text())
    top = cap.parse_top((fixture_dir / "cmux_top_no_tags.txt").read_text())
    agents = cap.build_tag_agents(tree, top)
    assert agents == []


def test_build_tag_agents_prefers_exact_kind_match():
    s_generic = cap.CapSurface(
        ref="surface:88a", pane_ref="pane:88a", workspace_ref="workspace:88",
        kind="terminal", title="agent notes",
    )
    s_exact = cap.CapSurface(
        ref="surface:88b", pane_ref="pane:88b", workspace_ref="workspace:88",
        kind="terminal", title="claude_code worker",
    )
    ws = cap.CapWorkspace(
        ref="workspace:88", title="W88", window_ref="window:1",
        surfaces=[s_generic, s_exact],
    )
    top = cap.TopResult(
        tags_by_workspace={
            "workspace:88": [cap.TagLine(kind="claude_code", state="Running", pid=99999)],
        },
    )
    agents = cap.build_tag_agents([ws], top)
    assert len(agents) == 1
    assert agents[0].surface_ref == "surface:88b"
    assert agents[0].state == "running"


def test_build_tag_agents_skips_browser_surfaces():
    """A browser that sorts before the terminal must NOT be tag-paired: the tag
    lands on the terminal and the browser stays a non-agent surface."""
    browser = cap.CapSurface(
        ref="surface:b", pane_ref="pane:b", workspace_ref="workspace:9",
        kind="browser", title="Docs",
    )
    terminal = cap.CapSurface(
        ref="surface:t", pane_ref="pane:t", workspace_ref="workspace:9",
        kind="terminal", title="worker",
    )
    ws = cap.CapWorkspace(
        ref="workspace:9", title="W9", window_ref="window:1",
        surfaces=[browser, terminal],   # browser first → fallback would pick it
    )
    top = cap.TopResult(
        tags_by_workspace={
            "workspace:9": [cap.TagLine(kind="claude_code", state="Running", pid=7)],
        },
    )
    agents = cap.build_tag_agents([ws], top)
    assert len(agents) == 1
    assert agents[0].surface_ref == "surface:t"   # terminal, NOT the browser
    assert browser.is_agent is False
    assert terminal.is_agent is True


# --- classify_surfaces end-to-end (tagged + heuristic + plain shell) ------

def test_classify_surfaces_tagged_plus_heuristic_plus_plain_shell():
    ws_a = cap.CapWorkspace(
        ref="workspace:1", title="Tagged WS", window_ref="window:1",
        surfaces=[cap.CapSurface(
            ref="surface:A", pane_ref="pane:1", workspace_ref="workspace:1",
            kind="terminal", title="claude_code worker",
        )],
    )
    ws_b = cap.CapWorkspace(
        ref="workspace:2", title="Heuristic Claude WS", window_ref="window:1",
        surfaces=[cap.CapSurface(
            ref="surface:B", pane_ref="pane:2", workspace_ref="workspace:2",
            kind="terminal", title="some-tab",
        )],
    )
    ws_c = cap.CapWorkspace(
        ref="workspace:3", title="Heuristic Codex WS", window_ref="window:1",
        surfaces=[cap.CapSurface(
            ref="surface:C", pane_ref="pane:3", workspace_ref="workspace:3",
            kind="terminal", title="another-tab",
        )],
    )
    ws_d = cap.CapWorkspace(
        ref="workspace:4", title="Plain WS", window_ref="window:1",
        surfaces=[cap.CapSurface(
            ref="surface:D", pane_ref="pane:4", workspace_ref="workspace:4",
            kind="terminal", title="shell",
        )],
    )
    workspaces = [ws_a, ws_b, ws_c, ws_d]
    top = cap.TopResult(
        tags_by_workspace={
            "workspace:1": [cap.TagLine(kind="claude_code", state="Running", pid=4242)],
        },
    )

    claude_sb = (SCROLLBACK / "claude_code.txt").read_text()
    codex_sb = (SCROLLBACK / "codex.txt").read_text()
    plain_sb = (SCROLLBACK / "plain_shell.txt").read_text()

    def fake_read_screen(surface_ref, workspace_ref):
        return {
            "surface:A": "tagged agent screen\n" + claude_sb,
            "surface:B": claude_sb,
            "surface:C": codex_sb,
            "surface:D": plain_sb,
        }.get(surface_ref, "")

    agents, captures, failures = cap.classify_surfaces(
        workspaces=workspaces, top=top, read_screen=fake_read_screen,
    )

    by_ref = {a.surface_ref: a for a in agents}
    assert set(by_ref) == {"surface:A", "surface:B", "surface:C"}
    assert "surface:D" not in by_ref  # plain shell never promoted

    assert by_ref["surface:A"].type_source == "cmux_tag"
    assert by_ref["surface:B"].type == "claude_code"
    assert by_ref["surface:B"].type_source == "heuristic"
    assert by_ref["surface:B"].type_confidence >= 0.7
    assert by_ref["surface:C"].type == "codex"
    assert by_ref["surface:C"].type_source == "heuristic"

    # D's surface stays in the workspace tree (just not an agent).
    refs = {s.ref for w in workspaces for s in w.surfaces}
    assert "surface:D" in refs

    # captures cover exactly the read agent surfaces.
    assert {c.surface_ref for c in captures} == {"surface:A", "surface:B", "surface:C"}


def test_classify_surfaces_redacts_scrollback_in_captures():
    ws = cap.CapWorkspace(
        ref="workspace:1", title="WS", window_ref="window:1",
        surfaces=[cap.CapSurface(
            ref="surface:1", pane_ref="pane:1", workspace_ref="workspace:1",
            kind="terminal", title="claude_code worker",
        )],
    )
    top = cap.TopResult(
        tags_by_workspace={
            "workspace:1": [cap.TagLine(kind="claude_code", state="Running", pid=1)],
        },
    )
    secret = "sk-ABCDEFGHIJKLMNOPQRSTUVWX"

    def fake_read_screen(surface_ref, workspace_ref):
        return f"some output\ntoken {secret}\n"

    _agents, captures, _failures = cap.classify_surfaces(
        workspaces=[ws], top=top, read_screen=fake_read_screen,
    )
    [c] = captures
    assert secret not in c.redacted_scrollback
    assert "SK_TOKEN:1" in c.redactions_applied
    assert len(c.screen_hash) == 64


def test_screen_hash_is_over_capped_payload():
    """Pin the documented cache semantics: screen_hash == sha256(capped redacted
    payload), NOT the full pre-truncation read. A screen over the byte cap hashes
    only the retained tail that ships to the summarizer."""
    import hashlib
    import redact as r

    ws = cap.CapWorkspace(
        ref="workspace:1", title="WS", window_ref="window:1",
        surfaces=[cap.CapSurface(
            ref="surface:1", pane_ref="pane:1", workspace_ref="workspace:1",
            kind="terminal", title="claude_code worker",
        )],
    )
    top = cap.TopResult(
        tags_by_workspace={
            "workspace:1": [cap.TagLine(kind="claude_code", state="Running", pid=1)],
        },
    )
    big = "line\n" * 5000  # well over the cap

    def reader(surface_ref, workspace_ref):
        return big

    _agents, captures, _failures = cap.classify_surfaces(
        workspaces=[ws], top=top, read_screen=reader, max_scrollback_bytes=512,
    )
    [c] = captures
    assert len(c.redacted_scrollback.encode("utf-8")) <= 512   # capped
    # Hash is over the capped payload exactly.
    expected = hashlib.sha256(c.redacted_scrollback.encode("utf-8")).hexdigest()
    assert c.screen_hash == expected == r.screen_hash(c.redacted_scrollback)
    # And NOT over the full redacted read.
    full_redacted, _ = r.redact_meta(big)
    assert c.screen_hash != r.screen_hash(full_redacted)


def test_read_failure_degrades_per_surface():
    ws = cap.CapWorkspace(
        ref="workspace:1", title="WS", window_ref="window:1",
        surfaces=[cap.CapSurface(
            ref="surface:1", pane_ref="pane:1", workspace_ref="workspace:1",
            kind="terminal", title="claude_code worker",
        )],
    )
    top = cap.TopResult(
        tags_by_workspace={
            "workspace:1": [cap.TagLine(kind="claude_code", state="Running", pid=1)],
        },
    )

    def boom(surface_ref, workspace_ref):
        raise RuntimeError("cmux read failed")

    agents, captures, failures = cap.classify_surfaces(
        workspaces=[ws], top=top, read_screen=boom,
    )
    assert len(agents) == 1            # tag agent still present
    assert captures == []              # no screen captured
    assert any(f.component == "read_screen" for f in failures)


# --- state ladder disagreement failure ------------------------------------

def test_state_ladder_emits_failure_on_cmux_tag_override():
    agent = cap.CapAgent(
        surface_ref="surface:1", workspace_ref="workspace:1",
        type="claude_code", type_source="cmux_tag", type_confidence=1.0,
        state="running", state_source="cmux_tag", pid=1,
    )
    # Scrollback with a strong needs_input signal.
    screens = {"surface:1": "Do you want to proceed?\n  1. yes\n  2. no\n"}
    failures: list[cap.CapFailure] = []
    cap.classify_states_from_scrollback([agent], screens, failures)
    assert agent.state == "needs_input"
    assert agent.state_source == "scrollback"
    assert any(f.component == "state_classifier" for f in failures)


# --- envelope build + validate --------------------------------------------

def test_build_and_validate_envelope_roundtrip():
    env = cap.build_envelope(
        workspaces=[], agents=[], captures=[], failures=[],
        host="laptop", cmux_version="cmux 1.2.3",
        captured_at="2026-06-04T00:00:00+00:00", scope="all",
    )
    assert env["capture_schema_version"] == cap.CAPTURE_SCHEMA_VERSION
    cap.validate_envelope(env)  # must not raise


def test_validate_envelope_rejects_bad_major():
    env = cap.build_envelope(
        workspaces=[], agents=[], captures=[], failures=[],
        host="h", cmux_version=None, captured_at="t", scope="all",
    )
    env["capture_schema_version"] = cap.CAPTURE_SCHEMA_VERSION + 1
    try:
        cap.validate_envelope(env)
    except ValueError:
        return
    raise AssertionError("expected ValueError on unsupported major version")


def test_validate_envelope_rejects_missing_version():
    try:
        cap.validate_envelope({"workspaces": [], "agents": [], "captures": []})
    except ValueError:
        return
    raise AssertionError("expected ValueError on missing version")


def test_validate_envelope_rejects_malformed_surface():
    """A surface missing a required field (pane_ref) must raise ValueError, not
    let a downstream mapper crash with TypeError."""
    env = cap.build_envelope(
        workspaces=[cap.CapWorkspace(ref="workspace:1", title="W", window_ref="window:1")],
        agents=[], captures=[], failures=[],
        host="h", cmux_version=None, captured_at="t", scope="all",
    )
    # Drop a required field from the surface.
    env["workspaces"][0]["surfaces"] = [{
        "ref": "surface:1", "workspace_ref": "workspace:1",
        "kind": "terminal", "title": "x",   # missing pane_ref
    }]
    try:
        cap.validate_envelope(env)
    except ValueError as e:
        assert "pane_ref" in str(e)
        return
    raise AssertionError("expected ValueError on malformed surface")
