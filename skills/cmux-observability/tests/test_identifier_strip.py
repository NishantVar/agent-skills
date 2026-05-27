"""T20 — Identifier-strip audit + grep-guard.

The rule (qa_lead addendum-2 hard-block): bare ``workspace:N`` / ``surface:N``
ref literals must appear ONLY in the three allowed homes where the ref IS
the content:

1. **Copy-ref chip** in ``_agent_row.html.j2`` — the
   ``<span class="chip surface-copy-ref">{{ s.ref }}</span>`` element.
2. **Diagnostic line** in ``_agent_row.html.j2`` — the muted
   ``<div class="surface-diagnostic">…</div>`` at the bottom of the expanded
   panel; six-field debug stripe, refs intentional.
3. **Failures-banner target** in ``_failures.html.j2`` — ``<code>{{ f.target }}</code>``
   inside ``<li>`` where the failure IS about a specific surface/workspace.
4. **Workspace copy-ref chip** in ``_workspace.html.j2`` — the
   ``<span class="chip workspace-copy-ref">{{ ws.ref }}</span>`` on the
   workspace card header. Parallel to the surface copy-ref chip on the
   surface row: the ref IS the content the user grabs.

(The plan listed footer ``run_id`` as the third home, but T18 footer is
deferred to v1.1.1 and T17 failures banner landed instead at b838422; for
v1.1 the third allowed home is the failures-banner target. The workspace
copy-ref chip is a fourth home — see the deviation note in the plan-doc
patch; the audit's first run flagged the pre-existing ``<span class="chip">``
on the workspace card header as a leak, and the surgical fix was to
promote it to a proper copy-ref chip rather than strip the ref entirely.)

This module installs a two-layer scan:

* **Template-source scan** — walks every ``*.html.j2`` under
  ``cmux_observability/render/templates/`` and asserts the literal
  substrings ``workspace:`` and ``surface:`` never appear outside the
  marker-bracketed allowed-home blocks. Currently the codebase uses Jinja
  expressions exclusively for ref rendering (e.g. ``{{ s.ref }}``,
  ``{{ agent.surface_ref }}``), so the scan has nothing to catch in the
  current source — its job is to fail the moment someone hard-codes a
  literal ref into template chrome (title attr, placeholder, heading, …).

* **Rendered-HTML scan** — renders a populated snapshot whose failures
  list contains a ``surface:N`` target so all three allowed homes fire,
  then asserts every ``workspace:\\d+`` / ``surface:\\d+`` occurrence in
  the rendered HTML lives inside one of the three allowed-element class
  hooks. This catches the harder case where a Jinja expression that
  legitimately resolves to a ref is placed in a wrong location.

BeautifulSoup is not a project dependency; the rendered-HTML scan uses a
substring-window heuristic (200 chars before/after each occurrence). If
``bs4`` becomes available later, the scan can be tightened to walk
ancestors; see the import guard at the top of the rendered-HTML test.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from cmux_observability.errors import Failure
from cmux_observability.model import (
    Agent,
    Snapshot,
    Summary,
    Surface,
    Workspace,
)
from cmux_observability.render.render import render_snapshot

TEMPLATES_DIR = (
    Path(__file__).resolve().parent.parent
    / "cmux_observability"
    / "render"
    / "templates"
)

# Marker comment pairs. Each pair (start, end) brackets a region that is
# allowed to contain literal ``workspace:`` / ``surface:`` text in the
# template source. The strip pass below removes everything between (and
# including) each pair before scanning the remaining template body.
MARKER_PAIRS = [
    ("copy-ref-chip-start", "copy-ref-chip-end"),
    ("diagnostic-line-start", "diagnostic-line-end"),
    ("failures-target-start", "failures-target-end"),
    ("workspace-copy-ref-start", "workspace-copy-ref-end"),
]


_JINJA_COMMENT_RE = re.compile(r"\{#.*?#\}", re.DOTALL)


def _strip_marker_regions(source: str) -> str:
    """Remove every marker-bracketed region, then strip all Jinja comments.

    Two-pass strip:

    1. Remove each marker pair and everything between it. This drops the
       allowed-home blocks (chip / diagnostic / failures-target /
       workspace-copy-ref) wholesale.

    2. Drop every remaining ``{# ... #}`` Jinja comment. Jinja comments
       never reach the rendered output, so a literal ``surface:N`` or
       ``workspace:N`` inside a comment is documentation, not chrome. The
       header comments in ``_agent_row.html.j2`` that explain the marker
       rule itself reference these tokens — without this second pass they
       would trip the scan even though they never render.

    Tolerant of whitespace inside the ``{# ... #}`` comment delimiters
    (Jinja allows leading/trailing spaces around the marker text).
    """
    stripped = source
    for start, end in MARKER_PAIRS:
        pattern = re.compile(
            r"\{#\s*"
            + re.escape(start)
            + r"\s*#\}.*?\{#\s*"
            + re.escape(end)
            + r"\s*#\}",
            re.DOTALL,
        )
        stripped = pattern.sub("", stripped)
    stripped = _JINJA_COMMENT_RE.sub("", stripped)
    return stripped


_REF_LITERAL_RE = re.compile(r"(?:workspace|surface):\d+")


def test_no_bare_workspace_or_surface_ref_in_template_chrome():
    """Template-source scan: ref-formatted literals ``workspace:\\d+`` /
    ``surface:\\d+`` must not appear in any ``*.html.j2`` template outside
    marker-bracketed regions.

    Today the codebase has no such literals (refs are rendered via Jinja
    expressions, e.g. ``{{ s.ref }}``), so this scan is vacuously green.
    It exists to fail the moment someone hard-codes a literal ref into
    template chrome (title attr, placeholder, heading, hero copy, …).

    The regex matches ``workspace:`` or ``surface:`` followed by ``\\d+``;
    this avoids false positives on CSS custom properties like
    ``--surface: #f6f7f9;`` in ``snapshot.html.j2``'s inline ``<style>``
    block. Ref literals always carry a numeric ID, so the discriminator
    is sound.
    """
    template_files = sorted(TEMPLATES_DIR.glob("*.html.j2"))
    assert template_files, f"no templates found under {TEMPLATES_DIR}"

    for tpl in template_files:
        raw = tpl.read_text()
        stripped = _strip_marker_regions(raw)
        match = _REF_LITERAL_RE.search(stripped)
        assert match is None, (
            f"ref literal {match.group()!r} found in template chrome of "
            f"{tpl} (outside marker-bracketed allowed-home regions). "
            f"Refs may only render inside the marker-bracketed allowed "
            f"homes; if this is a legitimate new home, wrap it in a "
            f"marker pair and add the pair to MARKER_PAIRS."
        )


def _snap_with_surface_failure() -> Snapshot:
    """Populated snapshot exercising all three allowed ref homes.

    The failures list carries a ``target='surface:1'`` so the rendered HTML
    contains a ref inside the failures-banner ``<code>`` element. The agent
    row renders ``s.ref`` in the copy-ref chip and ``agent.surface_ref`` /
    ``agent.workspace_ref`` in the diagnostic line.
    """
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
        title="Project A",
        window_ref="window:1",
        surfaces=[surface],
    )
    summary = Summary(
        text="writing pytest fixtures",
        state_hint="running",
        needs_input_reason=None,
        confidence=0.9,
        cache_hit=False,
        cached_at=datetime(2026, 5, 27, 14, 29, 0, tzinfo=timezone.utc),
        prompt_version=1,
        screen_hash="dead",
        redactions_applied=[],
        redaction_summary="",
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
    # Failure target IS a ref — the failures-banner target home must accept it.
    failure = Failure(
        component="summarizer",
        target="surface:1",
        message="screen capture timed out",
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
        failures=[failure],
    )


# Allowed-element class hooks. A ref occurrence in the rendered HTML must
# sit inside markup that includes one of these substrings in its nearby
# context (or, with bs4, in one of its ancestors).
ALLOWED_CLASS_HOOKS = (
    'class="chip surface-copy-ref"',
    'class="surface-diagnostic"',
    'class="failures-banner"',
    'class="chip workspace-copy-ref"',
)


def test_no_bare_workspace_or_surface_ref_outside_allowed_elements_in_rendered_html(
    tmp_path: Path,
):
    """Rendered-HTML scan: every ``workspace:\\d+`` / ``surface:\\d+`` in
    the rendered output must live inside one of the three allowed-element
    class hooks (copy-ref chip, diagnostic line, failures-banner).
    """
    snap = _snap_with_surface_failure()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Prefer bs4 ancestor walk if available; else fall back to a 200-char
    # substring window around each occurrence. The fallback is coarser but
    # adequate because the three allowed-element class hooks all appear on
    # the same element or a very close ancestor of every rendered ref.
    try:
        from bs4 import BeautifulSoup  # type: ignore  # noqa: F401

        _have_bs4 = True
    except ImportError:
        _have_bs4 = False

    pattern = re.compile(r"(?:workspace|surface):\d+")
    occurrences = list(pattern.finditer(html))

    # Sanity: the fixture must produce at least one ref occurrence,
    # otherwise the test is vacuously green and proves nothing.
    assert len(occurrences) >= 1, (
        "fixture produced no ref occurrences; the rendered-HTML scan would "
        "be vacuously green — strengthen the fixture"
    )

    if _have_bs4:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        # Walk text nodes that contain a ref and check ancestors for the
        # allowed class hooks.
        for node in soup.find_all(string=pattern):
            ancestor = node.parent
            ok = False
            while ancestor is not None:
                classes = ancestor.get("class") or []
                if (
                    "surface-copy-ref" in classes
                    or "surface-diagnostic" in classes
                    or "failures-banner" in classes
                    or "workspace-copy-ref" in classes
                ):
                    ok = True
                    break
                ancestor = ancestor.parent
            assert ok, (
                f"ref text {node!r} rendered outside the allowed homes "
                f"(surface copy-ref chip, diagnostic line, failures banner, "
                f"workspace copy-ref chip)"
            )
        return

    # Regex-fallback path: for each match, inspect a window of context.
    window = 200
    for m in occurrences:
        lo = max(0, m.start() - window)
        hi = min(len(html), m.end() + window)
        ctx = html[lo:hi]
        if not any(hook in ctx for hook in ALLOWED_CLASS_HOOKS):
            raise AssertionError(
                f"ref {m.group()!r} at offset {m.start()} rendered outside "
                f"the allowed homes. Context window:\n{ctx}"
            )
