"""End-to-end of send.send with mocked cmux transport."""

from __future__ import annotations

import json
import os
import time

import pytest

from p2plib import registry, send
from fake_cmux import FakeCmux


MY_SURFACE = "surface:100"
MY_WS = "workspace:1"


def _seed_self(tmp_registry, name="me"):
    p = registry.manifest_path(MY_SURFACE)
    p.write_text(json.dumps({
        "name": name, "surface_ref": MY_SURFACE,
        "started_at": 1, "last_seen": int(time.time()),
    }))


@pytest.fixture
def fc(monkeypatch):
    fc = FakeCmux()
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref=MY_SURFACE, title="me")
    fc.apply(monkeypatch, my_surface_ref=MY_SURFACE)
    return fc


def test_live_by_manifest_name_sends_plain_message(tmp_registry, fc):
    _seed_self(tmp_registry)
    fc.add(workspace_ref="workspace:2", workspace_title="Other",
           surface_ref="surface:200", title="anything")
    registry.register("peer_a", "surface:200",
                      live_set={MY_SURFACE, "surface:200"})

    out = send.send("peer_a", "hello there", my_name=None,
                    fallback_self_name=None, rerun_argv=[])
    assert out["ok"]
    assert out["kind"] == "message"
    assert out["resolved_by"] == "manifest_name"
    assert out["canonical_name"] == "peer_a"
    assert out["surface"] == "surface:200"
    surf, ws, text = fc.sent[0]
    assert surf == "surface:200"
    assert ws == "workspace:2"
    assert text == "[from: me] hello there"


def test_live_by_tab_no_manifest_sends_bootstrap_suggesting_addressed(
        tmp_registry, fc):
    _seed_self(tmp_registry)
    fc.add(workspace_ref="workspace:2", workspace_title="Other",
           surface_ref="surface:200", title="claude_new")
    out = send.send("claude_new", "hi", my_name=None,
                    fallback_self_name=None, rerun_argv=[])
    assert out["ok"]
    assert out["kind"] == "bootstrap"
    assert out["resolved_by"] == "tab_title_first_contact"
    assert out["canonical_name"] is None
    text = fc.sent[0][2]
    assert "[p2p-bootstrap]" in text
    assert "suggested_name=claude_new" in text
    assert "First message from me: hi" in text


def test_live_by_tab_with_manifest_uses_canonical(tmp_registry, fc):
    _seed_self(tmp_registry)
    fc.add(workspace_ref="workspace:2", workspace_title="Other",
           surface_ref="surface:200", title="display-tab")
    registry.register("canonical_one", "surface:200",
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("display-tab", "hi", my_name=None,
                    fallback_self_name=None, rerun_argv=[])
    assert out["ok"]
    assert out["kind"] == "message"
    assert out["resolved_by"] == "tab_title_to_manifest"
    assert out["canonical_name"] == "canonical_one"
    text = fc.sent[0][2]
    assert text == "[from: me] hi"


def test_stale_peer_bootstraps_with_canonical_not_addressed(
        tmp_registry, fc):
    _seed_self(tmp_registry)
    fc.add(workspace_ref="workspace:2", workspace_title="Other",
           surface_ref="surface:200", title="some-tab")
    old = int(time.time()) - registry.TTL_SECONDS - 60
    p = registry.manifest_path("surface:200")
    p.write_text(json.dumps({
        "name": "stalewalker", "surface_ref": "surface:200",
        "started_at": old, "last_seen": old,
    }))
    out = send.send("some-tab", "wake up", my_name=None,
                    fallback_self_name=None, rerun_argv=[])
    assert out["ok"]
    assert out["kind"] == "bootstrap"
    assert out["peer_status"] == "stale"
    assert out["canonical_name"] == "stalewalker"
    text = fc.sent[0][2]
    # Suggested name must be the canonical manifest name, not "some-tab".
    assert "suggested_name=stalewalker" in text
    assert "suggested_name=some-tab" not in text


def test_ambiguous_tab_returns_handoff(tmp_registry, fc):
    _seed_self(tmp_registry)
    fc.add(workspace_ref="workspace:2", workspace_title="A",
           surface_ref="surface:200", title="claude")
    fc.add(workspace_ref="workspace:3", workspace_title="B",
           surface_ref="surface:300", title="claude")
    out = send.send("claude", "x", my_name=None,
                    fallback_self_name=None, rerun_argv=[])
    assert out["ok"] is False
    assert out["code"] == "peer_ambiguous"
    refs = {c["ref"] for c in out["candidates"]}
    assert refs == {"surface:200", "surface:300"}
    assert fc.sent == []


def test_unregistered_no_self_name_auto_derives_from_surface(
        tmp_registry, fc):
    """Self-naming must never bounce to the user. With no --my-name and
    no bootstrap-suggested-name, default to agent_<surface_num>."""
    fc.add(workspace_ref="workspace:2", workspace_title="O",
           surface_ref="surface:200", title="peer")
    registry.register("peer", "surface:200",
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("peer", "hi", my_name=None,
                    fallback_self_name=None, rerun_argv=["x"])
    assert out["ok"]
    me = registry.get_self(MY_SURFACE)
    # MY_SURFACE = "surface:100"
    assert me["name"] == "agent_100"
    # And the [from: ...] prefix uses the auto-derived name.
    text = fc.sent[0][2]
    assert text.startswith("[from: agent_100]")


def test_unregistered_autoregisters_with_my_name(tmp_registry, fc):
    fc.add(workspace_ref="workspace:2", workspace_title="O",
           surface_ref="surface:200", title="peer")
    registry.register("peer", "surface:200",
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("peer", "hi", my_name="brand_new",
                    fallback_self_name=None, rerun_argv=[])
    assert out["ok"]
    me = registry.get_self(MY_SURFACE)
    assert me["name"] == "brand_new"


def test_unregistered_uses_fallback_self_name(tmp_registry, fc):
    fc.add(workspace_ref="workspace:2", workspace_title="O",
           surface_ref="surface:200", title="peer")
    registry.register("peer", "surface:200",
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("peer", "hi", my_name=None,
                    fallback_self_name="bootstrap_pick",
                    rerun_argv=[])
    assert out["ok"]
    me = registry.get_self(MY_SURFACE)
    assert me["name"] == "bootstrap_pick"


def test_bad_my_name_format(tmp_registry, fc):
    fc.add(workspace_ref="workspace:2", workspace_title="O",
           surface_ref="surface:200", title="peer")
    registry.register("peer", "surface:200",
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("peer", "hi", my_name="Bad-Name",
                    fallback_self_name=None, rerun_argv=[])
    assert out["ok"] is False
    assert out["code"] == "bad_name_format"


def test_peer_unknown_writes_payload_and_returns_handoff(
        tmp_registry, fc):
    _seed_self(tmp_registry)
    # No peer matching by name or tab.
    out = send.send("missing_peer", "boot me up", my_name=None,
                    fallback_self_name=None, rerun_argv=["rerun"])
    assert out["ok"] is False
    assert out["code"] == "peer_unknown"
    assert out["handoff_skill"] == "tfork"
    payload = out["payload_file"]
    assert os.path.exists(payload)
    st = os.stat(payload)
    assert oct(st.st_mode)[-3:] == "600"
    body = open(payload).read()
    assert "[p2p-bootstrap]" in body
    assert "suggested_name=missing_peer" in body
    assert "First message from me: boot me up" in body
    os.unlink(payload)


def test_empty_message(tmp_registry, fc):
    _seed_self(tmp_registry)
    out = send.send("anyone", "   \n  ", my_name=None,
                    fallback_self_name=None, rerun_argv=[])
    assert out["ok"] is False
    assert out["code"] == "empty_message"


def test_workspace_flag_is_passed_through(tmp_registry, fc):
    """Regression: every send must carry the destination workspace_ref
    into transport — the missing-workspace bug is exactly what the
    refactor exists to fix."""
    _seed_self(tmp_registry)
    fc.add(workspace_ref="workspace:99", workspace_title="Far",
           surface_ref="surface:999", title="far_peer")
    registry.register("far_peer", "surface:999",
                      live_set={MY_SURFACE, "surface:999"})
    send.send("far_peer", "hi", my_name=None,
              fallback_self_name=None, rerun_argv=[])
    surf, ws, _ = fc.sent[0]
    assert surf == "surface:999"
    assert ws == "workspace:99"


def test_explicit_peer_surface_skips_resolution_and_sends_plain(
        tmp_registry, fc):
    """Inline-bootstrap reply path: caller passes --peer-surface directly,
    so we skip name/tab resolution and route. No re-bootstrap — the peer
    already initiated contact."""
    _seed_self(tmp_registry)
    fc.add(workspace_ref="workspace:7", workspace_title="Inbound",
           surface_ref="surface:777", title="whatever")
    out = send.send("inbound_peer", "thanks for the ping",
                    my_name=None, fallback_self_name=None,
                    rerun_argv=[], peer_surface="surface:777")
    assert out["ok"]
    assert out["kind"] == "message"
    assert out["resolved_by"] == "explicit_surface"
    assert out["surface"] == "surface:777"
    surf, ws, text = fc.sent[0]
    assert surf == "surface:777"
    assert ws == "workspace:7"
    assert text == "[from: me] thanks for the ping"
    assert "[p2p-bootstrap]" not in text


def test_explicit_peer_surface_unknown_falls_back_to_spawn(
        tmp_registry, fc):
    """If the supplied surface is no longer in the cmux tree, fall back to
    the standard spawn handoff so the caller can invoke tfork."""
    _seed_self(tmp_registry)
    out = send.send("ghost_peer", "hi", my_name=None,
                    fallback_self_name=None, rerun_argv=["rerun"],
                    peer_surface="surface:404")
    assert out["ok"] is False
    assert out["code"] == "peer_unknown"
    assert out["handoff_skill"] == "tfork"
    payload = out["payload_file"]
    assert os.path.exists(payload)
    body = open(payload).read()
    assert "suggested_name=ghost_peer" in body
    os.unlink(payload)


def test_explicit_peer_surface_with_stale_manifest_still_plain(
        tmp_registry, fc):
    """Explicit surface skips the stale-triggers-bootstrap branch — the
    inbound bootstrap already established the channel."""
    _seed_self(tmp_registry)
    fc.add(workspace_ref="workspace:8", workspace_title="Old",
           surface_ref="surface:800", title="t")
    old = int(time.time()) - registry.TTL_SECONDS - 60
    p = registry.manifest_path("surface:800")
    p.write_text(json.dumps({
        "name": "stale_one", "surface_ref": "surface:800",
        "started_at": old, "last_seen": old,
    }))
    out = send.send("whatever_alias", "yo", my_name=None,
                    fallback_self_name=None, rerun_argv=[],
                    peer_surface="surface:800")
    assert out["ok"]
    assert out["kind"] == "message"
    assert out["canonical_name"] == "stale_one"
    assert out["peer_status"] == "stale"
    text = fc.sent[0][2]
    assert text == "[from: me] yo"


def test_bootstrap_suggested_name_takes_precedence_over_fallback(
        tmp_registry, fc):
    """Registration order: --my-name > --bootstrap-suggested-name >
    scrollback fallback. With no --my-name, the inline suggested_name
    should win over the scrollback-derived fallback."""
    fc.add(workspace_ref="workspace:2", workspace_title="O",
           surface_ref="surface:200", title="peer")
    registry.register("peer", "surface:200",
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("peer", "hi", my_name=None,
                    fallback_self_name="from_scrollback",
                    rerun_argv=[],
                    bootstrap_suggested_name="from_bootstrap")
    assert out["ok"]
    me = registry.get_self(MY_SURFACE)
    assert me["name"] == "from_bootstrap"


def test_my_name_beats_bootstrap_suggested_name(tmp_registry, fc):
    fc.add(workspace_ref="workspace:2", workspace_title="O",
           surface_ref="surface:200", title="peer")
    registry.register("peer", "surface:200",
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("peer", "hi", my_name="explicit_name",
                    fallback_self_name="from_scrollback",
                    rerun_argv=[],
                    bootstrap_suggested_name="from_bootstrap")
    assert out["ok"]
    me = registry.get_self(MY_SURFACE)
    assert me["name"] == "explicit_name"


def test_slash_command_skips_prefix(tmp_registry, fc):
    _seed_self(tmp_registry)
    fc.add(workspace_ref="workspace:2", workspace_title="O",
           surface_ref="surface:200", title="x")
    registry.register("cmdpeer", "surface:200",
                      live_set={MY_SURFACE, "surface:200"})
    send.send("cmdpeer", "/help", my_name=None,
              fallback_self_name=None, rerun_argv=[])
    text = fc.sent[0][2]
    assert text == "/help"
    assert not text.startswith("[from:")
