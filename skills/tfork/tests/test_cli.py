"""Argument parsing and the ``main`` entry point."""

import json

import pytest

import tforklib as ft


def test_parse_args_basic():
    args = ft.parse_args(["--placement", "left", "--", "claude"])
    assert args.placement == "left"
    assert args.command == ["claude"]
    assert args.type is None
    assert args.anchor is None
    assert args.delay is None


def test_parse_args_placement_defaults_to_none():
    """No explicit --placement leaves the argparse value at None; the
    orchestrator picks 'right' when no --workspace is also given."""
    args = ft.parse_args(["--", "claude"])
    assert args.placement is None


def test_parse_args_rejects_retired_new_workspace_placement():
    """The 'new-workspace' value was retired in favour of --workspace."""
    with pytest.raises(ft.ForkError) as exc:
        ft.parse_args(["--placement", "new-workspace", "--", "claude"])
    assert exc.value.code == "bad_arguments"


def test_parse_args_accepts_workspace():
    args = ft.parse_args(["--workspace", "exp1", "--", "claude"])
    assert args.workspace == "exp1"


def test_parse_args_accepts_anchor():
    args = ft.parse_args(["--anchor", "reviewer", "--", "claude"])
    assert args.anchor == "reviewer"


def test_parse_args_accepts_window():
    args = ft.parse_args(["--window", "new", "--", "claude"])
    assert args.window == "new"


def test_parse_args_keeps_the_commands_own_flags():
    args = ft.parse_args(["--", "claude", "--dangerously-skip-permissions"])
    assert args.command == ["claude", "--dangerously-skip-permissions"]


def test_parse_args_bad_placement_raises_bad_arguments():
    with pytest.raises(ft.ForkError) as exc:
        ft.parse_args(["--placement", "sideways", "--", "claude"])
    assert exc.value.code == "bad_arguments"


def test_parse_args_negative_delay_raises_bad_arguments():
    with pytest.raises(ft.ForkError) as exc:
        ft.parse_args(["--delay", "-3", "--", "claude"])
    assert exc.value.code == "bad_arguments"


def test_parse_args_non_integer_delay_raises_bad_arguments():
    with pytest.raises(ft.ForkError) as exc:
        ft.parse_args(["--delay", "soon", "--", "claude"])
    assert exc.value.code == "bad_arguments"


def test_parse_args_bad_type_raises_bad_arguments():
    """``--type`` accepts agent or command only; no ``auto`` sentinel."""
    with pytest.raises(ft.ForkError) as exc:
        ft.parse_args(["--type", "auto", "--", "claude"])
    assert exc.value.code == "bad_arguments"


def test_main_prints_a_handoff_object_on_bad_arguments(capsys):
    code = ft.main(["--placement", "sideways", "--", "claude"])
    assert code != 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["code"] == "bad_arguments"
