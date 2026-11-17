"""RWG-04/05: public adapter seam, scripted cmux RPCs only (no live IO)."""
import copy
import json
import subprocess
import unittest
from uuid import UUID

from tforklib.presentation import apply_presentation, CmuxRPC


def uid(n):
    return str(UUID(int=n))


WINDOW, OTHER, WORKSPACE, ANCHOR, GROUP = map(uid, (1, 2, 3, 4, 5))


def group(identity=GROUP, name='Flux', anchor=ANCHOR, members=None):
    return dict(id=identity, ref='workspace_group:5', name=name,
                anchor_workspace_id=anchor, anchor_workspace_ref='workspace:4',
                member_workspace_ids=members or [anchor], custom_color='#112233',
                is_pinned=True, is_collapsed=True)


class Native:
    """Stateful native boundary; preserves native defaults that matter here."""
    def __init__(self, groups=None):
        self.groups = copy.deepcopy([group()] if groups is None else groups)
        self.other_groups = [group(uid(20))]
        self.workspaces = [dict(id=WORKSPACE, ref='workspace:3', custom_color=None, selected=True),
                           dict(id=ANCHOR, ref='workspace:4', custom_color='#abcdef')]
        self.focus = 'surface:7'
        self.calls = []
        self.fail = None
        self.after_effect = False
        self.methods = ['workspace.list', 'workspace.group.list', 'workspace.group.create',
                        'workspace.group.move', 'workspace.group.add',
                        'workspace.group.set_color', 'workspace.group.collapse', 'workspace.action']

    def __call__(self, method, params):
        self.calls.append((method, copy.deepcopy(params)))
        if method == self.fail and not self.after_effect:
            raise RuntimeError('injected native failure')
        if method == 'system.capabilities':
            result = dict(methods=self.methods)
        else:
            assert params['window_id'] == WINDOW  # never read/move the other window
            if method == 'workspace.group.list':
                result = dict(window_id=WINDOW, window_ref='window:1', groups=self.groups)
            elif method == 'workspace.list':
                result = dict(window_id=WINDOW, window_ref='window:1', workspaces=self.workspaces)
            elif method == 'workspace.group.create':
                assert params['child_workspace_ids'] == []  # no implicit selection adoption
                fresh = group(uid(50), params['name'], uid(51))
                fresh.update(is_pinned=False, is_collapsed=False, custom_color=None)
                self.groups.insert(0, fresh)  # native anchor creation uses top placement
                self.workspaces.append(dict(id=uid(51), ref='workspace:51', custom_color=None))
                result = dict(group=fresh)
            else:
                selected = next((g for g in self.groups if g['id'] == params.get('group_id')), None)
                if method == 'workspace.group.move':
                    self.groups.remove(selected)
                    self.groups.insert(params['to_index'], selected)
                    result = dict(group_id=selected['id'])
                elif method == 'workspace.group.add':
                    assert params['placement'] == 'end'
                    workspace_id = params['workspace_id']
                    members = selected['member_workspace_ids']
                    if workspace_id in members:
                        members.remove(workspace_id)  # duplicate add would reorder on replay
                    members.append(workspace_id)
                    workspace = next(w for w in self.workspaces if w['id'] == workspace_id)
                    if workspace['selected']:
                        selected['is_collapsed'] = False
                    result = dict(group_id=selected['id'], workspace_id=workspace_id)
                elif method == 'workspace.group.collapse':
                    selected['is_collapsed'] = True
                    result = dict(group_id=selected['id'], is_collapsed=True)
                elif method == 'workspace.group.set_color':
                    selected['custom_color'] = params['hex']
                    result = dict(group_id=selected['id'], custom_color=params['hex'])
                elif method == 'workspace.action':
                    assert params['action'] == 'set_color'
                    workspace = next(w for w in self.workspaces if w['id'] == params['workspace_id'])
                    workspace['custom_color'] = params['color']
                    result = dict(workspace_id=workspace['id'], color=params['color'])
                else:
                    raise AssertionError(method)
        if method == self.fail:
            raise RuntimeError('reply lost after native effect')
        return copy.deepcopy(result)

    def mutations(self):
        return [m for m, _ in self.calls if m not in
                ('system.capabilities', 'workspace.list', 'workspace.group.list')]


def apply(native, state=None):
    return apply_presentation(group_name='Flux', color='#aabbcc', workspace_id=WORKSPACE,
                              window_id=WINDOW, rpc=native, state=state)


class PresentationTests(unittest.TestCase):
    def test_rwg04_rwg05_reuse_append_color_and_preserve_existing_presentation(self):
        native = Native([group(members=[ANCHOR, uid(6)]), group(uid(8), 'Other', uid(9))])
        native.workspaces.append(dict(id=uid(6), ref='workspace:6', custom_color='#123456'))
        before_other = copy.deepcopy(native.groups[1])
        result = apply(native)
        self.assertEqual(result['outcome'], 'success')
        self.assertEqual([g['id'] for g in native.groups], [GROUP, uid(8)])
        self.assertEqual(native.groups[0]['member_workspace_ids'], [ANCHOR, uid(6), WORKSPACE])
        self.assertEqual(native.groups[0]['custom_color'], '#aabbcc')
        self.assertTrue(native.groups[0]['is_pinned'])
        self.assertTrue(native.groups[0]['is_collapsed'])
        self.assertEqual(native.groups[1], before_other)
        self.assertEqual(native.workspaces[1]['custom_color'], '#abcdef')
        self.assertEqual(native.workspaces[2]['custom_color'], '#123456')
        self.assertEqual(native.workspaces[0]['custom_color'], '#aabbcc')
        self.assertEqual(native.focus, 'surface:7')
        self.assertEqual(result['state']['group_id'], GROUP)
        self.assertEqual(result['state']['anchor_workspace_id'], ANCHOR)
        self.assertEqual(result['incomplete'], [])

    def test_rwg04_create_fresh_anchor_at_end_and_replay_keeps_member_position(self):
        native = Native([group(uid(8), 'Other', uid(9))])
        other = copy.deepcopy(native.groups[0])
        result = apply(native)
        self.assertEqual(result['outcome'], 'success')
        self.assertEqual([g['id'] for g in native.groups], [uid(8), uid(50)])
        self.assertEqual(native.groups[0], other)
        self.assertEqual(native.groups[1]['member_workspace_ids'], [uid(51), WORKSPACE])
        self.assertEqual(result['state']['anchor_workspace_id'], uid(51))
        self.assertEqual(native.other_groups[0]['member_workspace_ids'], [ANCHOR])
        native.groups[1]['member_workspace_ids'].append(uid(90))
        native.calls.clear()
        replay = apply(native, json.loads(json.dumps(result['state'])))
        self.assertEqual(replay['outcome'], 'success')
        self.assertEqual(native.mutations(), [])
        self.assertEqual(native.groups[1]['member_workspace_ids'], [uid(51), WORKSPACE, uid(90)])

    def test_rwg04_duplicate_same_window_names_warn_without_mutation(self):
        native = Native([group(), group(uid(8), 'Flux', uid(9))])
        result = apply(native)
        self.assertEqual(result['outcome'], 'warning')
        self.assertEqual(result['diagnostic']['step'], 'select_group')
        self.assertEqual(len(result['diagnostic']['observed_refs']['matching_group_refs']), 2)
        self.assertEqual(native.mutations(), [])

    def test_run_test_failure_at_each_native_step_and_retry_remaining_only(self):
        steps = [('system.capabilities', 'capabilities'), ('workspace.group.list', 'list_groups'),
                 ('workspace.list', 'workspace_identity'), ('workspace.group.create', 'create_group'),
                 ('workspace.group.move', 'position_group'), ('workspace.group.add', 'append_workspace'),
                 ('workspace.group.set_color', 'group_color'), ('workspace.action', 'workspace_color')]
        for method, step in steps:
            with self.subTest(method=method):
                native = Native([group(uid(8), 'Other', uid(9))])
                native.fail = method
                first = apply(native)
                self.assertEqual(first['outcome'], 'warning')
                self.assertEqual(first['diagnostic']['step'], step)
                self.assertTrue(first['diagnostic']['action'])
                self.assertEqual(first['diagnostic']['workspace_id'], WORKSPACE)
                earlier = native.mutations()[:-1] if method in native.mutations() else []
                saved = copy.deepcopy(native.groups)
                if method == 'workspace.action':
                    self.assertEqual(saved[-1]['custom_color'], '#aabbcc')
                    self.assertEqual(saved[-1]['member_workspace_ids'], [uid(51), WORKSPACE])
                native.fail = None
                native.calls.clear()
                second = apply(native, first['state'])
                self.assertEqual(second['outcome'], 'success')
                self.assertEqual(len(native.groups), 2)
                self.assertEqual(len(native.workspaces), 3)
                for completed in earlier:
                    self.assertNotIn(completed, native.mutations())

    def test_run_test_lost_replies_reconcile_effects_without_duplicate_mutations(self):
        for method in ('workspace.group.create', 'workspace.group.move', 'workspace.group.add',
                       'workspace.group.set_color', 'workspace.action'):
            with self.subTest(method=method):
                native = Native([group(uid(8), 'Other', uid(9))])
                native.fail, native.after_effect = method, True
                first = apply(native)
                self.assertEqual(first['outcome'], 'warning')
                native.fail = None
                native.calls.clear()
                second = apply(native, first['state'])
                self.assertEqual(second['outcome'], 'success')
                self.assertNotIn(method, native.mutations())
                self.assertEqual(len(native.workspaces), 3)
                self.assertEqual(len(native.groups), 2)

    def test_rwg04_creation_response_name_is_validated_and_retained(self):
        native = Native([])
        def wrong_name(method, params):
            result = native(method, params)
            if method == 'workspace.group.create':
                native.groups[0]['name'] = 'Unexpected'
                result['group']['name'] = 'Unexpected'
            return result
        result = apply_presentation(group_name='Flux', color='#aabbcc', workspace_id=WORKSPACE,
                                    window_id=WINDOW, rpc=wrong_name)
        self.assertEqual(result['diagnostic']['step'], 'create_group')
        self.assertEqual(result['state']['group_id'], uid(50))
        self.assertEqual(result['state']['native_group_name'], 'Unexpected')
        self.assertEqual(native.mutations(), ['workspace.group.create'])
        native.calls.clear()
        retry = apply(native, result['state'])
        self.assertEqual(retry['outcome'], 'warning')
        self.assertEqual(native.mutations(), [])

    def test_run_test_unknown_creation_reconciles_missing_response_or_ambiguity(self):
        for variant in ('missing_payload', 'duplicate', 'different_name'):
            with self.subTest(variant=variant):
                native = Native([])
                def uncertain(method, params):
                    value = native(method, params)
                    if method == 'workspace.group.create':
                        if variant == 'duplicate':
                            native.groups.append(group(uid(70), 'Flux', uid(71)))
                        elif variant == 'different_name':
                            native.groups[0]['name'] = 'Unexpected'
                        return {}
                    return value
                first = apply_presentation(group_name='Flux', color='#aabbcc', workspace_id=WORKSPACE,
                                           window_id=WINDOW, rpc=uncertain)
                self.assertEqual(first['outcome'], 'warning')
                native.calls.clear()
                retry = apply(native, first['state'])
                self.assertEqual(retry['outcome'], 'success' if variant == 'missing_payload' else 'warning')
                self.assertNotIn('workspace.group.create', native.mutations())
                if variant != 'missing_payload':
                    self.assertEqual(native.mutations(), [])

    def test_run_test_missing_capabilities_warn_at_affected_step_and_resume(self):
        for method in [m for m in Native().methods if m != 'workspace.group.collapse']:
            with self.subTest(method=method):
                native = Native([group(uid(8), 'Other', uid(9))])
                native.methods.remove(method)
                first = apply(native)
                self.assertEqual(first['outcome'], 'warning')
                self.assertIn('Missing native capability', first['diagnostic']['message'])
                native.methods.append(method)
                self.assertEqual(apply(native, first['state'])['outcome'], 'success')

    def test_unreadable_or_wrong_window_topology_warns_without_mutation(self):
        for method in ('system.capabilities', 'workspace.group.list', 'workspace.list'):
            for payload in ({}, None, {'window_id': OTHER, 'groups': [], 'workspaces': []}):
                with self.subTest(method=method, payload=payload):
                    native = Native()
                    def malformed(m, params):
                        return payload if m == method else native(m, params)
                    result = apply_presentation(group_name='Flux', color='#aabbcc', workspace_id=WORKSPACE,
                                                window_id=WINDOW, rpc=malformed)
                    self.assertEqual(result['outcome'], 'warning')
                    self.assertTrue(result['incomplete'])
                    self.assertEqual(native.mutations(), [])

    def test_retained_group_identity_cannot_be_replaced_by_same_name(self):
        native = Native()
        first = apply(native)
        native.groups[0]['id'] = uid(80)
        native.calls.clear()
        retry = apply(native, first['state'])
        self.assertEqual(retry['outcome'], 'warning')
        self.assertEqual(native.mutations(), [])

    def test_missing_retained_group_can_create_its_required_anchor(self):
        native = Native()
        first = apply(native)
        native.groups.clear()
        native.calls.clear()
        retry = apply(native, first['state'])
        self.assertEqual(retry['outcome'], 'success')
        self.assertEqual(retry['state']['group_id'], uid(50))
        self.assertEqual(retry['state']['anchor_workspace_id'], uid(51))
        self.assertEqual(native.mutations().count('workspace.group.create'), 1)

    def test_existing_anchor_cannot_be_used_as_conductor_workspace(self):
        native = Native([group(anchor=WORKSPACE)])
        result = apply(native)
        self.assertEqual(result['diagnostic']['step'], 'workspace_identity')
        self.assertEqual(native.mutations(), [])

    def test_inputs_and_state_are_bound_to_verified_uuids_and_resolved_values(self):
        for fields in ({'workspace_id': 'workspace:3'}, {'window_id': 'window:1'},
                       {'group_name': ' Flux '}, {'group_name': 'bad\nname'},
                       {'color': '#ABCDEF'}, {'state': {'inputs': {}}}):
            with self.subTest(fields=fields):
                native = Native()
                args = dict(group_name='Flux', color='#aabbcc', workspace_id=WORKSPACE,
                            window_id=WINDOW, rpc=native)
                result = apply_presentation(**dict(args, **fields))
                self.assertEqual(result['diagnostic']['step'], 'inputs')
                self.assertEqual(native.calls, [])

    def test_native_reply_identity_mismatch_never_reports_complete(self):
        for method in ('workspace.group.move', 'workspace.group.add',
                       'workspace.group.set_color', 'workspace.action'):
            with self.subTest(method=method):
                native = Native([group(uid(8), 'Other', uid(9))])
                def mismatched(m, params):
                    value = native(m, params)
                    if m == method:
                        value.update(group_id=uid(999), workspace_id=uid(999))
                    return value
                result = apply_presentation(group_name='Flux', color='#aabbcc', workspace_id=WORKSPACE,
                                            window_id=WINDOW, rpc=mismatched)
                self.assertEqual(result['outcome'], 'warning')
                self.assertTrue(result['incomplete'])
                self.assertEqual(apply(native, result['state'])['outcome'], 'success')


class TransportTests(unittest.TestCase):
    def test_transport_uses_rpc_json_and_bounded_runner_without_shell(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, '{"methods": []}', '')
        self.assertEqual(CmuxRPC(runner=runner)('system.capabilities', {}), {'methods': []})
        self.assertEqual(calls[0][0], ['cmux', 'rpc', 'system.capabilities', '{}'])
        self.assertEqual(calls[0][1]['timeout'], 10)
        self.assertNotIn('shell', calls[0][1])

    def test_transport_failures_surface_as_native_step_warnings(self):
        for variant in ('exit', 'json', 'timeout', 'missing'):
            with self.subTest(variant=variant):
                def runner(argv, **kwargs):
                    if variant == 'timeout':
                        raise subprocess.TimeoutExpired(argv, 10)
                    if variant == 'missing':
                        raise FileNotFoundError('cmux unavailable')
                    return subprocess.CompletedProcess(argv, 1 if variant == 'exit' else 0,
                                                       'invalid json', 'native unavailable')
                result = apply_presentation(group_name='Flux', color='#aabbcc', workspace_id=WORKSPACE,
                                            window_id=WINDOW, rpc=CmuxRPC(runner=runner))
                self.assertEqual(result['outcome'], 'warning')
                self.assertEqual(result['diagnostic']['step'], 'capabilities')


class CollapseRetryTests(unittest.TestCase):
    def test_collapse_failure_keeps_membership_and_restores_state_on_retry(self):
        for variant in ('before', 'after', 'missing_capability'):
            with self.subTest(variant=variant):
                native = Native()
                if variant == 'missing_capability':
                    native.methods.remove('workspace.group.collapse')
                else:
                    native.fail = 'workspace.group.collapse'
                    native.after_effect = variant == 'after'
                first = apply(native)
                self.assertEqual(first['outcome'], 'warning')
                self.assertEqual(first['diagnostic']['step'], 'restore_collapse')
                self.assertEqual(native.groups[0]['member_workspace_ids'], [ANCHOR, WORKSPACE])
                native.fail = None
                if variant == 'missing_capability':
                    native.methods.append('workspace.group.collapse')
                native.calls.clear()
                retry = apply(native, first['state'])
                self.assertEqual(retry['outcome'], 'success')
                self.assertTrue(native.groups[0]['is_collapsed'])
                self.assertNotIn('workspace.group.add', native.mutations())
                if variant == 'after':
                    self.assertNotIn('workspace.group.collapse', native.mutations())


class CreationIdentityTests(unittest.TestCase):
    def test_creation_cannot_claim_preexisting_group_or_anchor_identity(self):
        for collision in ('group', 'anchor'):
            with self.subTest(collision=collision):
                native = Native([group(uid(8), 'Other', uid(9))])
                def collision_reply(method, params):
                    value = native(method, params)
                    if method == 'workspace.group.create':
                        if collision == 'group':
                            value['group']['id'] = uid(8)
                        else:
                            value['group']['anchor_workspace_id'] = ANCHOR
                            value['group']['member_workspace_ids'] = [ANCHOR]
                    return value
                result = apply_presentation(group_name='Flux', color='#aabbcc', workspace_id=WORKSPACE,
                                            window_id=WINDOW, rpc=collision_reply)
                self.assertEqual(result['outcome'], 'warning')
                self.assertEqual(result['diagnostic']['step'], 'create_group')
                self.assertEqual(native.mutations(), ['workspace.group.create'])
