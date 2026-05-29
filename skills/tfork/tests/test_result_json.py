"""The handoff JSON object for every code in the failure taxonomy."""

import tforklib as ft

HANDOFF_KEYS = {"ok", "code", "human_message", "agent_instruction",
                "retryable", "suggested_next_command"}


def _assert_handoff(err, code, retryable):
    handoff = err.handoff()
    assert set(handoff) == HANDOFF_KEYS
    assert handoff["ok"] is False
    assert handoff["code"] == code
    assert handoff["retryable"] is retryable
    for field in ("human_message", "agent_instruction", "suggested_next_command"):
        assert isinstance(handoff[field], str) and handoff[field]


def test_no_terminal():
    _assert_handoff(ft.err_no_terminal(), "no_terminal", False)


def test_bad_arguments():
    _assert_handoff(ft.err_bad_arguments("missing command"),
                    "bad_arguments", False)


def test_surface_resolution_failed():
    _assert_handoff(ft.err_surface_resolution_failed(),
                    "surface_resolution_failed", False)


def test_split_failed():
    _assert_handoff(ft.err_split_failed("cmux exploded"), "split_failed", True)


def test_spawn_failed():
    _assert_handoff(ft.err_spawn_failed("paste failed"), "spawn_failed", True)


def test_anchor_not_found():
    _assert_handoff(ft.err_anchor_not_found("ghost"),
                    "anchor_not_found", False)


def test_anchor_ambiguous_lists_candidates():
    err = ft.err_anchor_ambiguous("reviewer", [
        {"ref": "surface:7", "workspace_ref": "workspace:1",
         "workspace_title": "Skills"},
        {"ref": "surface:8", "workspace_ref": "workspace:2",
         "workspace_title": "HRI"},
    ])
    _assert_handoff(err, "anchor_ambiguous", False)
    # The candidate refs land in the human message so the user can pick.
    assert "surface:7" in err.human_message
    assert "surface:8" in err.human_message
    # Each candidate's workspace shows up too, so the user can pick by where
    # the tab actually lives rather than guessing which surface ref is which.
    assert "workspace:1" in err.human_message and "Skills" in err.human_message
    assert "workspace:2" in err.human_message and "HRI" in err.human_message


def test_workspace_unknown_carries_requested():
    err = ft.err_workspace_unknown("workspace:99999")
    _assert_handoff(err, "workspace_unknown", False)
    assert "workspace:99999" in err.human_message


def test_workspace_ambiguous_lists_candidates():
    err = ft.err_workspace_ambiguous("ambig", [
        {"ref": "workspace:1", "title": "ambig"},
        {"ref": "workspace:2", "title": "ambig"},
    ])
    _assert_handoff(err, "workspace_ambiguous", False)
    assert "workspace:1" in err.human_message
    assert "workspace:2" in err.human_message


def test_workspace_anchor_conflict():
    _assert_handoff(ft.err_workspace_anchor_conflict(),
                    "workspace_anchor_conflict", False)


def test_taxonomy_codes_all_map_to_nonzero_exits():
    expected = {"no_terminal", "bad_arguments", "surface_resolution_failed",
                "split_failed", "spawn_failed",
                "anchor_not_found", "anchor_ambiguous",
                "workspace_unknown", "workspace_ambiguous",
                "workspace_anchor_conflict"}
    assert set(ft.EXIT_CODES) == expected
    assert all(code != 0 for code in ft.EXIT_CODES.values())
