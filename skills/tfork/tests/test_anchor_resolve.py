"""Anchor resolution — accepts a surface ref directly, otherwise looks the
value up against every live surface's tab title."""

import pytest

import tforklib as ft
from tforklib import terminal


def _tree(*titled_refs):
    """Build a minimal ``cmux tree --all`` document carrying one surface per
    (title, ref) pair — every surface goes into the same workspace."""
    surfaces = [{"title": title, "ref": ref} for title, ref in titled_refs]
    return {
        "windows": [{
            "workspaces": [{
                "ref": "workspace:1",
                "title": "Default",
                "panes": [{"surfaces": surfaces}],
            }],
        }],
    }


def _multi_ws_tree(*surfaces_per_ws):
    """Each arg is ``(workspace_ref, workspace_title, [(title, ref), ...])`` —
    used to model an ambiguous anchor that resolves to surfaces sitting in
    different workspaces."""
    workspaces = []
    for ws_ref, ws_title, titled_refs in surfaces_per_ws:
        workspaces.append({
            "ref": ws_ref,
            "title": ws_title,
            "panes": [{"surfaces": [
                {"title": t, "ref": r} for t, r in titled_refs
            ]}],
        })
    return {"windows": [{"workspaces": workspaces}]}


def test_surface_ref_is_returned_verbatim(monkeypatch):
    """``surface:N`` is structurally unambiguous; no tree lookup is needed."""
    monkeypatch.setattr(terminal, "_cmux_tree",
                        lambda: (_ for _ in ()).throw(AssertionError("called")))
    assert ft.resolve_anchor("surface:42") == "surface:42"


def test_unique_tab_title_resolves(monkeypatch):
    monkeypatch.setattr(terminal, "_cmux_tree",
                        lambda: _tree(("reviewer", "surface:7"),
                                      ("planner", "surface:9")))
    assert ft.resolve_anchor("reviewer") == "surface:7"


def test_missing_tab_raises_anchor_not_found(monkeypatch):
    monkeypatch.setattr(terminal, "_cmux_tree",
                        lambda: _tree(("planner", "surface:9")))
    with pytest.raises(ft.ForkError) as exc:
        ft.resolve_anchor("ghost")
    assert exc.value.code == "anchor_not_found"


def test_ambiguous_tab_raises_anchor_ambiguous_with_candidates(monkeypatch):
    monkeypatch.setattr(terminal, "_cmux_tree",
                        lambda: _tree(("reviewer", "surface:7"),
                                      ("reviewer", "surface:8")))
    with pytest.raises(ft.ForkError) as exc:
        ft.resolve_anchor("reviewer")
    assert exc.value.code == "anchor_ambiguous"
    # Both candidate refs are surfaced in the handoff so the user can pick.
    assert "surface:7" in exc.value.human_message
    assert "surface:8" in exc.value.human_message


def test_ambiguous_tab_lists_each_candidate_by_workspace(monkeypatch):
    """When the same tab title exists in multiple workspaces, the human
    message names each workspace so the user can disambiguate by where the
    tab lives rather than guessing which ``surface:N`` is which."""
    monkeypatch.setattr(
        terminal, "_cmux_tree",
        lambda: _multi_ws_tree(
            ("workspace:23", "Skills", [("habits_codex", "surface:340")]),
            ("workspace:31", "HRI",    [("habits_codex", "surface:401")]),
        ),
    )
    with pytest.raises(ft.ForkError) as exc:
        ft.resolve_anchor("habits_codex")
    msg = exc.value.human_message
    assert exc.value.code == "anchor_ambiguous"
    assert "surface:340" in msg and "workspace:23" in msg and "Skills" in msg
    assert "surface:401" in msg and "workspace:31" in msg and "HRI" in msg
