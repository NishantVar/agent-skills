"""Best-effort native cmux presentation of one verified new conductor workspace.

Public seam: apply_presentation takes resolved strings, verified workspace/window
UUIDs and an injectable ``rpc(method, params) -> dict``. No launch evidence file
or presentation retry is exposed by tfork. This
module neither resolves repositories nor launches/delivers agent commands.

RPC shapes follow cmux's advertised v2 methods. Tests establish scripted behavior;
they do not establish installed native mutation behavior or concurrent atomicity.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
from uuid import UUID


STEPS = ('select_group', 'position_group', 'append_workspace', 'restore_collapse', 'group_color', 'workspace_color')


class CmuxRPC:
    """Thin bounded CLI transport; all native IO is replaceable at this boundary."""
    def __init__(self, *, runner=subprocess.run, executable='cmux', timeout=10):
        self.runner, self.executable, self.timeout = runner, executable, timeout

    def __call__(self, method, params):
        result = self.runner([self.executable, 'rpc', method, json.dumps(params)],
                             capture_output=True, text=True, check=False, timeout=self.timeout)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f'cmux {method} exited {result.returncode}')
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise ValueError(f'cmux {method} returned a non-object')
        return value


def _uuid(value):
    return str(UUID(value))


def _same(a, b):
    return isinstance(a, str) and isinstance(b, str) and a.lower() == b.lower()


def _groups(value, window_id):
    if not _same(value.get('window_id'), window_id) or not isinstance(value.get('groups'), list):
        raise ValueError('Group topology does not identify the requested window')
    groups = value['groups']
    identities = set()
    for g in groups:
        identity = _uuid(g['id'])
        _uuid(g['anchor_workspace_id'])
        if identity in identities or not isinstance(g['name'], str):
            raise ValueError('Duplicate group identity or unreadable group name')
        identities.add(identity)
        if not isinstance(g.get('is_collapsed'), bool) or not isinstance(g.get('is_pinned'), bool):
            raise ValueError('Unreadable group collapse/pin state')
        if not isinstance(g.get('member_workspace_ids'), list):
            raise ValueError('Unreadable group membership')
        members = [_uuid(m) for m in g['member_workspace_ids']]
        if len(set(members)) != len(members) or _uuid(g['anchor_workspace_id']) not in members:
            raise ValueError('Inconsistent group anchor/membership')
    return groups


def apply_presentation(*, group_name, color, workspace_id, window_id, rpc=None, state=None,
                       claim_group=None):
    """Apply remaining presentation steps; return outcome, steps, warning and state.

    Caller supplies verified UUIDs, never titles or short refs as mutation targets.
    State is bound to these inputs. Successful steps stay intact on failure. Every
    retry reads topology, follows retained group/anchor UUIDs and leaves an existing
    member's position alone. Unknown create outcomes are reconciled before another
    create; ambiguity requires user correction rather than guessing a group.
    Optional claim_group(group_id or None) must persist/check repository ownership
    before mutation; the caller holds its shared lock throughout this call.
    """
    rpc = rpc or CmuxRPC()
    retained = copy.deepcopy(state) if isinstance(state, dict) else {}
    result = dict(outcome='success', state=retained, steps=[], warnings=[], diagnostic=None,
                  incomplete=list(STEPS), workspace_id=workspace_id, window_id=window_id,
                  group_id=None, group_name=group_name, color=color, observed_refs={})
    result['observed_refs'].update({key: retained[key] for key in
                                  ('window_ref', 'workspace_ref', 'group_ref', 'anchor_workspace_ref')
                                  if retained.get(key)})
    result['group_id'] = retained.get('group_id')
    step = 'inputs'

    def done(name, status='success'):
        result['steps'].append(dict(step=name, outcome=status))
        if name in result['incomplete']:
            result['incomplete'].remove(name)

    def call(method, params):
        if method not in methods:
            raise ValueError(f'Missing native capability: {method}; update cmux to a build advertising it')
        value = rpc(method, params)
        if not isinstance(value, dict) or value.get('ok') is False or 'error' in value:
            raise ValueError(f'Native {method} returned an invalid/error result: {value!r}')
        return value

    def remember(g):
        # Keep observed refs even if a later native-name validation fails.
        for key in ('id', 'ref', 'anchor_workspace_id', 'anchor_workspace_ref', 'name'):
            retained[{'id': 'group_id', 'ref': 'group_ref', 'name': 'native_group_name'}.get(key, key)] = g.get(key)
        result['group_id'] = retained['group_id']
        result['observed_refs'].update(group_ref=g.get('ref'), anchor_workspace_ref=g.get('anchor_workspace_ref'))

    def validate(g):
        _uuid(g['id'])
        _uuid(g['anchor_workspace_id'])
        if g.get('name') != group_name:
            raise ValueError('Native group name differs from the resolved normalized name')
        if _same(g['anchor_workspace_id'], workspace_id):
            raise ValueError('Conductor workspace is a group anchor; refusing to move or recolor it')

    try:
        workspace_id, window_id = _uuid(workspace_id), _uuid(window_id)
        if (not isinstance(group_name, str) or not group_name or group_name.strip() != group_name
                or not group_name.isprintable() or not isinstance(color, str)
                or not re.fullmatch(r'#[0-9a-f]{6}', color)):
            raise ValueError('Expected normalized nonblank printable group name and #rrggbb color')
        binding = dict(workspace_id=workspace_id, window_id=window_id, group_name=group_name, color=color)
        if retained and retained.get('inputs') != binding:
            raise ValueError('Retained presentation state belongs to different inputs')
        retained['inputs'] = binding
        step = 'capabilities'
        capabilities = rpc('system.capabilities', {})
        methods = capabilities.get('methods')
        if not isinstance(methods, list) or not all(isinstance(m, str) for m in methods):
            raise ValueError('Unreadable native capabilities')
        done(step)
        step = 'list_groups'
        topology = call('workspace.group.list', dict(window_id=window_id))
        groups = _groups(topology, window_id)
        result['observed_refs']['window_ref'] = topology.get('window_ref')
        retained['window_ref'] = topology.get('window_ref')
        done(step)
        step = 'workspace_identity'
        topology = call('workspace.list', dict(window_id=window_id))
        if not _same(topology.get('window_id'), window_id):
            raise ValueError('Workspace topology belongs to another window')
        workspaces = topology.get('workspaces')
        if not isinstance(workspaces, list):
            raise ValueError('Unreadable workspace topology')
        matches = [w for w in workspaces if _same(w.get('id'), workspace_id)]
        if len(matches) != 1:
            raise ValueError('Verified conductor workspace is absent or ambiguous in launch window')
        workspace = matches[0]
        if not isinstance(workspace.get('selected'), bool):
            raise ValueError('Unreadable conductor workspace selection state')
        retained['workspace_ref'] = workspace.get('ref')
        result['observed_refs']['workspace_ref'] = workspace.get('ref')
        if any(_same(g['anchor_workspace_id'], workspace_id) for g in groups):
            raise ValueError('Conductor workspace is an existing native anchor')
        done(step)
        step = 'select_group'
        matches = [g for g in groups if g['name'] == group_name]
        if len(matches) > 1:
            result['observed_refs']['matching_group_refs'] = [g.get('ref') for g in matches]
            raise ValueError('Multiple same-window groups match; rename duplicates before retrying')
        selected = None
        if retained.get('group_id'):
            known = [g for g in groups if _same(g['id'], retained['group_id'])]
            if known:
                selected = known[0]
                if not _same(selected['anchor_workspace_id'], retained.get('anchor_workspace_id')):
                    raise ValueError('Retained group anchor identity changed')
                validate(selected)
            elif matches:
                raise ValueError('Retained group disappeared; same-name replacement has a different identity')
            else:
                # Live absence allows creation of the missing group and fresh anchor.
                retained.pop('group_id', None)
                retained.pop('positioned', None)
        if selected is None and matches:
            selected = matches[0]
        if claim_group is not None:
            claim_group(selected['id'] if selected is not None else None)
        if selected is None:
            if retained.get('create_attempted'):
                new_groups = [g for g in groups if _uuid(g['id']) not in retained['before_create_ids']]
                if new_groups:
                    result['observed_refs']['unreconciled_group_refs'] = [g.get('ref') for g in new_groups]
                    raise ValueError('Uncertain creation left unrecognized groups; reconcile them before retrying')
            step = 'create_group'
            retained.update(create_attempted=True, before_create_ids=[_uuid(g['id']) for g in groups],
                            positioned=False, restore_collapse=False)
            response = call('workspace.group.create', dict(window_id=window_id, name=group_name,
                                                           child_workspace_ids=[]))
            selected = response.get('group')
            if not isinstance(selected, dict):
                raise ValueError('Native creation returned no group identity')
            remember(selected)
            validate(selected)
            if (_uuid(selected['id']) in retained['before_create_ids']
                    or any(_same(w.get('id'), selected['anchor_workspace_id']) for w in workspaces)):
                raise ValueError('Native creation returned a preexisting group or anchor identity')
            # Same native payload schema as list; reject missing membership/anchor.
            _groups(dict(window_id=window_id, groups=[selected]), window_id)
            if claim_group is not None:
                claim_group(selected['id'])
            done(step)
        else:
            validate(selected)
            remember(selected)
        done('select_group')
        params = dict(window_id=window_id, group_id=selected['id'])
        step = 'position_group'
        at_end = bool(groups) and _same(groups[-1]['id'], selected['id'])
        if retained.get('create_attempted') and not retained.get('positioned') and not at_end:
            # Creation appends the group array but can insert its anchor beside the
            # active workspace. Native move-to-end puts the new section at the end.
            response = call('workspace.group.move', dict(params, to_index=len(groups) -
                            (1 if any(_same(g['id'], selected['id']) for g in groups) else 0)))
            if not _same(response.get('group_id'), selected['id']):
                raise ValueError('Native group placement returned another identity')
            retained['positioned'] = True
            done(step)
        else:
            if retained.get('create_attempted'):
                retained['positioned'] = True
            done(step, 'already_complete')
        step = 'append_workspace'
        if any(_same(m, workspace_id) for m in selected['member_workspace_ids']):
            done(step, 'already_complete')
        else:
            retained['restore_collapse'] = retained.get('restore_collapse', False) or selected['is_collapsed']
            response = call('workspace.group.add', dict(params, workspace_id=workspace_id, placement='end'))
            if not (_same(response.get('group_id'), selected['id'])
                    and _same(response.get('workspace_id'), workspace_id)):
                raise ValueError('Native membership returned inconsistent identities')
            done(step)
            # Native add auto-expands when this is the selected workspace.
            if workspace.get('selected') is True:
                selected['is_collapsed'] = False
        step = 'restore_collapse'
        if retained.get('restore_collapse') and not selected['is_collapsed']:
            response = call('workspace.group.collapse', params)
            if not _same(response.get('group_id'), selected['id']) or response.get('is_collapsed') is not True:
                raise ValueError('Native collapse restoration returned inconsistent identity/state')
            done(step)
        else:
            done(step, 'already_complete')
        retained['restore_collapse'] = False
        step = 'group_color'
        if _same(selected.get('custom_color'), color):
            done(step, 'already_complete')
        else:
            response = call('workspace.group.set_color', dict(params, hex=color))
            if not _same(response.get('group_id'), selected['id']) or not _same(response.get('custom_color'), color):
                raise ValueError('Native group color returned inconsistent identity/color')
            done(step)
        step = 'workspace_color'
        if _same(workspace.get('custom_color'), color):
            done(step, 'already_complete')
        else:
            response = call('workspace.action', dict(window_id=window_id, workspace_id=workspace_id,
                                                    action='set_color', color=color))
            if not _same(response.get('workspace_id'), workspace_id) or not _same(response.get('color'), color):
                raise ValueError('Native workspace color returned inconsistent identity/color')
            done(step)
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError, subprocess.TimeoutExpired) as exc:
        warning = dict(step=step, code='native_presentation_incomplete', message=str(exc),
                       action='Inspect the named native step and observed refs, correct the condition for future launches; do not relaunch the agent.',
                       observed_refs=copy.deepcopy(result['observed_refs']),
                       workspace_id=workspace_id, window_id=window_id, group_id=retained.get('group_id'))
        result.update(outcome='warning', diagnostic=warning, warnings=[warning])
        result['steps'].append(dict(step=step, outcome='warning'))
    return result
