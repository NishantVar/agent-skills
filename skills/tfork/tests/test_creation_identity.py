"""Creation UUID provenance through real orchestration; native transport is scripted."""
import json
import subprocess
from uuid import UUID

from tforklib.orchestrate import run_fork
from tforklib.terminal import CmuxTerminal
from tforklib.verify import Observation


def uid(n):
    return str(UUID(int=n))


def launch(monkeypatch, tmp_path, *, payload=None, fail=None, placement=None, split_payload=None):
    payload = dict(window_id=uid(1), window_ref='window:1', workspace_id=uid(3),
                   workspace_ref='workspace:3', surface_id=uid(7), surface_ref='surface:7') if payload is None else payload
    terminal = CmuxTerminal()
    calls = []
    monkeypatch.setattr('tforklib.terminal.Path.home', lambda: tmp_path)
    monkeypatch.setattr('tforklib.terminal.time.sleep', lambda _: None)
    # Ref/title reuse after creation must never replace event identities.
    replacement = {'windows': [dict(id=uid(101), ref='window:1', workspaces=[
        dict(id=uid(103), ref='workspace:3', title='feature', panes=[{'surfaces': [
            dict(id=uid(107), ref='surface:7')]}])])]}
    monkeypatch.setattr('tforklib.terminal._cmux_tree', lambda: replacement)
    terminal._list_workspaces = lambda: [('workspace:3', 'feature')]
    terminal._window_node = lambda _: dict(id=uid(1), ref='window:1')
    def run(argv, **kwargs):
        calls.append(argv)
        if ('workspace' in argv and 'create' in argv) or 'new-workspace' in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload), '')
        if 'new-split' in argv or 'new-pane' in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps(split_payload if split_payload is not None else {**payload,
                'surface_id': uid(8), 'surface_ref': 'surface:8'}), '')
        if fail and fail in argv:
            return subprocess.CompletedProcess(argv, 1, '', 'injected failure')
        return subprocess.CompletedProcess(argv, 0, '{}', '')
    monkeypatch.setattr('tforklib.terminal._run', run)
    monkeypatch.setattr('tforklib.orchestrate.observe_fork', lambda *_: Observation(
        start_sentinel_seen=True, end_sentinel_seen=False, exit_status=None,
        foreground='agent', pane_text='', readable=True))
    monkeypatch.setattr('tforklib.orchestrate.read_registry', lambda *_: {})
    monkeypatch.setattr('tforklib.orchestrate.write_registry_entry', lambda *_: None)
    try:
        result = run_fork(['agent'], window='window:1', workspace='feature',
            workspace_mode='create', terminal=terminal, cwd=str(tmp_path), placement=placement)
    except Exception as exc:
        if not hasattr(exc, 'handoff'):
            raise
        result = exc.handoff()
    return result, calls


def test_result_preserves_creation_event_ids_despite_later_ref_reuse(monkeypatch, tmp_path):
    result, calls = launch(monkeypatch, tmp_path)
    assert result['ok'], result
    assert result['workspace']['id'] == uid(3)
    assert result['window']['id'] == uid(1)
    assert result['surface_id'] == uid(7)
    assert result['session'] == 'surface:7'
    assert result['workspace']['created'] is True
    assert result['launch_outcome']['version'] == 1
    assert result['launch_outcome']['state'] == 'started'
    paste = next(a for a in calls if 'paste-buffer' in a)
    assert paste[paste.index('--surface') + 1] == uid(7)
    assert paste[paste.index('--workspace') + 1] == uid(3)


def test_actual_split_surface_comes_from_split_response(monkeypatch, tmp_path):
    result, calls = launch(monkeypatch, tmp_path, placement='right')
    assert result['surface_id'] == uid(8)
    assert result['session'] == 'surface:8'
    assert result['workspace']['id'] == uid(3)
    pane = next(a for a in calls if 'new-pane' in a)
    assert pane[pane.index('--workspace') + 1] == uid(3)


def test_partial_creation_response_is_not_completed_from_later_tree(monkeypatch, tmp_path):
    payload = dict(workspace_id=uid(3), workspace_ref='workspace:3', surface_ref='surface:7')
    result, _ = launch(monkeypatch, tmp_path, payload=payload)
    assert result['ok'], result
    assert result['workspace']['id'] == uid(3)
    assert 'id' not in result['window']
    assert 'surface_id' not in result


def test_ambiguous_delivery_failure_keeps_original_creation_binding(monkeypatch, tmp_path):
    result, _ = launch(monkeypatch, tmp_path, fail='send-key')
    assert result['ok'] is False
    assert result['launch_outcome']['state'] == 'unknown'
    assert result['workspace']['id'] == uid(3)
    assert result['window']['id'] == uid(1)
    assert result['surface_id'] == uid(7)


def test_seeded_workspace_identity_is_anchored_to_new_window_uuid(monkeypatch, tmp_path):
    terminal = CmuxTerminal()
    terminal._new_window = lambda: uid(1)
    seen = []
    def window(value):
        seen.append(value)
        return dict(id=uid(1), ref='window:1', workspaces=[dict(id=uid(3), ref='workspace:3',
            title='feature', panes=[{'surfaces': [dict(id=uid(7), ref='surface:7')]}])])
    terminal._window_node = window
    terminal._wait_ready = lambda _: None
    terminal._spawn = lambda *_: None
    monkeypatch.setattr('tforklib.orchestrate.observe_fork', lambda *_: Observation(
        start_sentinel_seen=True, end_sentinel_seen=False, exit_status=None,
        foreground='agent', pane_text='', readable=True))
    monkeypatch.setattr('tforklib.orchestrate.read_registry', lambda *_: {})
    monkeypatch.setattr('tforklib.orchestrate.write_registry_entry', lambda *_: None)
    result = run_fork(['agent'], window='new', terminal=terminal, cwd=str(tmp_path))
    assert seen == [uid(1)]
    assert result['workspace']['id'] == uid(3)
    assert result['window']['id'] == uid(1)
    assert result['surface_id'] == uid(7)


def test_reused_workspace_does_not_publish_created_identity(monkeypatch, tmp_path):
    from fake_terminal import FakeTerminal, make_scrollback
    terminal = FakeTerminal(process='zsh', text=make_scrollback('nonce', exit_status=0),
        window_resolver=lambda *_: (dict(ref='window:1', created=False, id=uid(1)),
            dict(ref='workspace:3', title='feature', created=False, id=uid(3))))
    result = run_fork(['echo'], window='window:1', workspace='feature', terminal=terminal,
        cwd=str(tmp_path), registry_path=tmp_path/'registry', nonce='nonce')
    assert 'id' not in result['workspace']
    assert 'id' not in result['window']
    assert 'surface_id' not in result


def test_new_window_failure_preserves_only_captured_window_uuid(tmp_path):
    terminal = CmuxTerminal()
    terminal._new_window = lambda: uid(1)
    terminal._window_node = lambda _: None
    from tforklib.errors import ForkError
    import pytest
    with pytest.raises(ForkError) as raised:
        run_fork(['agent'], window='new', terminal=terminal, cwd=str(tmp_path))
    result = raised.value.handoff()
    assert result['window']['id'] == uid(1)
    assert 'workspace' not in result
    assert 'surface_id' not in result


def test_missing_split_identity_does_not_reuse_seed_surface_id(monkeypatch, tmp_path):
    # Missing creation-time surface ID stays partial even though a later tree has it.
    payload = dict(window_id=uid(1), window_ref='window:1', workspace_id=uid(3),
                   workspace_ref='workspace:3', surface_ref='surface:7')
    result, _ = launch(monkeypatch, tmp_path, payload=payload)
    assert result['workspace']['id'] == uid(3)
    assert result['window']['id'] == uid(1)
    assert 'surface_id' not in result


def test_split_without_uuid_cannot_borrow_the_seed_uuid(monkeypatch, tmp_path):
    split = dict(window_id=uid(1), workspace_id=uid(3), surface_ref='surface:8')
    result, _ = launch(monkeypatch, tmp_path, placement='right', split_payload=split)
    assert result['workspace']['id'] == uid(3)
    assert result['window']['id'] == uid(1)
    assert result['session'] == 'surface:8'
    assert 'surface_id' not in result


def test_paste_failure_retains_identity_and_closes_only_created_uuid(monkeypatch, tmp_path):
    result, calls = launch(monkeypatch, tmp_path, fail='paste-buffer')
    assert result['launch_outcome']['state'] == 'prework_failure'
    assert result['launch_outcome']['evidence_code'] == 'command_delivery_absent'
    assert result['workspace']['id'] == uid(3)
    assert result['window']['id'] == uid(1)
    assert result['surface_id'] == uid(7)
    assert not any('send-key' in a for a in calls)
    close = next(a for a in calls if 'close-workspace' in a)
    assert close[close.index('--workspace') + 1] == uid(3)


def test_unconfirmed_seed_keeps_window_uuid_without_claiming_workspace_identity():
    terminal = CmuxTerminal()
    terminal._new_window = lambda: uid(1)
    terminal._window_node = lambda _: dict(ref='window:1', workspaces=[
        dict(id=uid(103), ref='workspace:3', title='feature')])
    window, workspace = terminal.resolve_window('new', None, '/repo')
    # Even an incomplete seed observation must not discard the UUID returned by creation.
    facts = terminal.creation_identity(workspace['ref'])
    assert facts == {'window_id': uid(1)}
