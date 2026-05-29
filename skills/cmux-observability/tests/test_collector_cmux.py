from pathlib import Path

from cmux_observability.collector.cmux import parse_tree


def test_parse_tree_basic(fixture_dir: Path):
    text = (fixture_dir / "cmux_tree_basic.txt").read_text()
    workspaces = parse_tree(text)
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
    workspaces = parse_tree(text)
    assert len(workspaces) == 1
    surfaces = workspaces[0].surfaces
    assert [s.ref for s in surfaces] == ["surface:67", "surface:68"]
    # title must be cleanly extracted despite ◀ active ◀ here annotations
    assert surfaces[0].title == "observability_designer"


from cmux_observability.collector.cmux import parse_top, TopResult


def test_parse_top_with_tags(fixture_dir):
    text = (fixture_dir / "cmux_top_with_tags.txt").read_text()
    result: TopResult = parse_top(text)

    assert set(result.tags_by_workspace.keys()) == {"workspace:12", "workspace:15"}
    tags12 = result.tags_by_workspace["workspace:12"]
    assert len(tags12) == 1
    assert tags12[0].kind == "claude_code"
    assert tags12[0].state == "Needs input"
    assert tags12[0].pid == 87611

    tags15 = result.tags_by_workspace["workspace:15"]
    assert tags15[0].kind == "claude_code"
    assert tags15[0].state == "Running"
    assert tags15[0].pid == 90828

    s39 = result.stats_by_surface["surface:39"]
    assert s39.cpu_pct == 1.1
    assert s39.mem_bytes == int(980.1 * 1024 * 1024)


def test_parse_top_no_tags_returns_empty_tag_map(fixture_dir):
    text = (fixture_dir / "cmux_top_no_tags.txt").read_text()
    result = parse_top(text)
    assert result.tags_by_workspace == {}
    assert "surface:39" in result.stats_by_surface


from pathlib import Path

from cmux_observability.collector.cmux import (
    fetch_tree, fetch_top, read_screen, cmux_version, CmuxUnavailable,
)


def test_fetch_tree_returns_parsed_workspaces(monkeypatch, fake_cmux, fixture_dir):
    monkeypatch.setenv("CMUX_FIXTURE_TREE", str(fixture_dir / "cmux_tree_basic.txt"))
    workspaces = fetch_tree()
    assert [w.ref for w in workspaces] == ["workspace:2", "workspace:17"]


def test_fetch_top_returns_parsed_top(monkeypatch, fake_cmux, fixture_dir):
    monkeypatch.setenv("CMUX_FIXTURE_TOP", str(fixture_dir / "cmux_top_with_tags.txt"))
    result = fetch_top()
    assert "workspace:12" in result.tags_by_workspace


def test_read_screen_passes_lines_and_returns_stdout(monkeypatch, fake_cmux, tmp_path):
    payload = tmp_path / "screen.txt"
    payload.write_text("line1\nline2\nline3\n")
    monkeypatch.setenv("CMUX_FIXTURE_READ_SCREEN", str(payload))
    out = read_screen("surface:1", lines=120)
    assert out == "line1\nline2\nline3\n"


def test_cmux_version_returns_stripped_string(monkeypatch, fake_cmux, tmp_path):
    payload = tmp_path / "version.txt"
    payload.write_text("  cmux 1.2.3\n\n")
    monkeypatch.setenv("CMUX_FIXTURE_VERSION", str(payload))
    assert cmux_version() == "cmux 1.2.3"


def test_fetch_tree_raises_cmux_unavailable_on_missing_binary(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    try:
        fetch_tree()
    except CmuxUnavailable:
        return
    raise AssertionError("expected CmuxUnavailable")


def test_read_screen_includes_workspace_when_provided(monkeypatch):
    """Live-smoke regression: cmux 0.64.10 `read-screen` requires
    `--workspace <ref>` alongside `--surface <ref>` to resolve a terminal
    surface. Without it, cmux errors with `Surface is not a terminal`.
    """
    captured: dict[str, tuple[str, ...]] = {}

    def fake_run_cmux(*args: str) -> str:
        captured["args"] = args
        return "screen text"

    monkeypatch.setattr(
        "cmux_observability.collector.cmux._run_cmux", fake_run_cmux
    )
    out = read_screen("surface:1", workspace_ref="workspace:1", lines=5)
    assert out == "screen text"

    args = list(captured["args"])
    assert args[0] == "read-screen"
    # --workspace must precede --surface (matches cmux CLI ordering).
    assert "--workspace" in args
    assert "--surface" in args
    ws_i = args.index("--workspace")
    sf_i = args.index("--surface")
    assert args[ws_i + 1] == "workspace:1"
    assert args[sf_i + 1] == "surface:1"
    assert ws_i < sf_i
    assert "--scrollback" in args
    assert "--lines" in args
    assert args[args.index("--lines") + 1] == "5"


def test_read_screen_omits_workspace_when_not_provided(monkeypatch):
    """Legacy path: callers (and fixtures) that don't pass workspace_ref
    must continue to produce the original arg vector — no --workspace."""
    captured: dict[str, tuple[str, ...]] = {}

    def fake_run_cmux(*args: str) -> str:
        captured["args"] = args
        return ""

    monkeypatch.setattr(
        "cmux_observability.collector.cmux._run_cmux", fake_run_cmux
    )
    read_screen("surface:9", lines=42)
    args = list(captured["args"])
    assert "--workspace" not in args
    assert args[0] == "read-screen"
    sf_i = args.index("--surface")
    assert args[sf_i + 1] == "surface:9"
    assert args[args.index("--lines") + 1] == "42"
