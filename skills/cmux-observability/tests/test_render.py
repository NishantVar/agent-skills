from datetime import datetime, timezone
from pathlib import Path

from cmux_observability.errors import Failure
from cmux_observability.model import (
    Agent,
    Productivity,
    RepoStats,
    Snapshot,
    Summary,
    Surface,
    Theme,
    Workspace,
)
from cmux_observability.render.render import render_snapshot


def _snap_empty() -> Snapshot:
    return Snapshot(
        schema_version=1,
        captured_at=datetime(2026, 5, 27, 14, 30, 0, tzinfo=timezone.utc),
        host="laptop",
        cmux_version="1.2.3",
        workspaces=[],
        agents=[],
        themes=[],
        productivity=None,
        history=None,
        failures=[],
    )


def _snap_populated(
    *,
    summary_text: str = "writing pytest fixtures",
    theme_label: str = "testing",
    ws_title: str = "Project A",
) -> Snapshot:
    surface = Surface(
        ref="surface:1",
        pane_ref="pane:1",
        workspace_ref="workspace:1",
        kind="terminal",
        title="claude_code worker",
        tty="ttys001",
        cwd="/home/u/p",
        cpu_pct=12.3,
        mem_bytes=104857600,
        is_agent=True,
    )
    workspace = Workspace(
        ref="workspace:1",
        title=ws_title,
        window_ref="window:1",
        surfaces=[surface],
    )
    summary = Summary(
        text=summary_text,
        state_hint="running",
        needs_input_reason=None,
        confidence=0.9,
        cache_hit=False,
        cached_at=datetime(2026, 5, 27, 14, 29, 0, tzinfo=timezone.utc),
        prompt_version=1,
        screen_hash="dead",
        redactions_applied=["SK_TOKEN:1"],
        redaction_summary="SK_TOKEN:1",
    )
    agent = Agent(
        surface_ref="surface:1",
        workspace_ref="workspace:1",
        type="claude_code",
        type_source="cmux_tag",
        type_confidence=1.0,
        state="running",
        state_source="cmux_tag",
        pid=42,
        summary=summary,
    )
    theme = Theme(
        label=theme_label,
        member_refs=["surface:1"],
        why="agent is writing fixtures",
        confidence=0.85,
    )
    failure = Failure(component="collector", target="cmux", message="tree timeout")
    productivity = Productivity(
        repos=[
            RepoStats(
                path="/home/u/p",
                name="p",
                commits={"today": 3, "week": 7, "30d": 21},
                last_commit_at=datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc),
            )
        ],
        totals={"today": 3, "week": 7, "30d": 21},
    )
    return Snapshot(
        schema_version=1,
        captured_at=datetime(2026, 5, 27, 14, 30, 0, tzinfo=timezone.utc),
        host="laptop",
        cmux_version="1.2.3",
        workspaces=[workspace],
        agents=[agent],
        themes=[theme],
        productivity=productivity,
        history=None,
        failures=[failure],
    )


def test_render_empty_snapshot_is_self_contained_and_modern_doc(tmp_path: Path):
    snap = _snap_empty()
    html_path, json_path = render_snapshot(snap, tmp_path)
    assert html_path.exists() and html_path.suffix == ".html"
    assert json_path.exists() and json_path.suffix == ".json"
    html = html_path.read_text()

    # Document skeleton (instruction #2)
    assert "<!doctype html>" in html.lower()
    assert '<html lang="en"' in html
    assert '<meta name="viewport"' in html
    assert '<meta name="color-scheme" content="light dark">' in html

    # CSS modernization (instruction #2)
    assert "color-scheme: light dark" in html
    assert "@media (prefers-color-scheme: dark)" in html
    assert "@media print" in html

    # Self-contained: reject external resources (instruction #6)
    for needle in (
        "http://",
        "https://",
        "//cdn.",
        '<link rel="stylesheet"',
        '<script src=',
    ):
        assert needle not in html, f"unexpected external resource: {needle!r}"

    # Graceful empty state
    assert "cmux observability" in html.lower()
    assert "No agents detected" in html


def test_render_populated_snapshot_exercises_all_partials(tmp_path: Path):
    snap = _snap_populated()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # _workspace + _agent_row
    assert "workspace:1" in html
    assert "Project A" in html
    assert "surface:1" in html
    assert "claude_code worker" in html
    assert "running" in html
    assert "12.3" in html              # cpu_pct
    assert "100.0 MB" in html          # 104857600 / 1024 / 1024
    assert "writing pytest fixtures" in html
    # _themes
    assert "testing" in html
    assert "agent is writing fixtures" in html
    # _productivity
    assert "Productivity" in html
    assert ">3<" in html or ">3 " in html or ">3\n" in html  # today count rendered
    assert ">7<" in html or ">7 " in html or ">7\n" in html
    # _failures
    assert "tree timeout" in html
    assert "collector" in html
    # inline style attributes are gone (instruction #1)
    assert "<h3 style=" not in html       # no inline styles on headings
    assert "onclick=" not in html         # no inline event handlers
    assert "card-title" in html           # the replacement class is wired in


def test_render_inlines_trusted_css_and_js_unescaped(tmp_path: Path):
    snap = _snap_empty()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # CSS selector survives intact (not entity-encoded)
    assert "details>summary" in html
    assert "details&gt;summary" not in html

    # JS source survives intact
    assert 'var blocks = ["' in html
    assert "&#34;" not in html

    # Sparkline span selector in JS must not be entity-encoded
    assert "&lt;span data-sparkline" not in html


def test_render_inline_theme_tokens_and_dark_mode(tmp_path: Path):
    """T7: snapshot.html.j2 ships an inline <style> block with theme tokens
    (light + dark + state) and a prefers-reduced-motion override."""
    snap = _snap_empty()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Mandatory state tokens
    for token in (
        "--state-running",
        "--state-needs-input",
        "--state-idle",
        "--state-unknown",
    ):
        assert token in html, f"missing state token: {token}"

    # Mandatory surface/text/spacing tokens
    for token in ("--bg", "--surface", "--text", "--muted", "--border"):
        assert token in html, f"missing surface token: {token}"

    # Dark theme media query present
    assert "@media (prefers-color-scheme: dark)" in html

    # Reduced-motion override present
    assert "prefers-reduced-motion: reduce" in html


def test_render_escapes_user_provided_strings(tmp_path: Path):
    snap = _snap_populated(
        summary_text="<script>alert(1)</script>",
        theme_label="<script>alert(1)</script>",
        ws_title="<script>alert(1)</script>",
    )
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Raw <script> from user content must NOT appear
    assert "<script>alert(1)</script>" not in html
    # Escaped form MUST appear (Jinja autoescape produces &lt;script&gt;…)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def _snap_hero_fixture() -> Snapshot:
    """Fixture sized for T8 hero strip: 4 workspaces, 41 surfaces, 17 agents
    (2 tagged + 15 heuristic), 3 needs_input, 12 running, 1 idle, 1 unknown."""
    workspaces: list[Workspace] = []
    surface_idx = 0
    # Distribute 41 surfaces across 4 workspaces: 10, 10, 10, 11.
    per_ws = [10, 10, 10, 11]
    for w_i, count in enumerate(per_ws, start=1):
        ws_ref = f"workspace:{w_i}"
        surfaces: list[Surface] = []
        for _ in range(count):
            surface_idx += 1
            surfaces.append(Surface(
                ref=f"surface:{surface_idx}",
                pane_ref=f"pane:{surface_idx}",
                workspace_ref=ws_ref,
                kind="terminal",
                title=f"surface {surface_idx}",
            ))
        workspaces.append(Workspace(
            ref=ws_ref,
            title=f"Workspace {w_i}",
            window_ref=f"window:{w_i}",
            surfaces=surfaces,
        ))

    # Agents: 2 tagged (cmux_tag), 15 heuristic. States: 12 running, 3 needs_input,
    # 1 idle, 1 unknown (totals to 17).
    states = (
        ["running"] * 12
        + ["needs_input"] * 3
        + ["idle"] * 1
        + ["unknown"] * 1
    )
    assert len(states) == 17
    type_sources = ["cmux_tag"] * 2 + ["heuristic"] * 15
    agents: list[Agent] = []
    for i, (state, src) in enumerate(zip(states, type_sources), start=1):
        agents.append(Agent(
            surface_ref=f"surface:{i}",
            workspace_ref="workspace:1",
            type="claude_code",
            type_source=src,
            type_confidence=0.9,
            state=state,
            state_source=src,
        ))

    return Snapshot(
        schema_version=1,
        captured_at=datetime(2026, 5, 27, 14, 30, 0, tzinfo=timezone.utc),
        host="laptop",
        cmux_version="1.2.3",
        workspaces=workspaces,
        agents=agents,
        themes=[],
        productivity=None,
        history=None,
        failures=[],
    )


def test_render_hero_strip_counters_and_layout(tmp_path: Path):
    """T8: sticky hero strip with 7 big-number counters, agents breakdown,
    captured-at + refresh hint, and a placeholder search input."""
    snap = _snap_hero_fixture()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Sticky positioning on hero
    assert "position: sticky" in html
    # Hero wrapper exists (class hook for CSS + JS)
    assert 'class="hero"' in html or "class='hero'" in html

    # 7 counter labels — agent state buckets + workspaces/surfaces/agents
    for label in (
        "workspaces", "surfaces", "agents",
        "running", "needs_input", "idle", "unknown",
    ):
        assert label in html, f"missing counter label: {label}"

    # Counter values for the fixture
    # workspaces=4, surfaces=41, agents=17, running=12, needs_input=3,
    # idle=1, unknown=1. Use a <div class="counter"> structure so we can pin
    # the (number, label) pairing.
    def _has_counter(value: int, label: str) -> bool:
        # The template renders counters as: <div class="counter">N<small>label</small></div>
        # Search for the value adjacent to the label, tolerating whitespace.
        import re
        pat = re.compile(
            r'class="counter[^"]*">\s*' + str(value) + r'\s*<small[^>]*>\s*' + re.escape(label),
            re.S,
        )
        return bool(pat.search(html))

    assert _has_counter(4, "workspaces")
    assert _has_counter(41, "surfaces")
    assert _has_counter(17, "agents")
    assert _has_counter(12, "running")
    assert _has_counter(3, "needs_input")
    assert _has_counter(1, "idle")
    assert _has_counter(1, "unknown")

    # Agents subtitle line "2 tagged · 15 heuristic"
    assert "2 tagged" in html
    assert "15 heuristic" in html
    assert "2 tagged · 15 heuristic" in html

    # Placeholder search input (live wiring lands in T10)
    assert '<input' in html and 'type="search"' in html

    # Refresh-hint text near captured_at
    assert "re-run: cmux-observability collect && finalize" in html

    # captured_at rendered through relative_time filter — for a fixture
    # several months in the past, output should fall back to an ISO date.
    assert "2026-05-27" in html


def test_relative_time_filter_registered_and_buckets():
    """T8: `relative_time` Jinja filter — seconds / minutes / hours / ISO date."""
    from datetime import timedelta
    from cmux_observability.render.render import _env

    env = _env()
    assert "relative_time" in env.filters, "relative_time filter must be registered"
    rt = env.filters["relative_time"]

    now = datetime.now(timezone.utc)
    assert rt(now - timedelta(seconds=14)) == "14s ago"
    assert rt(now - timedelta(minutes=3)) == "3m ago"
    assert rt(now - timedelta(hours=2)) == "2h ago"
    # >= 24h → ISO date fallback (just check it doesn't say "ago")
    old = now - timedelta(days=5)
    out = rt(old)
    assert "ago" not in out
    assert old.date().isoformat() in out
