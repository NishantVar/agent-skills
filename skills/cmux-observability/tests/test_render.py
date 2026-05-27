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
    # T13 dropped cpu/mem from the surface row layout — the row is now
    # [state-pill][mono title][summary][captured Xs ago][copy-ref chip].
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
        # T9 added a `data-state=...` attribute after the class on the four
        # state counters, so allow any attributes between class and `>`.
        import re
        pat = re.compile(
            r'class="counter[^"]*"[^>]*>\s*' + str(value) + r'\s*<small[^>]*>\s*' + re.escape(label),
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


def test_render_hero_click_filter_and_url_hash_state(tmp_path: Path):
    """T9: hero counter chips for the four state buckets are clickable;
    clicks compose OR-filter via location.hash, toggling `data-filter-active`
    on chips and `data-hidden` on rows whose state isn't in the active set.

    Render-snapshot assertions only — DOM behaviour is exercised by the
    inline JS at runtime; we verify the JS source plus the data hooks the
    JS reads/writes are present in the rendered HTML.
    """
    snap = _snap_hero_fixture()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # The four state counters carry data-state="<name>" so the JS can match
    # them when reading/writing location.hash.
    import re
    for state in ("running", "needs_input", "idle", "unknown"):
        pat = re.compile(
            r'class="counter[^"]*"[^>]*data-state="' + state + r'"'
            r'|data-state="' + state + r'"[^>]*class="counter[^"]*"',
            re.S,
        )
        assert pat.search(html), f"counter chip missing data-state=\"{state}\""

    # Workspace/surface/agents counters MUST NOT carry data-state — only
    # the four state buckets are filter triggers.
    for non_state_label in ("workspaces", "surfaces", "agents"):
        # Find the counter block and assert no data-state attribute on it.
        block = re.search(
            r'class="counter[^"]*">[^<]*<small[^>]*>\s*' + non_state_label,
            html,
            re.S,
        )
        # We only care that the non-state counter chip does not carry a
        # data-state attribute; the regex above pins the chip's open tag.
        # Look back at the matched chip's opening to verify.
        chip_open = re.search(
            r'<div class="counter[^"]*"[^>]*>[^<]*<small[^>]*>\s*' + non_state_label,
            html,
            re.S,
        )
        assert chip_open, f"counter chip for {non_state_label} not found"
        assert "data-state=" not in chip_open.group(0), (
            f"non-state counter {non_state_label!r} should not carry data-state"
        )

    # Surface rows expose their state via data-state so the JS can hide/show.
    # Fixture has agents on surfaces 1..17; row 1 is running. T13 moved row
    # containers from <tr> to <div class="surface-row"> — the contract is
    # the data-state attribute on the row root, not the tag name.
    assert re.search(r'<\w+[^>]*data-state="running"', html), (
        "agent row missing data-state=\"running\""
    )
    assert re.search(r'<\w+[^>]*data-state="needs_input"', html), (
        "agent row missing data-state=\"needs_input\""
    )
    assert re.search(r'<\w+[^>]*data-state="idle"', html), (
        "agent row missing data-state=\"idle\""
    )
    assert re.search(r'<\w+[^>]*data-state="unknown"', html), (
        "agent row missing data-state=\"unknown\""
    )

    # Inline <script> block carries the filter logic. We do not pin exact
    # source — only the load-bearing tokens that prove the wiring exists.
    for token in (
        "location.hash",          # reads URL hash
        "hashchange",             # listens for URL hash changes
        "data-filter-active",     # toggles on counter chips
        "data-hidden",            # toggles on filtered-out rows
        "data-state",             # selector key
        "filter=",                # hash format: #filter=running,needs_input
        "running",
        "needs_input",
        "idle",
        "unknown",
    ):
        assert token in html, f"inline filter script missing token: {token!r}"


def test_render_hero_search_live_filter_and_url_hash(tmp_path: Path):
    """T10: hero search box live-filters surface rows by substring against a
    per-row `data-search` corpus (lowercased workspace title + surface title +
    summary text). The query syncs to URL hash as `q=<encoded>` and composes
    with the T9 `filter=` state filter using AND.

    Render-snapshot assertions only — DOM behaviour is exercised by the
    inline JS at runtime; we verify the JS source plus the data hooks the
    JS reads/writes are present in the rendered HTML.
    """
    import re

    snap = _snap_populated(
        summary_text="writing pytest fixtures for maya project",
        ws_title="Project Maya",
    )
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # The search input has an id the script targets.
    assert re.search(r'<input[^>]*id="hero-search"[^>]*type="search"', html) or \
           re.search(r'<input[^>]*type="search"[^>]*id="hero-search"', html), (
        "hero search <input> must carry id=\"hero-search\""
    )

    # Surface rows expose a lowercased search corpus via data-search.
    # The populated fixture has ws.title="Project Maya", surface.title=
    # "claude_code worker", summary.text="writing pytest fixtures for maya
    # project". Corpus must be lowercased so JS does `.includes(q.toLowerCase())`.
    row_match = re.search(r'<\w+[^>]*data-search="([^"]*)"', html)
    assert row_match, "surface row missing data-search attribute"
    corpus = row_match.group(1)
    # Lowercased once at render-time:
    assert corpus == corpus.lower(), f"data-search corpus must be lowercased: {corpus!r}"
    # Must contain the three fields lowercased.
    assert "project maya" in corpus, f"workspace title missing from corpus: {corpus!r}"
    assert "claude_code worker" in corpus, f"surface title missing from corpus: {corpus!r}"
    assert "writing pytest fixtures for maya project" in corpus, (
        f"summary text missing from corpus: {corpus!r}"
    )

    # Inline script must carry the load-bearing tokens proving the wiring.
    for token in (
        "q=",                  # hash format: #filter=...&q=...
        "input",               # the input event listener
        "data-search",         # the per-row corpus selector key
        "hashchange",          # still listens for hash changes
        "encodeURIComponent",  # safely sync query into the hash
        "decodeURIComponent",  # safely read query out of the hash
        "toLowerCase",         # case-insensitive substring match
        "includes",            # substring match
    ):
        assert token in html, f"inline search script missing token: {token!r}"

    # AND-composition: the rendered script must combine the state filter and
    # the query. We look for a pattern proving both gates are checked on the
    # same row visibility decision. Accept either explicit `&&`/`and` joining,
    # or sequential early-continue branches. Conservative check: both
    # `q.length` (or `query`) and `data-state`/`activeSet` appear in the
    # row-visibility loop.
    # We assert the script mentions both gates near each other (within ~400
    # chars of the data-hidden write).
    hide_writes = [m.start() for m in re.finditer(r'data-hidden', html)]
    assert hide_writes, "expected at least one data-hidden write in the script"
    # Find the script section and assert both `data-state` and `data-search`
    # (or `dataset.search`) are referenced — proving the row decision reads
    # both attributes.
    script_block = re.search(r'<script>(?:(?!</script>).)*data-hidden(?:(?!</script>).)*</script>',
                              html, re.S)
    assert script_block, "filter script block not found"
    body = script_block.group(0)
    assert "data-state" in body or "activeSet" in body, (
        "filter script must reference state filter in visibility decision"
    )
    assert "data-search" in body or "dataset.search" in body, (
        "filter script must reference search corpus in visibility decision"
    )


def test_render_hero_search_corpus_handles_missing_summary(tmp_path: Path):
    """T10: rows without a summary still get a data-search corpus (workspace
    + surface title only) — the JS must not blow up when summary is absent."""
    import re

    snap = _snap_hero_fixture()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Every surface row carries data-search, even those without a summary.
    # T13 swapped the tag from <tr> to <div class="surface-row">; the contract
    # is the data-search attribute, not the tag.
    rows = re.findall(r'<\w+\b[^>]*>', html)
    rows_with_search = [r for r in rows if 'data-search="' in r]
    # Fixture has 41 surfaces, all in workspaces — all should carry corpus.
    assert len(rows_with_search) == 41, (
        f"expected 41 surface rows with data-search, got {len(rows_with_search)}"
    )
    # Each corpus is non-empty (workspace + surface title at minimum).
    for r in rows_with_search:
        m = re.search(r'data-search="([^"]*)"', r)
        assert m and m.group(1), f"empty data-search on row: {r!r}"


def test_render_hero_search_corpus_escapes_html(tmp_path: Path):
    """T10: data-search corpus must be HTML-attribute-safe — Jinja autoescape
    on the corpus string must protect against double-quote injection or
    `<script>` insertion via workspace/summary text."""
    import re

    snap = _snap_populated(
        summary_text='" onmouseover="alert(1)',
        ws_title="<script>x</script>",
    )
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # data-search must NOT contain a raw unescaped double-quote breakout or
    # raw <script>. We matched the attribute via [^"]* so absence of a raw "
    # inside is structurally guaranteed; the assertions below additionally
    # confirm the dangerous chars survive as entity references.
    row = re.search(r'<\w+[^>]*data-search="([^"]*)"', html)
    assert row, "missing data-search on surface row"
    corpus_attr = row.group(1)
    # Raw < / > / " MUST be entity-encoded inside the attribute value.
    assert "<script>" not in corpus_attr, (
        f"raw <script> reached corpus: {corpus_attr!r}"
    )
    assert "&lt;script&gt;" in corpus_attr, (
        f"workspace title should appear entity-encoded in corpus: {corpus_attr!r}"
    )
    assert "&#34;" in corpus_attr or "&quot;" in corpus_attr, (
        f"double-quote breakout from summary should be entity-encoded: {corpus_attr!r}"
    )


def _snap_blocked_fixture(needs_input_count: int) -> Snapshot:
    """T11: fixture with N needs_input surfaces (each in its own workspace) plus
    a couple of running surfaces interleaved. Agents are appended to
    snapshot.agents in capture order so the banner can rely on that ordering.
    """
    workspaces: list[Workspace] = []
    agents: list[Agent] = []
    # First, a couple of running surfaces (not blocked) — these must NOT appear
    # in the blocked banner.
    for i in range(1, 3):
        surf = Surface(
            ref=f"surface:R{i}",
            pane_ref=f"pane:R{i}",
            workspace_ref=f"workspace:R{i}",
            kind="terminal",
            title=f"running surface {i}",
        )
        ws = Workspace(
            ref=f"workspace:R{i}",
            title=f"Running WS {i}",
            window_ref=f"window:R{i}",
            surfaces=[surf],
        )
        workspaces.append(ws)
        agents.append(Agent(
            surface_ref=surf.ref,
            workspace_ref=ws.ref,
            type="claude_code",
            type_source="cmux_tag",
            type_confidence=1.0,
            state="running",
            state_source="cmux_tag",
            summary=Summary(
                text="running work",
                state_hint="running",
                needs_input_reason=None,
                confidence=0.9,
                cache_hit=False,
                cached_at=datetime(2026, 5, 27, 14, 29, 0, tzinfo=timezone.utc),
                prompt_version=1,
                screen_hash="aaaa",
            ),
        ))

    # Now the needs_input surfaces, in capture order.
    for i in range(1, needs_input_count + 1):
        surf = Surface(
            ref=f"surface:N{i}",
            pane_ref=f"pane:N{i}",
            workspace_ref=f"workspace:N{i}",
            kind="terminal",
            title=f"blocked surface {i}",
        )
        ws = Workspace(
            ref=f"workspace:N{i}",
            title=f"Blocked WS {i}",
            window_ref=f"window:N{i}",
            surfaces=[surf],
        )
        workspaces.append(ws)
        agents.append(Agent(
            surface_ref=surf.ref,
            workspace_ref=ws.ref,
            type="claude_code",
            type_source="cmux_tag",
            type_confidence=1.0,
            state="needs_input",
            state_source="cmux_tag",
            summary=Summary(
                text=f"long detailed summary for blocked surface {i} with no truncation expected",
                state_hint="needs_input",
                needs_input_reason=f"awaiting permission for action {i}",
                confidence=0.9,
                cache_hit=False,
                cached_at=datetime(2026, 5, 27, 14, 29, 0, tzinfo=timezone.utc),
                prompt_version=1,
                screen_hash=f"bbbb{i}",
            ),
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


def test_render_blocked_banner_absent_when_no_needs_input(tmp_path: Path):
    """T11: with zero needs_input surfaces, the blocked-work banner must not
    render at all (no markers, no `surface:N` literal outside chips elsewhere
    related to needs_input)."""
    import re

    snap = _snap_blocked_fixture(needs_input_count=0)
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # No banner <section> rendered (CSS rules for .blocked-banner may still
    # live in the inline <style>; what must NOT exist is the runtime markup).
    assert not re.search(r'<section[^>]*class="[^"]*blocked-banner', html), (
        "blocked-banner <section> must not render when no needs_input agents"
    )
    assert not re.search(r'<article[^>]*class="[^"]*blocked-card', html), (
        "blocked-card <article> must not render when no needs_input agents"
    )


def test_render_blocked_banner_two_cards_in_capture_order(tmp_path: Path):
    """T11: with two needs_input surfaces, the banner renders two cards in
    capture order, each carrying workspace title, surface title, full summary
    text, needs_input_reason (italic), relative_time stamp, and a copy-ref chip.

    The `surface:N` literal must appear ONLY inside chip elements (chip body +
    its title attribute) — NOT in card headings or bodies. T20 audits this
    globally; we honor it here from the start.
    """
    import re

    snap = _snap_blocked_fixture(needs_input_count=2)
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Banner section is present.
    assert "blocked-banner" in html
    # Two cards rendered.
    cards = re.findall(r'<article[^>]*class="[^"]*blocked-card[^"]*"', html)
    assert len(cards) == 2, f"expected 2 blocked cards, got {len(cards)}"

    # Extract the banner section so we can pin assertions to it.
    banner_match = re.search(
        r'<section[^>]*class="[^"]*blocked-banner[^"]*"[^>]*>(.*?)</section>',
        html, re.S,
    )
    assert banner_match, "blocked banner section not found"
    banner = banner_match.group(1)

    # Capture-order: surface:N1 appears before surface:N2 in the banner.
    pos_n1 = banner.find("surface:N1")
    pos_n2 = banner.find("surface:N2")
    assert pos_n1 != -1 and pos_n2 != -1, "both surface refs must appear in banner"
    assert pos_n1 < pos_n2, "capture order N1 before N2 must be preserved"

    # Workspace titles present.
    assert "Blocked WS 1" in banner
    assert "Blocked WS 2" in banner
    # Surface titles present.
    assert "blocked surface 1" in banner
    assert "blocked surface 2" in banner
    # Full summary text (no truncation).
    assert "long detailed summary for blocked surface 1 with no truncation expected" in banner
    assert "long detailed summary for blocked surface 2 with no truncation expected" in banner
    # needs_input_reason rendered in italic (<em> or <i>).
    assert re.search(
        r'<(?:em|i)[^>]*>[^<]*awaiting permission for action 1', banner
    ), "needs_input_reason for card 1 must be in <em>/<i>"
    assert re.search(
        r'<(?:em|i)[^>]*>[^<]*awaiting permission for action 2', banner
    ), "needs_input_reason for card 2 must be in <em>/<i>"
    # "captured Xs ago" stamp — relative_time on snapshot.captured_at against
    # now() yields ISO date for May 2026 from current "now". Either ago or ISO.
    assert "captured" in banner
    # Running surfaces must NOT appear in the banner.
    assert "running surface" not in banner
    assert "Running WS" not in banner

    # Identifier-strip rule: `surface:N` literal MUST appear ONLY inside chip
    # elements (chip body + title attribute) within the banner.
    # Find every occurrence of `surface:N` in the banner and confirm it lives
    # inside a chip element.
    # Strategy: remove all chip elements from the banner and assert no
    # `surface:` remains.
    banner_without_chips = re.sub(
        r'<[^>]*class="[^"]*\bchip\b[^"]*"[^>]*>[^<]*</[^>]+>',
        "",
        banner,
    )
    # Also remove standalone title="cmux focus surface:N" attributes if they
    # sit on non-chip elements (defensive — by spec the title sits on the chip
    # itself, removed above).
    leaked = re.findall(r'surface:\w+', banner_without_chips)
    assert not leaked, (
        f"surface:N literal leaked outside chip elements: {leaked!r}"
    )

    # The chip must carry title="cmux focus surface:N".
    assert re.search(
        r'title="cmux focus surface:N1"', banner
    ), "chip for card 1 must carry title=\"cmux focus surface:N1\""
    assert re.search(
        r'title="cmux focus surface:N2"', banner
    ), "chip for card 2 must carry title=\"cmux focus surface:N2\""

    # Amber left-border via the --state-needs-input token must be referenced
    # in the inline style block.
    assert "border-left" in html
    assert "var(--state-needs-input)" in html


def test_render_filter_css_hides_data_hidden_rows(tmp_path: Path):
    """T7-T10 follow-up (P1): the inline stylesheet must include a rule that
    hides any element carrying `data-hidden="true"`. Use a broad attribute
    selector so future non-<tr> row containers benefit as well."""
    import re

    snap = _snap_hero_fixture()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # `[data-hidden="true"] { display: none; }` — whitespace permissive.
    pat = re.compile(
        r'\[data-hidden="true"\]\s*\{\s*[^}]*display\s*:\s*none',
        re.S,
    )
    assert pat.search(html), (
        "inline <style> must define [data-hidden=\"true\"] { display: none }"
    )


def test_render_active_chip_styling_present(tmp_path: Path):
    """T7-T10 follow-up (P1): chips toggled active by the filter JS must have
    visible styling. The inline <style> block must reference
    `.counter[data-filter-active="true"]`."""
    snap = _snap_hero_fixture()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    assert '.counter[data-filter-active="true"]' in html, (
        "inline <style> must style .counter[data-filter-active=\"true\"]"
    )


def test_render_state_counters_are_buttons(tmp_path: Path):
    """T7-T10 follow-up (P2): the four clickable state-bucket counters must
    render as <button type="button" class="counter" data-state="..."> so they
    are keyboard-focusable and Enter/Space activate them natively."""
    import re

    snap = _snap_hero_fixture()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    for state in ("running", "needs_input", "idle", "unknown"):
        # button open tag carrying type="button", class="counter…", data-state=state
        # Tolerate attribute ordering: class first OR data-state first.
        pat = re.compile(
            r'<button\b[^>]*\btype="button"[^>]*\bclass="counter[^"]*"[^>]*\bdata-state="'
            + state + r'"'
            r'|<button\b[^>]*\bclass="counter[^"]*"[^>]*\btype="button"[^>]*\bdata-state="'
            + state + r'"'
            r'|<button\b[^>]*\bdata-state="' + state
            + r'"[^>]*\bclass="counter[^"]*"[^>]*\btype="button"'
            r'|<button\b[^>]*\btype="button"[^>]*\bdata-state="' + state
            + r'"[^>]*\bclass="counter[^"]*"',
            re.S,
        )
        assert pat.search(html), (
            f"state counter for {state!r} must render as <button type=\"button\" "
            f"class=\"counter\" data-state=\"{state}\">"
        )
        # And the old <div class="counter" data-state="..."> form must be gone.
        old = re.compile(
            r'<div\b[^>]*\bclass="counter[^"]*"[^>]*\bdata-state="' + state + r'"'
            r'|<div\b[^>]*\bdata-state="' + state + r'"[^>]*\bclass="counter[^"]*"',
            re.S,
        )
        assert not old.search(html), (
            f"state counter for {state!r} must NOT remain a <div>"
        )


def test_render_counter_focus_visible_style_present(tmp_path: Path):
    """T7-T10 follow-up (P2): the inline <style> block must define a
    `.counter:focus-visible` rule so keyboard users see a focus outline."""
    snap = _snap_hero_fixture()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    assert ".counter:focus-visible" in html, (
        "inline <style> must define .counter:focus-visible rule"
    )


def test_render_nonstate_counters_remain_div(tmp_path: Path):
    """T7-T10 follow-up (P2): only the four state counters become <button>;
    the three non-interactive counters (workspaces, surfaces, agents) stay
    as <div class="counter"> — they have no click handler and shouldn't be
    focusable."""
    import re

    snap = _snap_hero_fixture()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    for label in ("workspaces", "surfaces", "agents"):
        # Confirm the chip is a <div ...><small>label</small></div>, NOT a button.
        div_pat = re.compile(
            r'<div\b[^>]*\bclass="counter[^"]*"[^>]*>[\s\S]*?<small[^>]*>\s*'
            + label,
            re.S,
        )
        assert div_pat.search(html), (
            f"non-state counter {label!r} must remain a <div class=\"counter\">"
        )
        button_pat = re.compile(
            r'<button\b[^>]*\bclass="counter[^"]*"[^>]*>[\s\S]*?<small[^>]*>\s*'
            + label,
            re.S,
        )
        assert not button_pat.search(html), (
            f"non-state counter {label!r} must NOT have been converted to <button>"
        )
        # Reviewer follow-up tightening: non-state counters must NOT carry a
        # `data-state` attribute. The filter state machine keys off
        # `data-state`, so allowing it here would silently make these counters
        # interactive filter chips and shift the toggling contract.
        bare_div_pat = re.compile(
            r'<div\b(?P<attrs>[^>]*\bclass="counter[^"]*"[^>]*)>[\s\S]*?<small[^>]*>\s*'
            + label,
            re.S,
        )
        m = bare_div_pat.search(html)
        assert m is not None, f"non-state counter {label!r} <div> not found"
        assert "data-state=" not in m.group("attrs"), (
            f"non-state counter {label!r} must NOT carry data-state — "
            f"that attribute marks a counter as an interactive filter chip."
        )


def _snap_workspace_states(
    *,
    ws_title: str = "Project A",
    surface_states: list[str | None] | None = None,
) -> Snapshot:
    """T12 helper: one workspace with N surfaces; each surface either has an
    agent in the given state, or has no agent (`None`) to simulate a plain
    shell. Returns a Snapshot ready for rendering.
    """
    surface_states = surface_states or []
    surfaces: list[Surface] = []
    agents: list[Agent] = []
    for i, st in enumerate(surface_states, start=1):
        ref = f"surface:{i}"
        surfaces.append(Surface(
            ref=ref,
            pane_ref=f"pane:{i}",
            workspace_ref="workspace:1",
            kind="terminal",
            title=f"surface {i}",
        ))
        if st is not None:
            agents.append(Agent(
                surface_ref=ref,
                workspace_ref="workspace:1",
                type="claude_code",
                type_source="cmux_tag",
                type_confidence=1.0,
                state=st,
                state_source="cmux_tag",
            ))
    workspace = Workspace(
        ref="workspace:1",
        title=ws_title,
        window_ref="window:1",
        surfaces=surfaces,
    )
    return Snapshot(
        schema_version=1,
        captured_at=datetime(2026, 5, 27, 14, 30, 0, tzinfo=timezone.utc),
        host="laptop",
        cmux_version="1.2.3",
        workspaces=[workspace],
        agents=agents,
        themes=[],
        productivity=None,
        history=None,
        failures=[],
    )


def test_render_workspace_grid_responsive_breakpoints(tmp_path: Path):
    """T12: the workspace grid container ships a responsive CSS grid:
    1fr at baseline, 1fr 1fr at min-width 1280px, 1fr 1fr 1fr at 1600px.
    """
    snap = _snap_workspace_states(surface_states=["running"])
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Baseline single-column track
    import re
    assert re.search(
        r'\.workspace-grid\s*\{[^}]*grid-template-columns:\s*1fr\s*;',
        html, re.S,
    ), "workspace grid must default to 1fr (mobile baseline)"

    # 2-col @ 1280px
    assert re.search(
        r'@media\s*\(\s*min-width:\s*1280px\s*\)\s*\{[^}]*\.workspace-grid[^}]*grid-template-columns:\s*1fr\s+1fr\s*;',
        html, re.S,
    ), "workspace grid must switch to 1fr 1fr at min-width 1280px"

    # 3-col @ 1600px
    assert re.search(
        r'@media\s*\(\s*min-width:\s*1600px\s*\)\s*\{[^}]*\.workspace-grid[^}]*grid-template-columns:\s*1fr\s+1fr\s+1fr\s*;',
        html, re.S,
    ), "workspace grid must switch to 1fr 1fr 1fr at min-width 1600px"

    # Grid container wraps the workspaces section.
    assert re.search(
        r'class="[^"]*workspace-grid[^"]*"', html,
    ), "workspaces must be wrapped in .workspace-grid container"


def test_render_workspace_card_activity_dot_needs_input_wins(tmp_path: Path):
    """T12 precedence: any needs_input surface → amber dot."""
    snap = _snap_workspace_states(
        surface_states=["needs_input", "running", "idle"],
    )
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Activity dot exists on the workspace card with data-activity="needs_input".
    import re
    assert re.search(
        r'class="[^"]*activity-dot[^"]*"[^>]*data-activity="needs_input"',
        html, re.S,
    ), "activity dot must carry data-activity=\"needs_input\" when any surface needs_input"


def test_render_workspace_card_activity_dot_running_when_no_needs_input(tmp_path: Path):
    """T12 precedence: no needs_input, any running → green dot."""
    snap = _snap_workspace_states(surface_states=["running", "idle"])
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    import re
    assert re.search(
        r'class="[^"]*activity-dot[^"]*"[^>]*data-activity="running"',
        html, re.S,
    ), "activity dot must carry data-activity=\"running\" when no needs_input but some running"


def test_render_workspace_card_activity_dot_idle_when_only_idle(tmp_path: Path):
    """T12 precedence: only idle agents → gray dot."""
    snap = _snap_workspace_states(surface_states=["idle", "idle"])
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    import re
    assert re.search(
        r'class="[^"]*activity-dot[^"]*"[^>]*data-activity="idle"',
        html, re.S,
    ), "activity dot must carry data-activity=\"idle\" when all agents are idle"


def test_render_workspace_card_activity_dot_unknown_when_no_agents(tmp_path: Path):
    """T12 precedence fallthrough: no agents (only plain shells) → dotted-gray
    dot via data-activity="unknown"."""
    snap = _snap_workspace_states(surface_states=[None, None])
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    import re
    assert re.search(
        r'class="[^"]*activity-dot[^"]*"[^>]*data-activity="unknown"',
        html, re.S,
    ), "activity dot must carry data-activity=\"unknown\" when no agents present"


def test_render_workspace_card_details_open_when_needs_input(tmp_path: Path):
    """T12: <details> wrapping the card body is `open` when any surface is
    needs_input or running."""
    snap = _snap_workspace_states(surface_states=["needs_input"])
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    import re
    # `<details open ...>` or `<details ... open>` on the workspace card.
    assert re.search(
        r'<details\b[^>]*\bopen\b[^>]*class="[^"]*card-body[^"]*"'
        r'|<details\b[^>]*class="[^"]*card-body[^"]*"[^>]*\bopen\b',
        html, re.S,
    ), "workspace card-body <details> must carry open when any surface needs_input"


def test_render_workspace_card_details_open_when_running(tmp_path: Path):
    """T12: <details> is open when at least one surface is running."""
    snap = _snap_workspace_states(surface_states=["running", "idle"])
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    import re
    assert re.search(
        r'<details\b[^>]*\bopen\b[^>]*class="[^"]*card-body[^"]*"'
        r'|<details\b[^>]*class="[^"]*card-body[^"]*"[^>]*\bopen\b',
        html, re.S,
    ), "workspace card-body <details> must carry open when any surface running"


def test_render_workspace_card_details_closed_when_idle_only(tmp_path: Path):
    """T12: <details> is NOT open when no surface is needs_input or running."""
    snap = _snap_workspace_states(surface_states=["idle", "idle"])
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    import re
    # Find the workspace card-body details element and assert no `open` token.
    m = re.search(
        r'<details\b([^>]*)class="[^"]*card-body[^"]*"([^>]*)>',
        html, re.S,
    )
    assert m, "workspace card-body <details> must exist"
    pre, post = m.group(1), m.group(2)
    assert " open" not in pre and " open" not in post and not pre.strip().endswith("open") and not post.strip().endswith("open"), (
        "workspace card-body <details> must NOT carry open when no needs_input/running"
    )


def test_render_workspace_card_details_closed_when_no_agents(tmp_path: Path):
    """T12: a workspace with only plain shells (no agents) renders <details>
    closed — there's nothing demanding the user's attention."""
    snap = _snap_workspace_states(surface_states=[None, None])
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    import re
    m = re.search(
        r'<details\b([^>]*)class="[^"]*card-body[^"]*"([^>]*)>',
        html, re.S,
    )
    assert m, "workspace card-body <details> must exist"
    pre, post = m.group(1), m.group(2)
    assert " open" not in pre and " open" not in post, (
        "workspace card-body <details> must NOT carry open when no agents"
    )


def test_render_workspace_card_title_path_basename_and_muted_full_path(tmp_path: Path):
    """T12: when workspace title looks like a filesystem path, render basename
    prominently and the full path muted below."""
    snap = _snap_workspace_states(
        ws_title="/home/u/repos/my-project",
        surface_states=["running"],
    )
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Basename appears as prominent element.
    assert "my-project" in html
    # Full path also appears (muted secondary line).
    assert "/home/u/repos/my-project" in html
    # Muted full-path element carries a `ws-path-full` class hook.
    import re
    assert re.search(
        r'class="[^"]*ws-path-full[^"]*"[^>]*>[^<]*/home/u/repos/my-project',
        html, re.S,
    ), "muted full path must use .ws-path-full class hook"
    # Basename element marked.
    assert re.search(
        r'class="[^"]*ws-title-basename[^"]*"[^>]*>[^<]*my-project',
        html, re.S,
    ), "basename must use .ws-title-basename class hook"


def test_render_workspace_card_title_non_path_renders_as_is(tmp_path: Path):
    """T12: a non-path title renders without a muted full-path line."""
    snap = _snap_workspace_states(
        ws_title="Project Maya",
        surface_states=["running"],
    )
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    assert "Project Maya" in html
    # No ws-path-full muted line for non-path titles.
    import re
    assert not re.search(
        r'class="[^"]*ws-path-full[^"]*"', html, re.S,
    ), "non-path title must not render .ws-path-full muted line"


def test_render_workspace_card_surface_count_rendered(tmp_path: Path):
    """T12: surface count (NOT agent count) appears near the activity dot."""
    snap = _snap_workspace_states(
        surface_states=["running", "idle", None],  # 3 surfaces, 2 agents
    )
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # The surface-count element must show 3.
    import re
    m = re.search(
        r'class="[^"]*surface-count[^"]*"[^>]*>\s*3\b',
        html, re.S,
    )
    assert m, "surface count (3) must render via .surface-count class hook"


def test_render_state_buttons_carry_aria_pressed(tmp_path: Path):
    """Reviewer follow-up #2 (P2 a11y): the four state-bucket <button> chips must
    render with `aria-pressed="false"` baseline so screen-reader / keyboard
    users can perceive which buckets are toggled. The state-machine JS flips
    it to "true" when a chip enters the active set."""
    import re

    snap = _snap_hero_fixture()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    for state in ("running", "needs_input", "idle", "unknown"):
        # The button open tag must carry both data-state="<state>" and
        # aria-pressed="false". We allow any attribute ordering by anchoring
        # on the <button ...> open tag and asserting both attributes appear
        # before the closing `>`.
        pat = re.compile(
            r'<button\b(?P<attrs>[^>]*\bdata-state="' + state + r'"[^>]*)>',
            re.S,
        )
        m = pat.search(html)
        assert m is not None, (
            f"state counter button for {state!r} not found"
        )
        attrs = m.group("attrs")
        assert 'aria-pressed="false"' in attrs, (
            f"state counter button for {state!r} must carry "
            f"aria-pressed=\"false\" baseline; got: {attrs!r}"
        )


def test_render_dashboard_main_widens_past_legacy_cap(tmp_path: Path):
    """Reviewer follow-up #2 (P2 layout): legacy style.css pins
    `main { max-width: 1080px }` which defeats the T12 1280px/1600px
    breakpoints. The dashboard <main> element must carry a class hook
    (e.g. `dashboard-main`) and the inline <style> must define a
    higher-specificity rule with max-width > 1080px on that selector."""
    import re

    snap = _snap_hero_fixture()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # <main> carries the dashboard-main class hook.
    assert re.search(
        r'<main\b[^>]*\bclass="[^"]*\bdashboard-main\b[^"]*"',
        html, re.S,
    ), "<main> element must carry class=\"dashboard-main\""

    # Inline <style> defines main.dashboard-main { max-width: <N>px } where
    # N > 1080. Tolerant of additional declarations in the same block.
    m = re.search(
        r'main\.dashboard-main\s*\{[^}]*max-width\s*:\s*(\d+)\s*px',
        html, re.S,
    )
    assert m is not None, (
        "inline <style> must define main.dashboard-main { max-width: <N>px }"
    )
    cap = int(m.group(1))
    assert cap > 1080, (
        f"main.dashboard-main max-width must exceed legacy 1080px cap; got {cap}"
    )


def test_render_card_header_resets_page_header_chrome(tmp_path: Path):
    """Reviewer follow-up #3 (P3): T12's workspace `<header class="card-header">`
    inherits the global `header { padding: 12px 18px; border-bottom: 1px solid var(--border) }`
    from legacy style.css. The inline <style> `.card-header` rule must reset
    `padding: 0` and `border-bottom: 0` so the card chrome doesn't leak."""
    import re

    snap = _snap_workspace_states(surface_states=["running"])
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Find a .card-header rule in the inline <style> that contains both
    # `padding: 0` and `border-bottom: 0`. Tolerate other declarations.
    m = re.search(
        r'\.card-header\s*\{(?P<body>[^}]*)\}',
        html, re.S,
    )
    assert m is not None, "inline <style> must define a .card-header rule"
    body = m.group("body")
    # Walk every .card-header rule and check at least one resets both.
    found_padding_reset = False
    found_border_reset = False
    for rule_m in re.finditer(r'\.card-header\s*\{([^}]*)\}', html, re.S):
        decls = rule_m.group(1)
        if re.search(r'padding\s*:\s*0\b', decls):
            found_padding_reset = True
        if re.search(r'border-bottom\s*:\s*0\b', decls):
            found_border_reset = True
    assert found_padding_reset, (
        ".card-header must include padding: 0 to neutralise the legacy "
        "header { padding: 12px 18px } chrome"
    )
    assert found_border_reset, (
        ".card-header must include border-bottom: 0 to neutralise the legacy "
        "header { border-bottom: 1px solid var(--border) } chrome"
    )


def test_render_filter_script_flips_aria_pressed(tmp_path: Path):
    """Reviewer follow-up #2 (P2 a11y): the inline filter script must
    set `aria-pressed` on chips based on the active set, so the rendered
    accessible-name state stays in sync with the visual `data-filter-active`
    toggle. We assert the literal `aria-pressed` token appears inside the
    `apply()` chip-iteration block (the same code path that sets
    `data-filter-active`).

    JSDOM smoke-test note: a full DOM simulation would require booting
    node from /tmp and is unnecessary to prove the wiring — the token
    appearing inside the chip-update loop is sufficient evidence that
    deep-linked filters update aria-pressed alongside data-filter-active.
    Skipping JSDOM intentionally; the prior T9/T10 tests follow the same
    'static-token presence' pattern."""
    import re

    snap = _snap_hero_fixture()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # `aria-pressed` literal must appear in the rendered HTML (it lives in
    # both the rendered button attributes AND the inline script).
    assert "aria-pressed" in html, (
        "rendered HTML must mention aria-pressed (either in markup or script)"
    )

    # The token must specifically appear inside the chip-update branch of
    # the filter script, alongside data-filter-active. We grep for a window
    # of text containing both tokens close together.
    # Pull the filter state-machine <script> block. T15 added an additional
    # trailing <script> for theme-chip wiring, so we select the block by
    # content (the one containing `data-filter-active`) rather than position.
    scripts = re.findall(r'<script\b[^>]*>([\s\S]*?)</script>', html)
    assert scripts, "rendered HTML must contain at least one <script> block"
    filter_scripts = [s for s in scripts if "data-filter-active" in s]
    assert filter_scripts, (
        "filter script must set data-filter-active (baseline T9 wiring)"
    )
    filter_script = filter_scripts[0]
    assert "aria-pressed" in filter_script, (
        "filter script must set aria-pressed in lockstep with data-filter-active"
    )


# ---------------------------------------------------------------------------
# T13: surface row redesign — state pill, mono title, ellipsized summary
# ---------------------------------------------------------------------------

def _snap_surface_row(
    *,
    surface_title: str = "claude_code worker",
    summary: "Summary | None" = "__default__",
    is_agent: bool = True,
    has_agent: bool = True,
) -> Snapshot:
    """T13 helper: single workspace, single surface, optional agent + summary.
    `summary="__default__"` uses a tame default; pass `None` for "no summary"
    or a custom `Summary` for the truncation tests.
    """
    surface = Surface(
        ref="surface:1",
        pane_ref="pane:1",
        workspace_ref="workspace:1",
        kind="terminal",
        title=surface_title,
        is_agent=is_agent,
    )
    workspace = Workspace(
        ref="workspace:1",
        title="Project A",
        window_ref="window:1",
        surfaces=[surface],
    )
    agents: list[Agent] = []
    if has_agent:
        if summary == "__default__":
            summary_obj: Summary | None = Summary(
                text="hello world",
                state_hint="running",
                needs_input_reason=None,
                confidence=0.9,
                cache_hit=False,
                cached_at=datetime(2026, 5, 27, 14, 29, 0, tzinfo=timezone.utc),
                prompt_version=1,
                screen_hash="dead",
            )
        else:
            summary_obj = summary  # type: ignore[assignment]
        agents.append(Agent(
            surface_ref="surface:1",
            workspace_ref="workspace:1",
            type="claude_code",
            type_source="cmux_tag",
            type_confidence=1.0,
            state="running",
            state_source="cmux_tag",
            pid=42,
            summary=summary_obj,
        ))
    return Snapshot(
        schema_version=1,
        captured_at=datetime(2026, 5, 27, 14, 30, 0, tzinfo=timezone.utc),
        host="laptop",
        cmux_version="1.2.3",
        workspaces=[workspace],
        agents=agents,
        themes=[],
        productivity=None,
        history=None,
        failures=[],
    )


def _surface_row_html(html: str) -> str:
    """Extract the inner HTML of the surface row whose data-state="running".

    T14: the row root is now `<details class="surface-details">` (was a flat
    `<div class="surface-row">` in T13), so the tag alternation includes
    `details` and the non-greedy `</(?P=tag)>` correctly pairs with the
    matching `</details>`.
    """
    import re
    m = re.search(
        r'<(?P<tag>tr|div|li|article|details)\b(?P<attrs>[^>]*\bdata-state="running"[^>]*)>'
        r'(?P<inner>.*?)</(?P=tag)>',
        html, re.S,
    )
    assert m, "surface row with data-state=\"running\" not found"
    return m.group("attrs") + ">" + m.group("inner")


def test_render_surface_row_has_state_pill_and_mono_title(tmp_path: Path):
    """T13 step 2: row contains a state pill (state name in a span with
    state-running styling) AND the surface title rendered in monospace
    (either inline font-family or via a class hook backed by --font-mono).
    """
    import re

    snap = _snap_surface_row(surface_title="claude_code worker")
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    row = _surface_row_html(html)

    # State pill: an inline element with a class hook tied to the agent state.
    # The pill text is the state name.
    assert re.search(
        r'class="[^"]*state-pill[^"]*"[^>]*>[\s]*running',
        row, re.S,
    ), "row must render a state pill (class=\"state-pill ...\") containing the state name"

    # Mono title cell: title text wrapped in an element with a `mono-title`
    # class hook. The class is styled by an inline rule that references
    # --font-mono (defined in T7).
    assert re.search(
        r'class="[^"]*mono-title[^"]*"[^>]*>[\s]*claude_code worker',
        row, re.S,
    ), "surface title must render with class=\"mono-title\""

    # Inline <style> binds .mono-title to --font-mono.
    assert re.search(
        r'\.mono-title\b[^{}]*\{[^}]*font-family\s*:\s*var\(\s*--font-mono',
        html, re.S,
    ), "mono-title must use var(--font-mono) for its font-family"


def test_render_surface_row_summary_cell_truncates_via_css_and_keeps_full_text_in_title(tmp_path: Path):
    """T13 step 3: the summary cell carries the ellipsis triple
    (white-space: nowrap; overflow: hidden; text-overflow: ellipsis;) AND a
    `title="<full text>"` attribute so non-mouse users can still inspect the
    full text. The flex grow + min-width guard live in inline CSS for the
    `.surface-summary` class hook.
    """
    import re

    summary_text = "writing pytest fixtures for the surface row"
    summary = Summary(
        text=summary_text,
        state_hint="running",
        needs_input_reason=None,
        confidence=0.9,
        cache_hit=False,
        cached_at=datetime(2026, 5, 27, 14, 29, 0, tzinfo=timezone.utc),
        prompt_version=1,
        screen_hash="dead",
    )
    snap = _snap_surface_row(summary=summary)
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()
    row = _surface_row_html(html)

    # `.surface-summary` rule in inline <style> uses the ellipsis triple +
    # `flex: 1; min-width: 0;`.
    style_block = re.search(
        r'\.surface-summary\b[^{}]*\{(?P<decls>[^}]*)\}',
        html, re.S,
    )
    assert style_block, "inline <style> must define a .surface-summary rule"
    decls = style_block.group("decls")
    for needle in (
        "white-space: nowrap",
        "overflow: hidden",
        "text-overflow: ellipsis",
        "min-width: 0",
    ):
        assert needle in decls, (
            f".surface-summary must declare {needle!r}; got: {decls!r}"
        )
    # `flex: 1` (or flex-grow: 1) — accept either shorthand or longhand.
    assert re.search(r'flex\s*:\s*1\b|flex-grow\s*:\s*1\b', decls), (
        f".surface-summary must set flex: 1 (grow); got: {decls!r}"
    )

    # The summary cell carries title="<full text>" for hover reveal.
    assert re.search(
        r'class="[^"]*surface-summary[^"]*"[^>]*\btitle="' + re.escape(summary_text) + r'"'
        r'|\btitle="' + re.escape(summary_text) + r'"[^>]*class="[^"]*surface-summary[^"]*"',
        row, re.S,
    ), "summary cell must carry title=\"<full summary text>\" for non-mouse users"

    # Visible text equals the original (it's <80 chars, no newline).
    assert summary_text in row, "short summary text must appear verbatim in the row"


def test_render_surface_row_summary_truncates_long_text_to_80_chars_with_ellipsis(tmp_path: Path):
    """T13 step 4: a pathological >80 char single-line summary is template-
    truncated to 80 chars + '…'. Full text is preserved in the `title=` attr.
    """
    import re

    # 200-char pathological fixture; will be truncated to 80 chars + '…'.
    long_text = "a" * 200
    summary = Summary(
        text=long_text,
        state_hint="running",
        needs_input_reason=None,
        confidence=0.9,
        cache_hit=False,
        cached_at=datetime(2026, 5, 27, 14, 29, 0, tzinfo=timezone.utc),
        prompt_version=1,
        screen_hash="dead",
    )
    snap = _snap_surface_row(summary=summary)
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()
    row = _surface_row_html(html)

    # Visible body of the summary cell — extract inner text.
    cell_match = re.search(
        r'<[^>]*class="[^"]*surface-summary[^"]*"[^>]*>(?P<body>.*?)</[^>]+>',
        row, re.S,
    )
    assert cell_match, "surface-summary cell not found"
    body = cell_match.group("body").strip()
    # Body must NOT contain the full 200-char string.
    assert long_text not in body, (
        f"long summary must be truncated in the visible body; got len={len(body)}"
    )
    # Body must end with the ellipsis suffix.
    assert "…" in body, f"truncated summary must include '…' suffix; got: {body!r}"
    # And the prefix is 80 chars of 'a' (template guard truncates AT 80 chars).
    assert body.startswith("a" * 80), (
        f"truncated body must start with 80 a's; got: {body[:90]!r}"
    )
    # The `title=` attribute on the cell carries the full untruncated text.
    title_attr = re.search(
        r'class="[^"]*surface-summary[^"]*"[^>]*\btitle="([^"]*)"',
        row, re.S,
    )
    assert title_attr, "surface-summary cell missing title= attribute"
    # Jinja autoescape leaves a-z untouched; full 200-char string survives.
    assert title_attr.group(1) == long_text, (
        f"title= must carry the full untruncated text; got len={len(title_attr.group(1))}"
    )


def test_render_surface_row_summary_truncates_at_first_newline_when_shorter(tmp_path: Path):
    """T13 step 4: when the first newline appears before 80 chars, truncate
    at the newline (keep the first line)."""
    import re

    first_line = "short first line"
    summary_text = first_line + "\nsecond line should not appear\nthird line either"
    summary = Summary(
        text=summary_text,
        state_hint="running",
        needs_input_reason=None,
        confidence=0.9,
        cache_hit=False,
        cached_at=datetime(2026, 5, 27, 14, 29, 0, tzinfo=timezone.utc),
        prompt_version=1,
        screen_hash="dead",
    )
    snap = _snap_surface_row(summary=summary)
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()
    row = _surface_row_html(html)

    cell_match = re.search(
        r'<[^>]*class="[^"]*surface-summary[^"]*"[^>]*>(?P<body>.*?)</[^>]+>',
        row, re.S,
    )
    assert cell_match, "surface-summary cell not found"
    body = cell_match.group("body").strip()
    # Newline-trailing content must not appear in the visible cell.
    assert "second line" not in body, (
        f"content after first newline must be truncated; got: {body!r}"
    )
    # First-line prefix is preserved; ellipsis appended because the original
    # had more content beyond the newline.
    assert body.startswith(first_line), (
        f"first line must survive truncation; got: {body!r}"
    )
    assert "…" in body, (
        f"newline-truncated summary must include '…' suffix; got: {body!r}"
    )


def test_render_surface_row_captured_relative_time_and_copy_ref_chip(tmp_path: Path):
    """T13 step 2 (order): row right-edge contains a captured-Xs-ago stamp
    (via relative_time filter on `summary.cached_at`) AND a copy-ref chip
    whose body is `surface:N` and whose title attribute reads
    `cmux focus surface:N`.
    """
    import re

    snap = _snap_surface_row()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()
    row = _surface_row_html(html)

    # `captured ... ago` text near the right edge of the row.
    assert re.search(r'captured\b', row), "row must show a captured-Xs-ago stamp"

    # Copy-ref chip: title="cmux focus surface:1", body literal `surface:1`.
    assert re.search(
        r'class="[^"]*chip[^"]*"[^>]*\btitle="cmux focus surface:1"',
        row, re.S,
    ), "row must include a copy-ref chip with title=\"cmux focus surface:1\""


def test_render_surface_row_preserves_filter_contract(tmp_path: Path):
    """T13 must preserve the T9+T10 filter contract: surface row root carries
    data-state (state-bucket filter) and data-search (substring filter)."""
    import re

    snap = _snap_surface_row()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Some element carries data-state="running" AND data-search="<corpus>"
    # — these are the contract.
    m = re.search(
        r'<(?P<tag>\w+)\b[^>]*\bdata-state="running"[^>]*\bdata-search="[^"]*"'
        r'|<(?P<tag2>\w+)\b[^>]*\bdata-search="[^"]*"[^>]*\bdata-state="running"',
        html, re.S,
    )
    assert m, "surface row root must carry both data-state and data-search"


def test_render_surface_row_identifier_strip_surface_only_in_chip_and_diagnostic(tmp_path: Path):
    """T13 + T14: the literal `surface:N` token may appear ONLY inside the
    copy-ref chip (body + title attribute) AND the diagnostic line at the
    bottom of the T14 expanded panel. Strip both, then assert no
    `surface:` or `workspace:` text remains.
    """
    import re

    snap = _snap_surface_row()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()
    row = _surface_row_html(html)

    # Remove every chip element (open tag through close tag) AND every
    # title="cmux focus surface:N" attribute (since the chip element-body
    # regex below isn't precise enough for attribute removal).
    row_stripped = re.sub(
        r'<[^>]*\bclass="[^"]*\bchip\b[^"]*"[^>]*>.*?</[^>]+>',
        "",
        row,
        flags=re.S,
    )
    # Also defensively strip standalone "cmux focus surface:N" title attrs.
    row_stripped = re.sub(
        r'\btitle="cmux focus surface:[^"]*"',
        "",
        row_stripped,
    )
    # T14: the diagnostic line is the second allowed home for bare refs;
    # strip its container element so the leak-check ignores it.
    row_stripped = re.sub(
        r'<[^>]*\bclass="[^"]*\bsurface-diagnostic\b[^"]*"[^>]*>.*?</[^>]+>',
        "",
        row_stripped,
        flags=re.S,
    )
    leaked_surface = re.findall(r'surface:\w+', row_stripped)
    assert not leaked_surface, (
        f"surface:N literal leaked outside chip + diagnostic line: {leaked_surface!r}"
    )
    leaked_workspace = re.findall(r'workspace:\w+', row_stripped)
    assert not leaked_workspace, (
        f"workspace:N literal leaked outside chip + diagnostic line: {leaked_workspace!r}"
    )


def test_render_surface_row_missing_summary_when_not_agent(tmp_path: Path):
    """T13 step 5: surface that is not classified as an agent renders the
    text `(not classified as an agent)` — NEVER a bare em-dash."""
    snap = _snap_surface_row(has_agent=False, is_agent=False)
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # The non-agent message must appear somewhere in the row container.
    assert "(not classified as an agent)" in html, (
        "non-agent surface must show '(not classified as an agent)' message"
    )


def test_render_surface_row_missing_summary_when_agent_has_no_summary(tmp_path: Path):
    """T13 step 5: agent surface with no summary at all → '(no screen access)'
    catch-all. (Skipped-vs-no-screen-access distinction collapses into this
    fallback because the model does not currently expose a `no_summarize`
    signal — documented deviation.)"""
    snap = _snap_surface_row(summary=None, has_agent=True, is_agent=True)
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    assert "(no screen access)" in html, (
        "agent surface without a summary must show '(no screen access)' fallback"
    )


def test_render_surface_row_never_renders_bare_em_dash_for_missing_summary(tmp_path: Path):
    """T13 step 5: the surface-summary cell must never be a bare `—`. We
    extract the cell body and assert it carries one of the three documented
    'why no summary' strings instead.
    """
    import re

    # Two scenarios: no-agent surface AND agent-without-summary surface.
    for snap in (
        _snap_surface_row(has_agent=False, is_agent=False),
        _snap_surface_row(summary=None, has_agent=True, is_agent=True),
    ):
        html_path, _json_path = render_snapshot(snap, tmp_path)
        html = html_path.read_text()
        # Pull the surface-summary cell body.
        cell_match = re.search(
            r'<[^>]*class="[^"]*surface-summary[^"]*"[^>]*>(?P<body>.*?)</[^>]+>',
            html, re.S,
        )
        assert cell_match, "surface-summary cell not found"
        body = cell_match.group("body").strip()
        # The catch-all messages are wrapped in parens — assert the body is
        # not a bare em-dash (with or without surrounding whitespace).
        assert body != "—", (
            f"summary cell must never be a bare '—'; got: {body!r}"
        )
        # And it must contain one of the documented messages.
        assert any(needle in body for needle in (
            "(not classified as an agent)",
            "(summary skipped — no_summarize)",
            "(no screen access)",
        )), f"missing 'why no summary' message; got body: {body!r}"


# ---------------------------------------------------------------------------
# T14: click-to-expand surface row with diagnostic line and redaction badge.
# ---------------------------------------------------------------------------


def _snap_surface_row_full(
    *,
    summary_text: str = "the full untruncated summary text " * 5,
    needs_input_reason: str | None = "awaiting user approval on plan",
    cwd: str | None = "/home/u/proj",
    type_source: str = "cmux_tag",
    type_confidence: float = 0.95,
    state_source: str = "cmux_tag",
    redactions_applied: list[str] | None = None,
    state: str = "running",
    pid: int | None = 42,
    prompt_version: int = 3,
    screen_hash: str = "abcdef1234567890",
) -> Snapshot:
    """T14 helper: a populated single-surface fixture suitable for asserting
    the expanded-panel contents and the diagnostic line.
    """
    surface = Surface(
        ref="surface:1",
        pane_ref="pane:1",
        workspace_ref="workspace:1",
        kind="terminal",
        title="claude_code worker",
        cwd=cwd,
        is_agent=True,
    )
    workspace = Workspace(
        ref="workspace:1",
        title="Project A",
        window_ref="window:1",
        surfaces=[surface],
    )
    summary = Summary(
        text=summary_text,
        state_hint=state,
        needs_input_reason=needs_input_reason,
        confidence=0.9,
        cache_hit=False,
        cached_at=datetime(2026, 5, 27, 14, 29, 0, tzinfo=timezone.utc),
        prompt_version=prompt_version,
        screen_hash=screen_hash,
        redactions_applied=list(redactions_applied or []),
        redaction_summary=", ".join(redactions_applied or []),
    )
    agent = Agent(
        surface_ref="surface:1",
        workspace_ref="workspace:1",
        type="claude_code",
        type_source=type_source,
        type_confidence=type_confidence,
        state=state,
        state_source=state_source,
        pid=pid,
        summary=summary,
    )
    return Snapshot(
        schema_version=1,
        captured_at=datetime(2026, 5, 27, 14, 30, 0, tzinfo=timezone.utc),
        host="laptop",
        cmux_version="1.2.3",
        workspaces=[workspace],
        agents=[agent],
        themes=[],
        productivity=None,
        history=None,
        failures=[],
    )


def test_render_surface_row_is_details_with_summary_root(tmp_path: Path):
    """T14 step 1: the surface row root is `<details class="surface-details">`
    with `<summary class="surface-row">` as the collapsed view. <details>
    + <summary> is keyboard-accessible by default (Enter/Space) and ATs
    expose the expanded state — no extra JS for the toggle.
    """
    import re

    snap = _snap_surface_row_full()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Root element is a <details> with the surface-details class hook AND the
    # filter-contract attributes (data-state + data-search).
    assert re.search(
        r'<details\b[^>]*class="[^"]*surface-details[^"]*"[^>]*\bdata-state="running"',
        html, re.S,
    ), "row root must be <details class=\"surface-details\" ... data-state=\"running\">"

    # The collapsed view is the <summary class="surface-row"> child.
    assert re.search(
        r'<summary\b[^>]*class="[^"]*surface-row[^"]*"',
        html, re.S,
    ), "<details> must contain <summary class=\"surface-row\"> as the collapsed view"


def test_render_surface_row_filter_contract_on_details_root(tmp_path: Path):
    """T14: data-state and data-search MUST live on the outer <details> so the
    `[data-hidden="true"] { display: none; }` rule still hides the whole row,
    and so the JS filter (which iterates `[data-search]`) keeps working.
    """
    import re

    snap = _snap_surface_row_full()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Both attributes on the same <details> element (either order).
    pat = re.compile(
        r'<details\b[^>]*\bdata-state="running"[^>]*\bdata-search="[^"]*"'
        r'|<details\b[^>]*\bdata-search="[^"]*"[^>]*\bdata-state="running"',
        re.S,
    )
    assert pat.search(html), (
        "<details> root must carry both data-state and data-search "
        "(filter contract preserved from T9 + T10)"
    )

    # And the data-hidden display:none rule is still present (inherited from
    # T7-T10 follow-up CSS) — same broad attribute selector hides any element.
    assert re.search(
        r'\[data-hidden="true"\]\s*\{\s*[^}]*display\s*:\s*none',
        html, re.S,
    ), "[data-hidden=\"true\"] { display: none } rule must still be defined"


def test_render_surface_row_expanded_panel_renders_full_summary_and_metadata(tmp_path: Path):
    """T14 step 1: the expanded panel renders the FULL summary text (not the
    template-truncated version), `needs_input_reason`, `cwd` (when known),
    and `type_source + type_confidence` as small text.
    """
    import re

    long_summary = (
        "this is the full untruncated summary that exceeds the 80-char "
        "ellipsis budget enforced on the collapsed row by truncated_summary"
    )
    snap = _snap_surface_row_full(
        summary_text=long_summary,
        needs_input_reason="awaiting user approval on plan",
        cwd="/home/u/proj",
        type_source="cmux_tag",
        type_confidence=0.95,
    )
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()
    row = _surface_row_html(html)

    # Extract the expanded-panel container (a non-summary element under
    # <details>). We key off `surface-expanded` as the documented class hook.
    # Match the OUTER <div class="surface-expanded"> precisely (class anchored
    # so .surface-expanded-summary is not a false positive); body runs to the
    # end of the extracted row (the helper already stopped at the matching
    # </details> close).
    panel_match = re.search(
        r'<div\b[^>]*\bclass="surface-expanded"[^>]*>(?P<body>.*)\Z',
        row, re.S,
    )
    assert panel_match, "expanded panel (class=\"surface-expanded\") not found"
    panel = panel_match.group("body")

    # Full untruncated summary text appears in the expanded panel.
    assert long_summary in panel, (
        "expanded panel must show the FULL untruncated summary text"
    )
    # needs_input_reason rendered when present.
    assert "awaiting user approval on plan" in panel, (
        "expanded panel must render needs_input_reason when present"
    )
    # cwd rendered when known.
    assert "/home/u/proj" in panel, "expanded panel must render cwd when known"
    # type_source + type_confidence appear together.
    assert "cmux_tag" in panel, "expanded panel must render type_source"
    assert "0.95" in panel, "expanded panel must render type_confidence"


def test_render_surface_row_diagnostic_line_renders_all_fields(tmp_path: Path):
    """T14 step 2: a single muted diagnostic line at the bottom of the
    expanded panel renders the 6 fields (run_id omitted — Snapshot dataclass
    does not expose it). Bare refs `workspace:N` and `surface:N` are allowed
    here per spec (second allowed home, after the copy-ref chip).
    """
    import re

    snap = _snap_surface_row_full(
        type_source="cmux_tag",
        prompt_version=3,
        screen_hash="abcdef1234567890",
        pid=42,
    )
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()
    row = _surface_row_html(html)

    diag_match = re.search(
        r'<[^>]*\bclass="[^"]*surface-diagnostic[^"]*"[^>]*>(?P<body>.*?)</[^>]+>',
        row, re.S,
    )
    assert diag_match, "diagnostic line (class=\"surface-diagnostic\") not found"
    body = diag_match.group("body")

    # 6 fields rendered (run_id omitted — documented deviation).
    assert "workspace:1" in body, "diagnostic must include workspace_ref"
    assert "surface:1" in body, "diagnostic must include surface_ref"
    assert "42" in body, "diagnostic must include pid"
    assert "cmux_tag" in body, "diagnostic must include type_source"
    assert "3" in body, "diagnostic must include prompt_version"
    # screen_hash is truncated to ~7 chars for readability; the prefix must appear.
    assert "abcdef1" in body, "diagnostic must include screen_hash prefix"


def test_render_surface_row_diagnostic_line_pid_unknown_renders_question_mark(tmp_path: Path):
    """T14 step 2: when `agent.pid` is None the diagnostic still renders, with
    `?` as the placeholder so the line stays uniform across rows."""
    import re

    snap = _snap_surface_row_full(pid=None)
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()
    row = _surface_row_html(html)

    diag_match = re.search(
        r'<[^>]*\bclass="[^"]*surface-diagnostic[^"]*"[^>]*>(?P<body>.*?)</[^>]+>',
        row, re.S,
    )
    assert diag_match, "diagnostic line not found"
    body = diag_match.group("body")
    assert "?" in body, "diagnostic must render '?' for unknown pid"


def test_render_surface_row_diagnostic_line_is_muted_low_contrast(tmp_path: Path):
    """T14 step 2: the diagnostic line is muted via `color: var(--muted)` and
    `font-size: 0.75em;` per spec — small + low-contrast."""
    import re

    snap = _snap_surface_row_full()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    style_block = re.search(
        r'\.surface-diagnostic\b[^{}]*\{(?P<decls>[^}]*)\}',
        html, re.S,
    )
    assert style_block, "inline <style> must define a .surface-diagnostic rule"
    decls = style_block.group("decls")
    assert re.search(r'color\s*:\s*var\(\s*--muted', decls), (
        f".surface-diagnostic must use color: var(--muted); got: {decls!r}"
    )
    assert re.search(r'font-size\s*:\s*0\.75em', decls), (
        f".surface-diagnostic must use font-size: 0.75em; got: {decls!r}"
    )


def test_render_surface_row_redaction_badge_renders_when_redactions_applied(tmp_path: Path):
    """T14 step 3: when `agent.summary.redactions_applied` is non-empty,
    the collapsed row carries a `redacted` badge (inside `<summary>`) with
    a tooltip listing the redaction types.
    """
    import re

    snap = _snap_surface_row_full(
        redactions_applied=["SK_TOKEN:1", "EMAIL:2"],
    )
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()
    row = _surface_row_html(html)

    # Badge appears inside the <summary> (collapsed view).
    summary_match = re.search(
        r'<summary\b[^>]*class="[^"]*surface-row[^"]*"[^>]*>(?P<body>.*?)</summary>',
        row, re.S,
    )
    assert summary_match, "<summary class=\"surface-row\"> not found"
    summary_body = summary_match.group("body")

    badge_match = re.search(
        r'<[^>]*\bclass="[^"]*surface-redaction-badge[^"]*"[^>]*>(?P<body>.*?)</[^>]+>',
        summary_body, re.S,
    )
    assert badge_match, (
        "collapsed row must include a redaction badge "
        "(class=\"surface-redaction-badge\") when redactions_applied is non-empty"
    )
    assert "redacted" in badge_match.group("body").lower(), (
        f"badge text must say 'redacted'; got: {badge_match.group('body')!r}"
    )
    # Tooltip carries the redaction types.
    title_match = re.search(
        r'class="[^"]*surface-redaction-badge[^"]*"[^>]*\btitle="([^"]*)"',
        summary_body, re.S,
    )
    assert title_match, "redaction badge must carry a title= tooltip"
    title = title_match.group(1)
    assert "SK_TOKEN:1" in title and "EMAIL:2" in title, (
        f"badge tooltip must list redaction types; got: {title!r}"
    )


def test_render_surface_row_no_redaction_badge_when_empty(tmp_path: Path):
    """T14 step 3: when `redactions_applied` is empty, no badge is rendered."""
    import re

    snap = _snap_surface_row_full(redactions_applied=[])
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()
    row = _surface_row_html(html)

    assert not re.search(
        r'class="[^"]*surface-redaction-badge[^"]*"',
        row,
    ), "redaction badge must NOT render when redactions_applied is empty"


def test_render_surface_row_disagreement_note_when_heuristic_and_agent_summary_state(tmp_path: Path):
    """T14 step 1: when `type_source == "heuristic"` AND `state_source ==
    "agent_summary"` (i.e. the summarizer's hint drove the state on a row
    cmux did not tag as a known agent), render a disagreement note in the
    expanded panel. (cmux_tag-vs-heuristic disagreement in the other
    direction is skipped — see worker report.)
    """
    import re

    snap = _snap_surface_row_full(
        type_source="heuristic",
        state_source="agent_summary",
    )
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()
    row = _surface_row_html(html)

    # Match the OUTER <div class="surface-expanded"> precisely (class anchored
    # so .surface-expanded-summary is not a false positive); body runs to the
    # end of the extracted row (the helper already stopped at the matching
    # </details> close).
    panel_match = re.search(
        r'<div\b[^>]*\bclass="surface-expanded"[^>]*>(?P<body>.*)\Z',
        row, re.S,
    )
    assert panel_match, "expanded panel not found"
    panel = panel_match.group("body")
    # Disagreement note carries a stable class hook so future tests + screen
    # readers can find it. Body text mentions both signals.
    assert re.search(
        r'class="[^"]*surface-disagreement[^"]*"',
        panel, re.S,
    ), "expanded panel must include a disagreement note when heuristic + agent_summary"


def test_render_surface_row_no_disagreement_note_when_cmux_tag(tmp_path: Path):
    """T14 step 1 (negative): when `type_source == "cmux_tag"`, the
    disagreement note must NOT render — cmux tagged this row authoritatively."""
    import re

    snap = _snap_surface_row_full(
        type_source="cmux_tag",
        state_source="agent_summary",
    )
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()
    row = _surface_row_html(html)

    assert not re.search(
        r'class="[^"]*surface-disagreement[^"]*"',
        row,
    ), "disagreement note must NOT render when type_source=cmux_tag"


# ---------------------------------------------------------------------------
# T15: theme chips with titles + scroll-to + highlight pulse
# ---------------------------------------------------------------------------


def _snap_themes_fixture(
    *,
    workspace_title: str = "Project Alpha",
    surface_specs: list[tuple[str, str | None]] | None = None,
    theme_member_refs: list[str] | None = None,
    theme_label: str = "auth refactor",
) -> Snapshot:
    """T15 helper: one workspace with N surfaces (each `(surface_title, agent_state_or_None)`),
    plus a single theme referencing the given member refs (defaults to all surfaces).
    """
    surface_specs = surface_specs or [("worker frontend", "running")]
    surfaces: list[Surface] = []
    agents: list[Agent] = []
    for i, (title, st) in enumerate(surface_specs, start=1):
        ref = f"surface:{i}"
        surfaces.append(Surface(
            ref=ref,
            pane_ref=f"pane:{i}",
            workspace_ref="workspace:1",
            kind="terminal",
            title=title,
        ))
        if st is not None:
            agents.append(Agent(
                surface_ref=ref,
                workspace_ref="workspace:1",
                type="claude_code",
                type_source="cmux_tag",
                type_confidence=1.0,
                state=st,
                state_source="cmux_tag",
            ))
    workspace = Workspace(
        ref="workspace:1",
        title=workspace_title,
        window_ref="window:1",
        surfaces=surfaces,
    )
    if theme_member_refs is None:
        theme_member_refs = [s.ref for s in surfaces]
    theme = Theme(
        label=theme_label,
        member_refs=theme_member_refs,
        why="related work",
        confidence=0.85,
    )
    return Snapshot(
        schema_version=1,
        captured_at=datetime(2026, 5, 27, 14, 30, 0, tzinfo=timezone.utc),
        host="laptop",
        cmux_version="1.2.3",
        workspaces=[workspace],
        agents=agents,
        themes=[theme],
        productivity=None,
        history=None,
        failures=[],
    )


def test_render_themes_section_absent_when_empty(tmp_path: Path):
    """T15 step 6: when `snapshot.themes` is empty, the themes <section> must
    not render at all — no card, no header, no chip artifacts."""
    snap = _snap_workspace_states(surface_states=["running"])  # themes=[] by default
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # No themes <h2>, no rendered theme-member chip element. Match on the
    # opening <button> tag specifically so the chip class name appearing in
    # the always-emitted inline-JS querySelector doesn't false-positive.
    import re
    assert "Work themes" not in html, "themes section must not render when themes=[]"
    assert not re.search(
        r'<button\b[^>]*\btheme-member-chip\b', html,
    ), "no theme chip element when themes empty"


def test_render_themes_section_present_when_themes(tmp_path: Path):
    """T15 step 6 positive: when themes are non-empty, the section renders."""
    snap = _snap_themes_fixture()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    assert "Work themes" in html, "themes section must render when themes present"


def test_render_themes_chip_uses_titles_not_bare_refs(tmp_path: Path):
    """T15 step 2: each theme member is rendered as
    `<button class="chip" data-target="sf-N">{surface.title} @ {workspace.title}</button>`.
    Labels must use titles — no bare `surface:N` or `workspace:N` literals."""
    import re

    snap = _snap_themes_fixture(
        workspace_title="auth-service",
        surface_specs=[("worker frontend", "running")],
    )
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Extract the themes section so we don't pick up matches elsewhere.
    sect_m = re.search(
        r'<h2>Work themes.*?</section>',
        html, re.S,
    )
    assert sect_m, "themes <section> not found"
    section = sect_m.group(0)

    # A button.chip with data-target="sf-..." carrying titles in its label.
    btn_m = re.search(
        r'<button\b[^>]*class="[^"]*chip[^"]*"[^>]*data-target="(?P<target>[^"]+)"[^>]*>(?P<label>.*?)</button>',
        section, re.S,
    )
    assert btn_m, "theme chip must be a <button class='chip' data-target='...'> element"
    target = btn_m.group("target")
    label = btn_m.group("label")

    # Stable DOM id is DOM-safe (no colon) — not the raw surface:N ref.
    assert ":" not in target, f"data-target must be DOM-safe (no colons): got {target!r}"
    assert target.startswith("sf-"), f"data-target should follow `sf-N` scheme: got {target!r}"

    # Label includes both titles.
    assert "worker frontend" in label, "chip label must include surface title"
    assert "auth-service" in label, "chip label must include workspace title"

    # Identifier-strip: no bare `surface:` or `workspace:` literals in the
    # chip label or any other theme-card body (the diagnostic line + copy-ref
    # chip live OUTSIDE the themes section).
    # Within the entire themes section, neither bare ref form should appear.
    assert "surface:" not in section, "theme section must not leak bare `surface:N` refs"
    assert "workspace:" not in section, "theme section must not leak bare `workspace:N` refs"


def test_render_surface_row_carries_stable_dom_id(tmp_path: Path):
    """T15 step 3: each surface row's <details> root carries
    `id="surface-sf-N"` — a sanitized DOM-safe id, NOT the raw `surface:N` ref.
    The id must match what theme chips target via `data-target`."""
    import re

    snap = _snap_themes_fixture(
        surface_specs=[("worker frontend", "running"), ("worker backend", "idle")],
        theme_member_refs=["surface:2"],  # chip should point at sf-1 (0-indexed second surface)
    )
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Both surface rows carry id="surface-sf-N" (DOM-safe).
    ids = re.findall(
        r'<details\b[^>]*class="[^"]*surface-details[^"]*"[^>]*id="(?P<id>[^"]+)"'
        r'|<details\b[^>]*id="(?P<id2>[^"]+)"[^>]*class="[^"]*surface-details[^"]*"',
        html, re.S,
    )
    flat_ids = [a or b for a, b in ids]
    assert len(flat_ids) == 2, f"expected 2 surface-details ids, got {flat_ids!r}"
    for sid in flat_ids:
        assert sid.startswith("surface-sf-"), f"id must follow `surface-sf-N` scheme: {sid!r}"
        assert ":" not in sid, f"id must be DOM-safe (no colons): {sid!r}"

    # The theme chip targeting surface:2 should resolve to the second surface
    # (sf-1 in 0-indexed flat enumeration); the chip's data-target must match
    # one of the surface row ids minus the "surface-" prefix.
    chip_m = re.search(
        r'<button\b[^>]*class="[^"]*chip[^"]*"[^>]*data-target="(?P<target>[^"]+)"',
        html, re.S,
    )
    assert chip_m, "theme chip not found"
    target = chip_m.group("target")
    assert f"surface-{target}" in flat_ids, (
        f"chip data-target={target!r} must point to a surface row id; "
        f"surface ids: {flat_ids!r}"
    )


def test_render_themes_card_activity_dot_needs_input_wins(tmp_path: Path):
    """T15 step 4: theme card carries workspace-style activity dot;
    any member in needs_input → amber (precedence rule mirrors T12)."""
    import re

    snap = _snap_themes_fixture(
        surface_specs=[("a", "needs_input"), ("b", "running"), ("c", "idle")],
    )
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # The themes section must include an activity dot data-activity="needs_input".
    sect_m = re.search(r'<h2>Work themes.*?</section>', html, re.S)
    assert sect_m, "themes section not found"
    section = sect_m.group(0)
    assert re.search(
        r'class="[^"]*activity-dot[^"]*"[^>]*data-activity="needs_input"',
        section, re.S,
    ), "theme card activity dot must be needs_input when any member is needs_input"


def test_render_themes_card_activity_dot_unknown_when_no_agents(tmp_path: Path):
    """T15 step 4 fallthrough: a theme whose members have no agent rows (plain
    shells) renders the dotted-gray dot (data-activity="unknown")."""
    import re

    snap = _snap_themes_fixture(
        surface_specs=[("a", None), ("b", None)],
    )
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    sect_m = re.search(r'<h2>Work themes.*?</section>', html, re.S)
    assert sect_m, "themes section not found"
    section = sect_m.group(0)
    assert re.search(
        r'class="[^"]*activity-dot[^"]*"[^>]*data-activity="unknown"',
        section, re.S,
    ), "theme card activity dot must be unknown when no member has an agent"


def test_render_themes_inline_script_has_scroll_and_pulse(tmp_path: Path):
    """T15 step 5: an inline <script> wires theme chip clicks to
    scrollIntoView + a transient `.pulse` class on the target row."""
    snap = _snap_themes_fixture()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # The script must reference data-target, scrollIntoView with smooth/center,
    # and add+remove the `pulse` class.
    assert "data-target" in html
    assert "scrollIntoView" in html, "inline JS must call scrollIntoView"
    assert "behavior" in html and "smooth" in html, "scrollIntoView must use behavior:'smooth'"
    assert "block" in html and "center" in html, "scrollIntoView must use block:'center'"
    assert "pulse" in html, "inline JS must add the `pulse` class"
    # Add then remove (timeout-based).
    assert "setTimeout" in html, "inline JS must remove `pulse` class via setTimeout"


def test_render_themes_css_has_pulse_keyframes_and_reduced_motion(tmp_path: Path):
    """T15 step 5: a CSS @keyframes drives the pulse, and a
    `prefers-reduced-motion: reduce` rule overrides the animation."""
    import re

    snap = _snap_themes_fixture()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # @keyframes named (e.g.) surface-pulse.
    assert re.search(
        r'@keyframes\s+surface-pulse\b',
        html, re.S,
    ), "CSS must declare @keyframes surface-pulse"
    # Reduced-motion override targeting the pulse selector.
    assert re.search(
        r'@media\s*\(\s*prefers-reduced-motion:\s*reduce\s*\)\s*\{[^}]*\.pulse[^}]*animation:\s*none',
        html, re.S,
    ), "must include prefers-reduced-motion override that disables the pulse animation"


def test_render_surface_row_separator_uses_details_sibling_selector(tmp_path: Path):
    """T14 follow-up: after wrapping rows in <details>, adjacent .surface-row
    summaries are no longer DOM siblings — the <details> roots are. The
    separator rule MUST match adjacent <details.surface-details> pairs and
    paint the border on the summary child."""
    import re

    snap = _snap_surface_row_full()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    assert re.search(
        r'details\.surface-details\s*\+\s*details\.surface-details\s*>\s*summary\.surface-row\s*\{[^}]*border-top\s*:\s*1px\s+solid\s+var\(--border\)',
        html, re.S,
    ), (
        "separator must use `details.surface-details + details.surface-details "
        "> summary.surface-row` with a border-top declaration"
    )

    # And the broken pre-T14 selector must not be present anymore.
    assert not re.search(
        r'\.surface-row\s*\+\s*\.surface-row\s*\{',
        html, re.S,
    ), "legacy `.surface-row + .surface-row` selector must be gone (siblings are <details>, not <summary>)"


def test_render_surface_row_disclosure_chevron_cue_collapsed_and_open(tmp_path: Path):
    """T14 follow-up: the native disclosure marker is suppressed via
    `::-webkit-details-marker { display: none }` + `list-style: none`, so a
    replacement directional cue is required. Use a `::before` chevron that
    renders ▸ when collapsed and ▾ when [open]. Pseudo-elements are
    aria-hidden by spec, so the chevron does not duplicate the UA-managed
    aria-expanded signal."""
    import re

    snap = _snap_surface_row_full()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Collapsed cue: `::before` rule on summary.surface-row with content ▸
    # (encoded either as the literal char or as the CSS escape \25B8).
    collapsed_pat = re.compile(
        r'details\.surface-details\s*>\s*summary\.surface-row::before\s*\{[^}]*content\s*:\s*"(\\25B8|▸)"',
        re.S | re.I,
    )
    assert collapsed_pat.search(html), (
        "must declare a `::before` directional cue on summary.surface-row "
        "with collapsed glyph ▸ (\\25B8)"
    )

    # Open variant: `[open]` flips the chevron to ▾ (\25BE).
    open_pat = re.compile(
        r'details\.surface-details\[open\]\s*>\s*summary\.surface-row::before\s*\{[^}]*content\s*:\s*"(\\25BE|▾)"',
        re.S | re.I,
    )
    assert open_pat.search(html), (
        "must override `::before` content to ▾ (\\25BE) when the <details> "
        "is `[open]`"
    )


def test_render_themes_chip_focuses_summary_with_prevent_scroll(tmp_path: Path):
    """T15 follow-up: theme chip click must move focus to the target row's
    <summary class="surface-row"> using `preventScroll: true` so the focus
    move does not fight the centered scrollIntoView position. Without this,
    keyboard and AT users stay parked on the theme chip even though the
    viewport jumped to the target row.
    """
    import re

    snap = _snap_themes_fixture()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Find the chip-click inline script (the one that already calls scrollIntoView).
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S)
    chip_scripts = [
        s for s in scripts
        if "data-target" in s and "scrollIntoView" in s
    ]
    assert chip_scripts, "could not locate the theme-chip inline <script>"
    script = chip_scripts[0]

    # Must query the target's summary.surface-row before focusing.
    assert re.search(
        r'querySelector\(\s*"summary\.surface-row"\s*\)',
        script,
    ), "chip click handler must querySelector('summary.surface-row') on the target"

    # Must call .focus({ preventScroll: true }) so the focus move does not
    # override the centered scroll position established by scrollIntoView.
    assert re.search(
        r'\.focus\s*\(\s*\{\s*preventScroll\s*:\s*true\s*\}\s*\)',
        script,
    ), "chip click handler must call summary.focus({ preventScroll: true })"

    # Bare .focus() fallback for browsers that don't accept FocusOptions —
    # protects keyboard users on older runtimes.
    assert re.search(r'\.focus\s*\(\s*\)', script), (
        "chip click handler must provide a bare .focus() fallback for "
        "runtimes that reject FocusOptions"
    )
