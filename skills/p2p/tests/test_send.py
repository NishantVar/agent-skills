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
    assert text == "[from: me] hello there\n\nTo reply: Load p2p"


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


def test_idle_peer_sends_plain_message_no_rebootstrap(tmp_registry, fc):
    """An idle peer (manifest exists, very old last_seen) is fully
    reachable. Send a plain `[from: ...]` framed message, not a
    bootstrap. Liveness is grounded in cmux tree, not heartbeat age."""
    _seed_self(tmp_registry)
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="sleepy")
    old = int(time.time()) - 86400  # one day old
    p = registry.manifest_path("surface:200")
    p.write_text(json.dumps({
        "title": "sleepy", "surface_ref": "surface:200",
        "workspace_ref": MY_WS,
        "started_at": old, "last_seen": old,
    }))
    out = send.send("sleepy", "wake up", my_title=None,
                    fallback_self_title=None, rerun_argv=[])
    assert out["ok"]
    assert out["kind"] == "message"
    assert "peer_status" not in out
    assert out["title"] == "sleepy"
    text = fc.sent[0][2]
    assert text.startswith("[from: ")
    assert "[p2p-bootstrap]" not in text


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
    rerun = ["agent_msg.py", "send", "--peer", "peer",
             "--message-file", "/tmp/x"]
    out = send.send("peer", "hi", my_title=None,
                    fallback_self_title=None, rerun_argv=rerun)
    assert out["ok"] is False
    assert out["code"] == "info_needed"
    assert "self_title" in out["missing"]
    assert out["action_required"] == "pick_self_title"
    # Envelope: prose is a mechanical retry instruction.
    assert out["retryable"] is True
    assert out["rerun_argv"] == rerun
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
    rerun = ["agent_msg.py", "send", "--peer", "anything",
             "--my-title", "taken", "--message-file", "/tmp/x"]
    out = send.send("anything", "x", my_title="taken",
                    fallback_self_title=None, rerun_argv=rerun)
    assert out["ok"] is False
    assert out["code"] == "title_collision"
    assert out["holder_surface"] == "surface:200"
    assert registry.get_self(MY_SURFACE) is None
    # Envelope: prose tells the agent to pick a different title + rerun.
    assert out["action_required"] == "pick_self_title"
    assert out["retryable"] is True
    assert out["rerun_argv"] == rerun


def test_my_title_collision_does_not_rename_own_tab(tmp_registry, fc):
    """QA-C regression: title_collision must not leave the caller's
    cmux tab visibly renamed. Probe-before-rename means the tab keeps
    its prior title when the handoff fires."""
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="taken")
    registry.register("taken", "surface:200", MY_WS,
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("anything", "x", my_title="taken",
                    fallback_self_title=None, rerun_argv=[])
    assert out["code"] == "title_collision"
    # Caller's tab title must still be its pre-call value, not the
    # colliding `taken`. The fc fixture seeds my_surface with title="me".
    my_tab = next(s for s in fc.surfaces if s.surface_ref == MY_SURFACE)
    assert my_tab.title == "me"


def test_my_title_collision_rolls_back_rename_on_toctou(
        tmp_registry, fc, monkeypatch):
    """QA-C TOCTOU regression: would_collide() can return None and
    register() can still return title_collision (another agent claimed
    the title between probe and register). When that happens, the
    rename must be rolled back so the caller's tab doesn't end up
    visibly renamed."""
    # Force the TOCTOU scenario by mocking would_collide() to lie.
    monkeypatch.setattr(registry, "would_collide",
                        lambda *a, **kw: None)
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="taken")
    registry.register("taken", "surface:200", MY_WS,
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("anything", "x", my_title="taken",
                    fallback_self_title=None, rerun_argv=[])
    assert out["code"] == "title_collision"
    # Tab must be rolled back to its pre-call title, not left as `taken`.
    my_tab = next(s for s in fc.surfaces if s.surface_ref == MY_SURFACE)
    assert my_tab.title == "me"


def test_my_title_no_collision_renames_and_registers(tmp_registry, fc):
    """Sanity for the happy path: non-colliding --my-title on first
    registration still renames the tab AND writes the manifest."""
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="peer_a")
    registry.register("peer_a", "surface:200", MY_WS,
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("peer_a", "hi", my_title="qa_lead",
                    fallback_self_title=None, rerun_argv=[])
    assert out["ok"]
    my_tab = next(s for s in fc.surfaces if s.surface_ref == MY_SURFACE)
    assert my_tab.title == "qa_lead"
    me = registry.get_self(MY_SURFACE)
    assert me["title"] == "qa_lead"


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
    rerun = ["agent_msg.py", "send", "--peer", "anyone",
             "--message-file", "/tmp/x"]
    out = send.send("anyone", "   \n  ", my_title=None,
                    fallback_self_title=None, rerun_argv=rerun)
    assert out["ok"] is False
    assert out["code"] == "empty_message"
    # Envelope: prose tells the agent to rewrite + rerun, envelope
    # must reflect that mechanical retry.
    assert out["action_required"] == "rewrite_message"
    assert out["retryable"] is True
    assert out["rerun_argv"] == rerun


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
    assert text == "[from: me] thanks for the ping\n\nTo reply: Load p2p"
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


def test_explicit_peer_surface_with_idle_manifest_sends_plain(
        tmp_registry, fc):
    """Explicit surface routing sends a plain framed message
    regardless of manifest age — idle peers are still live."""
    _seed_self(tmp_registry)
    fc.add(workspace_ref="workspace:8", workspace_title="Old",
           surface_ref="surface:800", title="idle_one")
    old = int(time.time()) - 86400
    p = registry.manifest_path("surface:800")
    p.write_text(json.dumps({
        "title": "idle_one", "surface_ref": "surface:800",
        "workspace_ref": "workspace:8",
        "started_at": old, "last_seen": old,
    }))
    out = send.send("idle_one", "yo", my_title=None,
                    fallback_self_title=None, rerun_argv=[],
                    peer_surface="surface:800")
    assert out["ok"]
    assert out["kind"] == "message"
    assert out["title"] == "idle_one"
    assert "peer_status" not in out
    text = fc.sent[0][2]
    assert text == "[from: me] yo\n\nTo reply: Load p2p"


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


def test_peer_renamed_when_addressing_former_title(tmp_registry, fc):
    """A live tab in the caller's workspace was previously registered
    as 'reviewer' and has since been renamed to 'r1'. Addressing
    'reviewer' returns peer_renamed pointing at the current title and
    surface — no silent failure, no wrong route."""
    _seed_self(tmp_registry)
    # Peer surface is live, currently titled 'r1', but its manifest
    # carries former_titles=['reviewer'] from a prior cmux rename.
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="r1")
    p = registry.manifest_path("surface:200")
    p.write_text(json.dumps({
        "title": "r1", "former_titles": ["reviewer"],
        "surface_ref": "surface:200", "workspace_ref": MY_WS,
        "started_at": 1, "last_seen": int(time.time()),
    }))
    rerun = ["agent_msg.py", "send", "--peer", "reviewer",
             "--message-file", "/tmp/x"]
    out = send.send("reviewer", "hi", my_title=None,
                    fallback_self_title=None, rerun_argv=rerun)
    assert out["ok"] is False
    assert out["code"] == "peer_renamed"
    # No message goes out.
    assert fc.sent == []
    # Envelope shape parity with peer_ambiguous.
    assert out["action_required"] == "confirm_rename"
    assert out["retryable"] is True
    assert out["rerun_argv"] == rerun
    assert len(out["candidates"]) == 1
    c = out["candidates"][0]
    assert c["ref"] == "surface:200"
    assert c["current_title"] == "r1"
    assert c["former_title"] == "reviewer"
    # Human wording surfaces the new title clearly.
    assert "r1" in out["human_message"]
    assert "reviewer" in out["human_message"]


def test_peer_renamed_lazy_promotion_via_read_side_sweep(
        tmp_registry, fc):
    """Even when the renamed peer's manifest has NOT yet had its
    title/former_titles updated on disk (e.g., the peer never ran a
    register since the rename), the read-side sweep in `send` promotes
    the rename in place — so the very first peer addressing the prior
    title sees peer_renamed rather than peer_unknown."""
    _seed_self(tmp_registry)
    # Peer surface currently has title 'r1' per cmux, but the on-disk
    # manifest still says 'reviewer' (no former_titles yet).
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="r1")
    p = registry.manifest_path("surface:200")
    p.write_text(json.dumps({
        "title": "reviewer", "surface_ref": "surface:200",
        "workspace_ref": MY_WS,
        "started_at": 1, "last_seen": int(time.time()),
    }))
    out = send.send("reviewer", "hi", my_title=None,
                    fallback_self_title=None, rerun_argv=[])
    assert out["ok"] is False
    assert out["code"] == "peer_renamed"
    # The sweep promoted the rename onto disk.
    on_disk = json.loads(p.read_text())
    assert on_disk["title"] == "r1"
    assert on_disk["former_titles"] == ["reviewer"]


def test_live_current_match_wins_over_rename_in_send(
        tmp_registry, fc):
    """Edge case #3: peer addressing 'reviewer' must hit the live tab
    that currently holds that title, not a rename candidate."""
    _seed_self(tmp_registry)
    # Old surface, renamed away from 'reviewer' to 'r1'.
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="r1")
    p_old = registry.manifest_path("surface:200")
    p_old.write_text(json.dumps({
        "title": "r1", "former_titles": ["reviewer"],
        "surface_ref": "surface:200", "workspace_ref": MY_WS,
        "started_at": 1, "last_seen": int(time.time()),
    }))
    # New surface that took the 'reviewer' title.
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:300", title="reviewer")
    registry.register("reviewer", "surface:300", MY_WS,
                      live_set={MY_SURFACE, "surface:200", "surface:300"})
    out = send.send("reviewer", "hi", my_title=None,
                    fallback_self_title=None, rerun_argv=[])
    assert out["ok"]
    assert out["surface"] == "surface:300"
    assert out["title"] == "reviewer"


def test_self_externally_renamed_frames_with_current_cmux_title(
        tmp_registry, fc):
    """Regression (codex_reviewer dd89b32 finding 1): my manifest says
    title='me' but my cmux tab has been renamed externally to 'newme'.
    Without refreshing `me` from the post-sweep manifest set, framing
    would emit '[from: me]' while the manifest gets promoted to
    'newme' on the same call — peers seeing '[from: me]' would later
    get peer_renamed when they replied to 'me', which is the OPPOSITE
    of the bridge we want."""
    _seed_self(tmp_registry)  # writes manifest title='me'
    # Externally rename the cmux tab.
    fc.surfaces[0].title = "newme"
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="peer_a")
    registry.register("peer_a", "surface:200", MY_WS,
                      live_set={MY_SURFACE, "surface:200"})
    out = send.send("peer_a", "hello", my_title=None,
                    fallback_self_title=None, rerun_argv=[])
    assert out["ok"]
    text = fc.sent[0][2]
    assert text == "[from: newme] hello\n\nTo reply: Load p2p"
    # And the on-disk manifest reflects the rename promotion.
    me_on_disk = json.loads(registry.manifest_path(MY_SURFACE).read_text())
    assert me_on_disk["title"] == "newme"
    assert me_on_disk["former_titles"] == ["me"]


def test_in_scope_rename_wins_over_out_of_scope_current(
        tmp_registry, fc):
    """Regression (codex_reviewer dd89b32 finding 2): caller scoped to
    workspace A; title 'reviewer' is held currently by a tab in
    workspace B; A also has a live surface whose former_titles
    contains 'reviewer'. The in-scope rename match must win over the
    out-of-scope ambiguous bounce — caller's own workspace is more
    relevant."""
    _seed_self(tmp_registry)
    # Out-of-scope current-title match.
    fc.add(workspace_ref="workspace:99", workspace_title="Other",
           surface_ref="surface:999", title="reviewer")
    # In-scope renamed surface (former title 'reviewer').
    fc.add(workspace_ref=MY_WS, workspace_title="Self",
           surface_ref="surface:200", title="r1")
    p = registry.manifest_path("surface:200")
    p.write_text(json.dumps({
        "title": "r1", "former_titles": ["reviewer"],
        "surface_ref": "surface:200", "workspace_ref": MY_WS,
        "started_at": 1, "last_seen": int(time.time()),
    }))
    out = send.send("reviewer", "hi", my_title=None,
                    fallback_self_title=None, rerun_argv=[])
    assert out["ok"] is False
    assert out["code"] == "peer_renamed"
    # The candidate is the in-scope renamed surface, not the
    # out-of-scope current holder.
    assert len(out["candidates"]) == 1
    assert out["candidates"][0]["ref"] == "surface:200"
    assert out["candidates"][0]["workspace_ref"] == MY_WS
    assert out["candidates"][0]["current_title"] == "r1"
    assert fc.sent == []


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
