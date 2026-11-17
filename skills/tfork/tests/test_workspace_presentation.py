"""Native apply through actual orchestration, including cross-repository ownership."""
import copy
import json
from pathlib import Path

from fake_terminal import FakeTerminal
from test_native_group_presentation import Native, WINDOW, WORKSPACE, uid
from tforklib.orchestrate import run_fork
from tforklib.verify import Observation


def launch(monkeypatch, tmp_path, native, *, created=True, owner='/repo/one', flags=True, identity=True):
    terminal = FakeTerminal(window_resolver=lambda *_: (
        dict(ref='window:1', created=False), dict(ref='workspace:3', title='feature', created=created)))
    terminal.creation_identity = lambda _: dict(workspace_id=WORKSPACE, window_id=WINDOW) if identity else {}
    monkeypatch.setattr('tforklib.presentation.CmuxRPC', lambda: native)
    monkeypatch.setattr('tforklib.orchestrate.observe_fork', lambda *_: Observation(
        start_sentinel_seen=True, end_sentinel_seen=False, exit_status=None,
        foreground='codex', pane_text='', readable=True))
    return run_fork(['codex'], workspace='feature', window='window:1', terminal=terminal,
        cwd=str(tmp_path), registry_path=tmp_path/'registry.json',
        **(dict(workspace_group='Flux', workspace_color='#aabbcc', workspace_group_owner=owner,
                workspace_group_ownership_dir=str(tmp_path/'ownership')) if flags else {}))


def test_apply_to_created_workspace(monkeypatch, tmp_path):
    native = Native()
    result = launch(monkeypatch, tmp_path, native)
    assert result['launch_outcome']['state'] == 'started'
    assert 'warnings' not in result
    assert native.groups[0]['member_workspace_ids'][-1] == WORKSPACE
    assert native.groups[0]['custom_color'] == native.workspaces[0]['custom_color'] == '#aabbcc'
    assert json.loads((tmp_path/'ownership'/f'{WINDOW}.json').read_text())['Flux']['repo_identity'] == '/repo/one'


def test_reuse_and_direct_fork_skip_native(monkeypatch, tmp_path):
    native = Native()
    launch(monkeypatch, tmp_path, native, created=False)
    launch(monkeypatch, tmp_path, native, flags=False)
    assert native.calls == []
    assert not (tmp_path/'ownership').exists()


def test_native_failure_warns_without_failing_started_launch(monkeypatch, tmp_path):
    native = Native()
    native.fail = 'workspace.group.set_color'
    result = launch(monkeypatch, tmp_path, native)
    assert result['ok'] and result['launch_outcome']['state'] == 'started'
    assert result['warnings'][0]['step'] == 'group_color'
    assert len(native.calls) > 0


def test_missing_creation_identity_warns_without_native_io(monkeypatch, tmp_path):
    native = Native()
    result = launch(monkeypatch, tmp_path, native, identity=False)
    assert result['launch_outcome']['state'] == 'started' and result['warnings']
    assert native.calls == []


def test_distinct_repositories_cannot_share_or_recolor_claimed_group(monkeypatch, tmp_path):
    native = Native(groups=[])
    first = launch(monkeypatch, tmp_path, native)
    assert not first.get('warnings')
    groups = copy.deepcopy(native.groups)
    mutations = native.mutations()
    second = launch(monkeypatch, tmp_path, native, owner='/repo/two')
    assert second['launch_outcome']['state'] == 'started'
    assert 'another repository' in second['warnings'][0]['message']
    assert native.groups == groups and native.mutations() == mutations


def test_prior_flux_ownership_file_is_honored(monkeypatch, tmp_path):
    native = Native()
    directory = tmp_path/'ownership'; directory.mkdir()
    (directory/f'{WINDOW}.json').write_text(json.dumps({'Flux': dict(
        repo_identity='/other/repo', group_id=native.groups[0]['id'])}))
    result = launch(monkeypatch, tmp_path, native)
    assert 'another repository' in result['warnings'][0]['message']
    assert native.mutations() == []


def test_ownership_symlink_warns_without_native_io(monkeypatch, tmp_path):
    real = tmp_path/'elsewhere'; real.mkdir()
    (tmp_path/'ownership').symlink_to(real)
    native = Native()
    result = launch(monkeypatch, tmp_path, native)
    assert result['warnings'] and native.calls == []
    assert list(real.iterdir()) == []
