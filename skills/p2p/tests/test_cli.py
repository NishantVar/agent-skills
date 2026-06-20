"""Unit tests for cli helpers that don't need a registry or transport."""

from __future__ import annotations

from p2plib import cli
from p2plib import bootstrap


def _parse(argv: list[str]):
    return cli.build_parser().parse_args(argv)


def test_rerun_argv_preserves_inline_message():
    """Regression for codex_reviewer finding on 2389fde: --message body
    was dropped from rerun_argv, making empty_message / title_collision /
    info_needed non-replayable for inline-message callers."""
    args = _parse(["send", "--peer", "p", "--my-title", "me",
                   "--message", "hello world"])
    rerun = cli._build_rerun_argv(args)
    assert "--message" in rerun
    assert rerun[rerun.index("--message") + 1] == "hello world"


def test_rerun_argv_preserves_message_file():
    args = _parse(["send", "--peer", "p", "--my-title", "me",
                   "--message-file", "/tmp/x.txt"])
    rerun = cli._build_rerun_argv(args)
    assert "--message-file" in rerun
    assert rerun[rerun.index("--message-file") + 1] == "/tmp/x.txt"
    assert "--message" not in rerun


def test_rerun_argv_preserves_both_when_both_supplied():
    """The CLI accepts both flags; the rerun must replay verbatim
    rather than silently picking one."""
    args = _parse(["send", "--peer", "p", "--my-title", "me",
                   "--message", "inline",
                   "--message-file", "/tmp/x.txt"])
    rerun = cli._build_rerun_argv(args)
    assert "--message" in rerun
    assert "--message-file" in rerun


def test_rerun_argv_carries_scope_and_one_way():
    args = _parse(["send", "--peer", "p", "--my-title", "me",
                   "--workspace", "workspace:7", "--window", "window:2",
                   "--one-way", "--message", "hi"])
    rerun = cli._build_rerun_argv(args)
    assert "--workspace" in rerun
    assert rerun[rerun.index("--workspace") + 1] == "workspace:7"
    assert "--window" in rerun
    assert rerun[rerun.index("--window") + 1] == "window:2"
    assert "--one-way" in rerun


def test_bootstrap_parser_returns_workspace_and_window():
    text = "\n".join([
        "[p2p-bootstrap] You have an incoming peer-messaging connection.",
        "peer_title=caller",
        "peer_surface=surface:100",
        "peer_workspace=workspace:1",
        "peer_window=window:1",
        "suggested_title=worker",
    ])
    parsed = bootstrap.parse_bootstrap_text(text)
    assert parsed == {
        "peer_title": "caller",
        "peer_surface": "surface:100",
        "peer_workspace": "workspace:1",
        "peer_window": "window:1",
        "suggested_title": "worker",
    }
