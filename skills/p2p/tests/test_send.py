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


def _seed_self(tmp_registry, title="me", ws=MY_WS):
    p = registry.manifest_path(MY_SURFACE)
    p.write_text(json.dumps({
        "title": title, "surface_ref": MY_SURFACE,
        "workspace_ref": ws,
        "started_at": 1, "last_seen": int(time.time()),
    }))


@pytest.fixture
def fc(monkeypatch):
    fc = FakeCmux()
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref=MY_SURFACE, title="me")
    fc.apply(monkeypatch, my_surface_ref=MY_SURFACE)
    return fc


def test_live_peer_in_workspace_sends_plain_message(tmp_registry, fc):
    _seed_self(tmp_registry)
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="peer_a")
    registry.register("peer_a", "surface:200", MY_WS,
                      live_set={MY_SURFACE, "surface:200"})

    out = send.send("peer_a", "hello there", my_title=None,
                    fallback_self_title=None, rerun_argv=[])
    assert out["ok"]
    assert out["kind"] == "message"
    assert out["resolved_by"] == "title_in_workspace"
    assert out["title"] == "peer_a"
    assert out["surface"] == "surface:200"
    surf, ws, text = fc.sent[0]
    assert surf == "surface:200"
    assert ws == MY_WS
    assert text == "[from: me] hello there"


def test_live_first_contact_sends_bootstrap(tmp_registry, fc):
    """Tab exists in workspace, no manifest — bootstrap with suggested
    title = the title the caller addressed (which equals the tab title)."""
    _seed_self(tmp_registry)
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="claude_new")
    out = send.send("claude_new", "hi", my_title=None,
                    fallback_self_title=None, rerun_argv=[])
    assert out["ok"]
    assert out["kind"] == "bootstrap"
    text = fc.sent[0][2]
    assert "[p2p-bootstrap]" in text
    assert "suggested_title=claude_new" in text
    assert "First message from me: hi" in text


def test_stale_peer_bootstraps_with_manifest_title(tmp_registry, fc):
    """Stale manifest: re-bootstrap using the manifest's title as the
    suggested title."""
    _seed_self(tmp_registry)
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="stalewalker")
    old = int(time.time()) - registry.TTL_SECONDS - 60
    p = registry.manifest_path("surface:200")
    p.write_text(json.dumps({
        "title": "stalewalker", "surface_ref": "surface:200",
        "workspace_ref": MY_WS,
        "started_at": old, "last_seen": old,
    }))
    out = send.send("stalewalker", "wake up", my_title=None,
                    fallback_self_title=None, rerun_argv=[])
    assert out["ok"]
    assert out["kind"] == "bootstrap"
    assert out["peer_status"] == "stale"
    assert out["title"] == "stalewalker"
    text = fc.sent[0][2]
    assert "suggested_title=stalewalker" in text


def test_cross_workspace_returns_ambiguous_under_default_scope(
        tmp_registry, fc):
    """Default scope is caller's workspace. A live tab in another
    workspace with the addressed title returns ambiguous so the caller
    can opt out via --workspace."""
    _seed_self(tmp_registry)
    fc.add(workspace_ref="workspace:2", workspace_title="Other",
           surface_ref="surface:200", title="reviewer")
    rerun = ["agent_msg.py", "send", "--peer", "reviewer",
             "--message-file", "/tmp/x"]
    out = send.send("reviewer", "x", my_title=None,
                    fallback_self_title=None, rerun_argv=rerun)
    assert out["ok"] is False
    assert out["code"] == "peer_ambiguous"
    refs = {c["ref"] for c in out["candidates"]}
    assert refs == {"surface:200"}
    assert fc.sent == []
    # Bug A: single-candidate-elsewhere gets the "not in your workspace"
    # wording rather than "matches more than one".
    assert "not in your workspace" in out["human_message"]
    assert MY_WS in out["human_message"]
    assert "matches more than one" not in out["human_message"]
    # Bug B: envelope must reflect that this is a mechanical retry.
    assert out["action_required"] == "pick_candidate"
    assert out["retryable"] is True
    assert out["rerun_argv"] == rerun


def test_ambiguous_multi_candidate_keeps_generic_wording(
        tmp_registry, fc):
    """When the title matches in two different workspaces under global
    scope, the existing 'matches more than one' wording stays."""
    _seed_self(tmp_registry)
    fc.add(workspace_ref="workspace:2", workspace_title="A",
           surface_ref="surface:200", title="dup")
    fc.add(workspace_ref="workspace:3", workspace_title="B",
           surface_ref="surface:300", title="dup")
    out = send.send("dup", "x", my_title=None,
                    fallback_self_title=None, rerun_argv=[],
                    scope_workspace_ref="workspace:99")  # title is nowhere in scope:99
    assert out["ok"] is False
    assert out["code"] == "peer_ambiguous"
    assert "matches more than one" in out["human_message"]
    assert "not in your workspace" not in out["human_message"]
    # Envelope shape unchanged across both branches.
    assert out["action_required"] == "pick_candidate"
    assert out["retryable"] is True


def test_unregistered_with_generic_tab_returns_info_needed(
        tmp_registry, fc):
    """No --my-title, current tab title is generic ('claude'), no
    bootstrap-suggested. info_needed targets the calling agent."""
    # Rename the self surface to a generic title.
    fc.surfaces[0].title = "claude"
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="peer")
    registry.register("peer", "surface:200", MY_WS,
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("peer", "hi", my_title=None,
                    fallback_self_title=None, rerun_argv=["x"])
    assert out["ok"] is False
    assert out["code"] == "info_needed"
    assert "self_title" in out["missing"]
    assert out["action_required"] == "pick_self_title"
    # Self should NOT have been registered.
    assert registry.get_self(MY_SURFACE) is None


def test_unregistered_with_meaningful_tab_adopts_current_title(
        tmp_registry, fc):
    """No --my-title, no bootstrap, but the current cmux tab title is
    meaningful (not in GENERIC_TITLES). Adopt it as the wire identity."""
    # fc.surfaces[0].title is already "me" — meaningful.
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="peer")
    registry.register("peer", "surface:200", MY_WS,
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("peer", "hi", my_title=None,
                    fallback_self_title=None, rerun_argv=[])
    assert out["ok"]
    me = registry.get_self(MY_SURFACE)
    assert me["title"] == "me"
    text = fc.sent[0][2]
    assert text.startswith("[from: me]")


def test_unregistered_autoregisters_with_my_title(tmp_registry, fc):
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="peer")
    registry.register("peer", "surface:200", MY_WS,
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("peer", "hi", my_title="brand_new",
                    fallback_self_title=None, rerun_argv=[])
    assert out["ok"]
    me = registry.get_self(MY_SURFACE)
    assert me["title"] == "brand_new"


def test_unregistered_uses_fallback_self_title(tmp_registry, fc):
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="peer")
    registry.register("peer", "surface:200", MY_WS,
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("peer", "hi", my_title=None,
                    fallback_self_title="bootstrap_pick",
                    rerun_argv=[])
    assert out["ok"]
    me = registry.get_self(MY_SURFACE)
    assert me["title"] == "bootstrap_pick"


def test_bootstrap_suggested_title_beats_fallback(tmp_registry, fc):
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="peer")
    registry.register("peer", "surface:200", MY_WS,
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("peer", "hi", my_title=None,
                    fallback_self_title="from_scrollback",
                    rerun_argv=[],
                    bootstrap_suggested_title="from_bootstrap")
    assert out["ok"]
    me = registry.get_self(MY_SURFACE)
    assert me["title"] == "from_bootstrap"


def test_my_title_beats_bootstrap_suggested(tmp_registry, fc):
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="peer")
    registry.register("peer", "surface:200", MY_WS,
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("peer", "hi", my_title="explicit_title",
                    fallback_self_title="from_scrollback",
                    rerun_argv=[],
                    bootstrap_suggested_title="from_bootstrap")
    assert out["ok"]
    me = registry.get_self(MY_SURFACE)
    assert me["title"] == "explicit_title"


def test_my_title_collision_blocks_registration(tmp_registry, fc):
    """--my-title that's already held by another live agent in the same
    workspace returns title_collision; self is not registered."""
    # The holder's tab title must match its manifest title — otherwise
    # the sweep reaps it as a renamed-outside-of-p2p manifest.
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="taken")
    registry.register("taken", "surface:200", MY_WS,
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("anything", "x", my_title="taken",
                    fallback_self_title=None, rerun_argv=[])
    assert out["ok"] is False
    assert out["code"] == "title_collision"
    assert out["holder_surface"] == "surface:200"
    assert registry.get_self(MY_SURFACE) is None


def test_peer_unknown_writes_payload_and_returns_handoff(
        tmp_registry, fc):
    _seed_self(tmp_registry)
    out = send.send("missing_peer", "boot me up", my_title=None,
                    fallback_self_title=None, rerun_argv=["rerun"])
    assert out["ok"] is False
    assert out["code"] == "peer_unknown"
    assert out["handoff_skill"] == "tfork"
    payload = out["payload_file"]
    assert os.path.exists(payload)
    st = os.stat(payload)
    assert oct(st.st_mode)[-3:] == "600"
    body = open(payload).read()
    assert "[p2p-bootstrap]" in body
    assert "suggested_title=missing_peer" in body
    assert "First message from me: boot me up" in body
    os.unlink(payload)


def test_empty_message(tmp_registry, fc):
    _seed_self(tmp_registry)
    out = send.send("anyone", "   \n  ", my_title=None,
                    fallback_self_title=None, rerun_argv=[])
    assert out["ok"] is False
    assert out["code"] == "empty_message"


def test_destination_workspace_is_carried_to_transport(tmp_registry, fc):
    """Regression: every send must carry the destination workspace_ref
    into transport."""
    _seed_self(tmp_registry)
    fc.add(workspace_ref="workspace:99", workspace_title="Far",
           surface_ref="surface:999", title="far_peer")
    # Use explicit cross-workspace scope so resolution doesn't bail.
    send.send("far_peer", "hi", my_title=None,
              fallback_self_title=None, rerun_argv=[],
              scope_workspace_ref="workspace:99")
    surf, ws, _ = fc.sent[0]
    assert surf == "surface:999"
    assert ws == "workspace:99"


def test_explicit_peer_surface_skips_resolution(tmp_registry, fc):
    _seed_self(tmp_registry)
    fc.add(workspace_ref="workspace:7", workspace_title="Inbound",
           surface_ref="surface:777", title="whatever")
    out = send.send("inbound_peer", "thanks for the ping",
                    my_title=None, fallback_self_title=None,
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
    _seed_self(tmp_registry)
    out = send.send("ghost_peer", "hi", my_title=None,
                    fallback_self_title=None, rerun_argv=["rerun"],
                    peer_surface="surface:404")
    assert out["ok"] is False
    assert out["code"] == "peer_unknown"
    assert out["handoff_skill"] == "tfork"
    payload = out["payload_file"]
    assert os.path.exists(payload)
    body = open(payload).read()
    assert "suggested_title=ghost_peer" in body
    os.unlink(payload)


def test_explicit_peer_surface_with_stale_manifest_still_plain(
        tmp_registry, fc):
    """Explicit surface skips the stale-triggers-bootstrap branch — the
    inbound bootstrap already established the channel."""
    _seed_self(tmp_registry)
    fc.add(workspace_ref="workspace:8", workspace_title="Old",
           surface_ref="surface:800", title="stale_one")
    old = int(time.time()) - registry.TTL_SECONDS - 60
    p = registry.manifest_path("surface:800")
    p.write_text(json.dumps({
        "title": "stale_one", "surface_ref": "surface:800",
        "workspace_ref": "workspace:8",
        "started_at": old, "last_seen": old,
    }))
    out = send.send("stale_one", "yo", my_title=None,
                    fallback_self_title=None, rerun_argv=[],
                    peer_surface="surface:800")
    assert out["ok"]
    assert out["kind"] == "message"
    assert out["title"] == "stale_one"
    assert out["peer_status"] == "stale"
    text = fc.sent[0][2]
    assert text == "[from: me] yo"


def test_one_way_to_live_peer_marks_frame(tmp_registry, fc):
    _seed_self(tmp_registry)
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="peer_a")
    registry.register("peer_a", "surface:200", MY_WS,
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("peer_a", "fyi only", my_title=None,
                    fallback_self_title=None, rerun_argv=[],
                    one_way=True)
    assert out["ok"]
    assert out["one_way"] is True
    assert out["kind"] == "message"
    text = fc.sent[0][2]
    assert text == "[from: me | one-way] fyi only"


def test_one_way_first_contact_bootstrap_omits_reply_request(
        tmp_registry, fc):
    _seed_self(tmp_registry)
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="new_tab")
    out = send.send("new_tab", "status update", my_title=None,
                    fallback_self_title=None, rerun_argv=[],
                    one_way=True)
    assert out["ok"]
    assert out["one_way"] is True
    assert out["kind"] == "bootstrap"
    text = fc.sent[0][2]
    assert "[p2p-bootstrap]" in text
    assert "reply when ready" not in text
    assert "and reply" not in text
    assert "no reply is expected" in text
    assert ("First message from me (one-way, no reply expected): "
            "status update") in text


def test_default_send_keeps_reply_trailer_and_plain_frame(
        tmp_registry, fc):
    _seed_self(tmp_registry)
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="another_tab")
    out = send.send("another_tab", "hi", my_title=None,
                    fallback_self_title=None, rerun_argv=[])
    assert out["ok"]
    assert out["one_way"] is False
    text = fc.sent[0][2]
    assert "reply when ready" in text
    assert "one-way" not in text


def test_one_way_explicit_peer_surface_marks_frame(tmp_registry, fc):
    _seed_self(tmp_registry)
    fc.add(workspace_ref="workspace:7", workspace_title="Inbound",
           surface_ref="surface:777", title="whatever")
    out = send.send("inbound_peer", "ack-free note", my_title=None,
                    fallback_self_title=None, rerun_argv=[],
                    peer_surface="surface:777", one_way=True)
    assert out["ok"]
    assert out["one_way"] is True
    text = fc.sent[0][2]
    assert text == "[from: me | one-way] ack-free note"


def test_slash_command_skips_prefix(tmp_registry, fc):
    _seed_self(tmp_registry)
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="cmdpeer")
    registry.register("cmdpeer", "surface:200", MY_WS,
                      live_set={MY_SURFACE, "surface:200"})
    send.send("cmdpeer", "/help", my_title=None,
              fallback_self_title=None, rerun_argv=[])
    text = fc.sent[0][2]
    assert text == "/help"
    assert not text.startswith("[from:")


def test_legacy_name_manifest_routes_under_promoted_title(
        tmp_registry, fc):
    """A manifest written by the old code (with `name` not `title`) is
    promoted on read and routes under that name as the title."""
    _seed_self(tmp_registry)
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="legacy_peer")
    p = registry.manifest_path("surface:200")
    p.write_text(json.dumps({
        "name": "legacy_peer", "surface_ref": "surface:200",
        "workspace_ref": MY_WS,
        "started_at": 1, "last_seen": int(time.time()),
    }))
    out = send.send("legacy_peer", "hi", my_title=None,
                    fallback_self_title=None, rerun_argv=[])
    assert out["ok"]
    assert out["kind"] == "message"
    assert out["title"] == "legacy_peer"
