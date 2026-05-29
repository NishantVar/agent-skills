"""T20 — Identifier-strip audit + grep-guard.

The rule (qa_lead addendum-2 hard-block): bare ``workspace:N`` / ``surface:N``
ref literals must appear ONLY in the five allowed homes where the ref IS
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
5. **Blocked-ref chip** in ``_blocked.html.j2`` — the
   ``<span class="chip blocked-ref">{{ s.ref }}</span>`` on each blocked-work
   card (T11). Same role as the surface copy-ref chip: the ref IS the content
   the user grabs to focus the blocked surface in cmux.

(The plan listed footer ``run_id`` as the third home, but T18 footer is
deferred to v1.1.1 and T17 failures banner landed instead at b838422; for
v1.1 the third allowed home is the failures-banner target. The workspace
copy-ref chip is a fourth home — see the deviation note in the plan-doc
patch; the audit's first run flagged the pre-existing ``<span class="chip">``
on the workspace card header as a leak, and the surgical fix was to
promote it to a proper copy-ref chip rather than strip the ref entirely.
The blocked-ref chip is a fifth home — the T20 follow-up audit caught that
the T11 blocked-work banner renders a real copy-ref chip that was neither
sanctioned in the allowed-class list nor exercised by the audit fixture.)

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
  list contains a ``surface:N`` target AND whose agents include a
  ``needs_input`` row so all five allowed homes fire, then asserts every
  ``workspace:\\d+`` / ``surface:\\d+`` occurrence in the rendered HTML
  lives inside one of the five allowed-element class hooks. This catches
  the harder case where a Jinja expression that legitimately resolves to
  a ref is placed in a wrong location. With ``bs4`` available, both text
  nodes AND element attribute values are validated; the regex-window
  fallback catches attribute leaks "for free" because window context is
  matched against the raw HTML string (attribute content is just part
  of that string).

BeautifulSoup is not a project dependency; the rendered-HTML scan uses a
substring-window heuristic (200 chars before/after each occurrence) when
``bs4`` is unavailable. With ``bs4`` available the scan walks ancestors
explicitly for both text-node refs and attribute-value refs.
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
    ("blocked-ref-start", "blocked-ref-end"),
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
    """Populated snapshot exercising all five allowed ref homes.

    Two surfaces in one workspace: one ``running`` agent (exercises the
    surface copy-ref chip + diagnostic line) and one ``needs_input`` agent
    (exercises the blocked-ref chip via ``_blocked.html.j2`` rendering).
    The workspace card itself exercises the workspace-copy-ref chip. The
    failures list carries a ``target='surface:1'`` so the rendered HTML
    contains a ref inside the failures-banner ``<code>`` element.
    """
    surface_running = Surface(
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
    surface_blocked = Surface(
        ref="surface:2",
        pane_ref="pane:2",
        workspace_ref="workspace:1",
        kind="terminal",
        title="claude_code reviewer",
        tty="ttys002",
        cwd="/home/u/p",
        cpu_pct=4.5,
        mem_bytes=104857600,
        is_agent=True,
    )
    workspace = Workspace(
        ref="workspace:1",
        title="Project A",
        window_ref="window:1",
        surfaces=[surface_running, surface_blocked],
    )
    summary_running = Summary(
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
    summary_blocked = Summary(
        text="awaiting reviewer sign-off",
        state_hint="needs_input",
        needs_input_reason="awaiting permission for action 1",
        confidence=0.9,
        cache_hit=False,
        cached_at=datetime(2026, 5, 27, 14, 29, 30, tzinfo=timezone.utc),
        prompt_version=1,
        screen_hash="beef",
        redactions_applied=[],
        redaction_summary="",
    )
    agent_running = Agent(
        surface_ref="surface:1",
        workspace_ref="workspace:1",
        type="claude_code",
        type_source="cmux_tag",
        type_confidence=1.0,
        state="running",
        state_source="cmux_tag",
        pid=42,
        summary=summary_running,
    )
    agent_blocked = Agent(
        surface_ref="surface:2",
        workspace_ref="workspace:1",
        type="claude_code",
        type_source="cmux_tag",
        type_confidence=1.0,
        state="needs_input",
        state_source="cmux_tag",
        pid=43,
        summary=summary_blocked,
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
        agents=[agent_running, agent_blocked],
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
    'class="chip blocked-ref"',
)

# Class names (bare, no ``class="..."`` wrapping) for ancestor-walk checks
# in the bs4 path. Must stay in sync with ALLOWED_CLASS_HOOKS above.
ALLOWED_CLASSES = (
    "surface-copy-ref",
    "surface-diagnostic",
    "failures-banner",
    "workspace-copy-ref",
    "blocked-ref",
)


def _ancestor_has_allowed_class(el, allowed: tuple[str, ...]) -> bool:
    """Return True iff ``el`` or any ancestor carries one of ``allowed`` in its
    ``class`` attribute. Used by the bs4 path for both text-node refs and
    attribute-value refs so the two passes share identical ancestor semantics.
    """
    cur = el
    while cur is not None:
        # bs4 Tag.get may return a list (for ``class``) or None on NavigableString.
        getter = getattr(cur, "get", None)
        classes = getter("class") if getter is not None else None
        if classes:
            for c in allowed:
                if c in classes:
                    return True
        cur = getattr(cur, "parent", None)
    return False


def test_no_bare_workspace_or_surface_ref_outside_allowed_elements_in_rendered_html(
    tmp_path: Path,
):
    """Rendered-HTML scan: every ``workspace:\\d+`` / ``surface:\\d+`` in
    the rendered output must live inside one of the five allowed-element
    class hooks (surface copy-ref chip, diagnostic line, failures banner,
    workspace copy-ref chip, blocked-ref chip).

    With ``bs4`` available, the scan validates BOTH text nodes AND every
    element's attribute values via ``_ancestor_has_allowed_class``. This
    closes the original gap where ``soup.find_all(string=pattern)`` only
    matched text nodes — a ref placed in a non-allowed element attribute
    (e.g. ``<h2 title="surface:88">``) would otherwise slip past.

    The regex-window fallback catches attribute leaks "for free": the
    rendered HTML string contains attribute content as plain substring,
    so a 200-char window around a ref match will include the surrounding
    element open-tag (with its class= hook) regardless of whether the ref
    came from a text node or an attribute value.
    """
    snap = _snap_with_surface_failure()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()

    # Sanity guard 1: the blocked banner must have rendered. Without this
    # the blocked-ref allowed-home coverage is vacuous (the partial only
    # renders when at least one agent is in needs_input state). Reviewer
    # caught exactly this regression in the T20 follow-up.
    assert "blocked-banner" in html, (
        "fixture must render the blocked banner (_blocked.html.j2) so the "
        "blocked-ref allowed home is actually exercised; add a needs_input "
        "agent to _snap_with_surface_failure"
    )

    # Prefer bs4 ancestor walk if available; else fall back to a 200-char
    # substring window around each occurrence. The fallback is coarser but
    # adequate because the allowed-element class hooks all appear on the
    # same element or a very close ancestor of every rendered ref, and
    # window-context substring match handles attribute leaks naturally
    # (attribute content is part of the raw HTML string).
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

        # Pass 1: walk text nodes that contain a ref.
        text_node_count = 0
        for node in soup.find_all(string=pattern):
            text_node_count += 1
            assert _ancestor_has_allowed_class(node.parent, ALLOWED_CLASSES), (
                f"ref text {node!r} rendered outside the allowed homes "
                f"(surface copy-ref chip, diagnostic line, failures banner, "
                f"workspace copy-ref chip, blocked-ref chip)"
            )

        # Pass 2: walk every element's attribute values. attrs may be str or
        # list[str] (e.g. ``class`` is a list); normalize before scanning.
        attr_count = 0
        for el in soup.find_all(True):
            for attr_name, attr_val in el.attrs.items():
                values = attr_val if isinstance(attr_val, list) else [attr_val]
                for v in values:
                    if isinstance(v, str) and pattern.search(v):
                        attr_count += 1
                        assert _ancestor_has_allowed_class(
                            el, ALLOWED_CLASSES
                        ), (
                            f"ref in {el.name}[{attr_name}]={v!r} rendered "
                            f"outside the allowed homes (surface copy-ref "
                            f"chip, diagnostic line, failures banner, "
                            f"workspace copy-ref chip, blocked-ref chip)"
                        )

        # Sanity: BOTH passes must have hit something, otherwise one of the
        # two scan paths is silently vacuous and could miss real leaks.
        assert text_node_count >= 1, (
            "fixture produced no text-node ref occurrences; the text-node "
            "scan path is vacuously green — strengthen the fixture"
        )
        assert attr_count >= 1, (
            "fixture produced no attribute-value ref occurrences; the "
            "attribute scan path is vacuously green — the existing "
            "title=\"cmux focus {{ s.ref }}\" / {{ ws.ref }} patterns "
            "should naturally satisfy this"
        )
        return

    # Regex-fallback path: for each match, inspect a window of context.
    # Attribute leaks are caught for free because attribute content is part
    # of the raw HTML string the window slides over.
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


# T22 (qa_lead HOLD) + follow-up (Reviewer HOLD) — copy-ref chip surgery.
#
# Two-pillar rule (6th audit rule, tightened): for every chip with class
# surface-copy-ref, workspace-copy-ref, or blocked-ref:
#   (1) get_text(strip=True) MUST equal the icon glyph "⧉" (U+29C9) —
#       exact equality, not merely "not a ref". The original "not-the-ref"
#       form was too weak: it passed for empty text, "copy", or any
#       label-shaped string.
#   (2) data-cmux-focus attribute MUST be present AND its value MUST match
#       the ref regex (?:workspace|surface):\d+ — without this, the
#       machine-readable ref is gone and the chip is useless.
#
# surface-diagnostic and failures-banner remain exempt: those are
# bug-report / failure-target affordances where the ref IS the content.
COPY_REF_CHIP_CLASSES = (
    "surface-copy-ref",
    "workspace-copy-ref",
    "blocked-ref",
)

CHIP_ICON = "⧉"  # ⧉ U+29C9 — the canonical chip glyph.


def _chip_text_and_focus(
    soup, chip_class: str
) -> list[tuple[str, str | None]]:
    """Return ``[(text, data_cmux_focus_or_None), ...]`` for every chip of
    ``chip_class``. Empty list = no chips of that class rendered (the
    non-vacuity guard tests count >= 1 separately).
    """
    out: list[tuple[str, str | None]] = []
    for el in soup.find_all(class_=chip_class):
        text = el.get_text(strip=True)
        focus = el.get("data-cmux-focus")
        out.append((text, focus))
    return out


def test_copy_ref_chip_text_is_icon_and_has_data_focus(tmp_path: Path):
    """T22 follow-up (Reviewer HOLD): two-pillar rule.

    (1) Every .surface-copy-ref / .workspace-copy-ref / .blocked-ref chip
        must render exactly the icon glyph ⧉ as visible text.
    (2) Every such chip must carry data-cmux-focus whose value matches the
        ref regex.

    Requires bs4 (rule is a DOM check; the regex-window fallback can't
    distinguish text nodes from attribute values or enforce exact text).
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        import pytest

        # T22 follow-up #2 (Reviewer HOLD): bs4 is now pinned in
        # pyproject.toml [project.optional-dependencies].test, so a missing
        # bs4 is a packaging regression rather than an environmental quirk.
        # Fail loudly instead of silently skipping — the addendum-2 chip rule
        # is hard-blocking and MUST run on every suite execution.
        pytest.fail(
            "bs4 unavailable but is a declared test dependency "
            "(beautifulsoup4>=4.12 in [project.optional-dependencies].test); "
            "the T22 chip rule is hard-blocking and must not skip"
        )

    snap = _snap_with_surface_failure()
    html_path, _json_path = render_snapshot(snap, tmp_path)
    html = html_path.read_text()
    soup = BeautifulSoup(html, "html.parser")

    bad_text: list[tuple[str, str]] = []  # (class, observed_text)
    bad_focus: list[tuple[str, str | None]] = []  # (class, observed_attr)

    for chip_class in COPY_REF_CHIP_CLASSES:
        chips = _chip_text_and_focus(soup, chip_class)
        # Non-vacuity: every class must render at least once in the
        # fixture so each pillar is exercised per class.
        assert len(chips) >= 1, (
            f"fixture must render at least one .{chip_class} chip so the "
            f"two-pillar rule is exercised; saw {len(chips)}"
        )
        for text, focus in chips:
            # Pillar 1: exact icon-glyph text.
            if text != CHIP_ICON:
                bad_text.append((chip_class, text))
            # Pillar 2: data-cmux-focus present AND ref-shaped.
            if focus is None or not _REF_LITERAL_RE.fullmatch(focus):
                bad_focus.append((chip_class, focus))

    assert not bad_text, (
        f"chip text must equal icon glyph {CHIP_ICON!r} (U+29C9); offending "
        f"chips (class, observed_text): {bad_text!r}"
    )
    assert not bad_focus, (
        "chip missing data-cmux-focus attr (or value does not match the "
        f"ref regex); offending chips (class, observed_attr): {bad_focus!r}"
    )
