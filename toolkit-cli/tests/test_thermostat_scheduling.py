"""Selection capture replay and development outer-composition checks."""
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit.thermostat_schedule_levels import ScheduleLevel
from cbus_toolkit.thermostat_scheduling import ScheduleGroup, SchedulingState, ThermostatScheduling


def levels(addresses):
    return tuple(ScheduleLevel('existing:' + str(n), n, 255 - n, 'Existing ' + str(n)) for n in addresses)


class ThermostatSchedulingTests(unittest.TestCase):
    def test_twelve_original_outer_workflows_states_save_order_and_semantic_events(self):
        path = Path(__file__).resolve().parents[1] / 'research/fixtures/thermostat-scheduling-outer-vectors.json'
        fixture = json.loads(path.read_text())
        self.assertEqual(len(fixture['cases']), 12)
        for row in fixture['cases']:
            case, observed = row['case'], row['observed']
            with self.subTest(case=case['id']):
                groups = [ScheduleGroup(g['identity'], g['address'], tuple(
                    ScheduleLevel('existing:' + str(v['address']), v['address'], v['value'], v['tag'])
                    for v in g['levels'])) for g in case['groups']]
                model = ThermostatScheduling()
                state = model.load(groups, **case['roles'], enabled=case['enabled'],
                                   save_lock=case['initial_lock'], pending_save=case['initial_pending'])
                saves = []
                failure = OSError('injected original provider boundary')
                def level_save(group, level, snapshot):
                    saves.append({'event': 'level_save', 'group': group, 'address': level.address,
                                  'value': level.value, 'tag': level.tag})
                    if snapshot.level_save_attempts == case['deny_level_save']:
                        raise failure
                def storage_save(snapshot):
                    saves.append({'event': 'storage'})
                    if snapshot.storage_attempts == case['deny_storage_save']:
                        raise failure
                if observed['completed']:
                    outcome = model.create_levels(state, policy=case['entry'], level_save=level_save,
                                                  storage_save=storage_save)
                else:
                    with self.assertRaises(OSError) as caught:
                        model.create_levels(state, policy=case['entry'], level_save=level_save,
                                            storage_save=storage_save)
                    self.assertIs(caught.exception, failure)
                    outcome = model.last_outcome
                document = outcome.as_dict()
                current = outcome.state
                if case['release_lock']:
                    current = model.end_save_lock(current, storage_save=storage_save).state
                self.assertEqual(saves, [e for e in observed['trace'] if e['event'] in ('level_save', 'storage')])
                self.assertEqual([(r['role'], r['group'], r['action']) for r in document['roles']],
                                 [(r['role'], r['group'], r['action']) for r in observed['trace'] if r['event'] == 'inner'])
                normalized, in_inner, role = [], False, None
                index = {g['identity']: g for g in case['groups']}
                for event in observed['trace']:
                    name = event['event']
                    if name == 'inner':
                        in_inner = True
                    elif name == 'inner_return':
                        in_inner = False
                    elif not in_inner:
                        if name == 'get_enable':
                            normalized.append({'event': 'enabled', 'value': event['value']})
                        elif name == 'get_role':
                            role = event['role']
                            normalized.append({'event': 'group', 'role': role, 'present': event['group'] is not None})
                        elif name == 'is_unused':
                            normalized.append({'event': 'address', 'role': role, 'value': index[event['group']]['address']})
                        elif name == 'find':
                            normalized.append({'event': 'find', 'role': role, 'address': event['address'],
                                               'create': event['create'], 'found': any(
                                                   v['address'] == event['address'] for v in index[event['group']]['levels'])})
                        elif name == 'cursor':
                            normalized.append(event)
                        elif name in ('delay_begin', 'delay_finish'):
                            normalized.append({'event': 'delay_started' if name == 'delay_begin' else 'delay_finished'})
                self.assertEqual(document['events'], normalized)
                actual = current.as_dict()
                actual.pop('roles'); actual.pop('enabled')
                for group in actual['groups']:
                    for level in group['levels']:
                        level.pop('identity')
                actual['lock'] = actual.pop('save_lock')
                actual['pending'] = actual.pop('pending_save')
                actual['level_attempts'] = actual.pop('level_save_attempts')
                actual['level_completed'] = actual.pop('level_save_completed')
                expected = {k: v for k, v in observed['state'].items() if k not in ('cursor', 'delay_active')}
                self.assertEqual(actual, expected)
                self.assertEqual(document['complete'], observed['completed'])

    def test_all_twelve_original_predicate_captures_and_lazy_events(self):
        path = Path(__file__).resolve().parents[1] / 'research/fixtures/thermostat-scheduling-selection-vectors.json'
        vectors = json.loads(path.read_text())
        self.assertEqual(vectors['original_entry_calls'], 24)
        for row in vectors['cases']:
            case = row['case']
            with self.subTest(case=case['id']):
                model = ThermostatScheduling(); groups = []; roles = {}
                for role, group in case['groups'].items():
                    roles[role] = None if group is None else role
                    if group is not None:
                        groups.append(ScheduleGroup(role, group['address'], levels(group['level_addresses'])))
                state = model.load(groups, enabled=case['enabled'], **roles)
                self.assertEqual(model.selected(state), row['observed']['selected'])
                self.assertEqual(model.required(state), row['observed']['required'])

    def test_button_disabled_never_enters_outer_but_direct_does(self):
        model = ThermostatScheduling(); state = model.load([ScheduleGroup('a', 1)], on='a', enabled=False)
        result = model.create_levels(state)
        self.assertEqual(result.state.groups[0].levels, ())
        self.assertEqual(result.as_dict()['events'], [{'event': 'enabled', 'value': False}])
        self.assertEqual(result.as_dict()['roles'], [])
        direct = model.create_levels(state, policy='direct')
        self.assertEqual(len(direct.state.groups[0].levels), 31)
        self.assertIsNone(direct.as_dict()['required'])
        self.assertFalse(any(x['event'] == 'enabled' for x in direct.as_dict()['events']))

    def test_three_distinct_roles_share_project_counters_and_flush_separately(self):
        model = ThermostatScheduling(); state = model.load([ScheduleGroup(x, n) for n, x in enumerate('abc', 1)],
                                                          on='a', off='b', override='c', enabled=True)
        saves = []
        result = model.create_levels(state, storage_save=lambda snapshot: saves.append(snapshot))
        self.assertEqual([x.storage_attempts for x in saves], [1, 2, 3])
        self.assertEqual([x.storage_completed for x in saves], [0, 1, 2])
        self.assertEqual([x.level_save_completed for x in saves], [62, 124, 186])
        self.assertEqual((result.state.save_lock, result.state.pending_save), (0, False))
        self.assertEqual((result.state.level_save_attempts, result.state.storage_completed, result.state.project_requests), (186, 3, 99))
        self.assertEqual([x['action'] for x in result.as_dict()['roles']], ['Enable', 'Disable', 'Overrd'])
        self.assertEqual([x.levels[0].tag for x in result.state.groups],
                         ['Sched Enable Zone:unsw', 'Sched Disable Zone:unsw', 'Sched Overrd Zone:unsw'])

    def test_shared_roles_are_not_deduplicated_and_first_labels_survive(self):
        model = ThermostatScheduling(); state = model.load([ScheduleGroup('same', 1)], on='same', off='same', override='same', enabled=True)
        result = model.create_levels(state)
        self.assertEqual(len(result.as_dict()['roles']), 3)
        self.assertEqual((result.state.level_save_completed, result.state.storage_completed), (62, 1))
        self.assertTrue(all(level.tag.startswith('Sched Enable ') for level in result.state.groups[0].levels))
        self.assertEqual([x['inner']['state']['level_save_attempts'] for x in result.as_dict()['roles']], [62, 0, 0])

    def test_complete_and_unused_groups_preserve_extra_values_and_identity(self):
        complete = ScheduleGroup('complete', 1, levels([255, 0, 32, *range(1, 32)]))
        unused = ScheduleGroup('unused', 255, levels([4]))
        missing = ScheduleGroup('missing', 3, levels(range(1, 31)))
        model = ThermostatScheduling(); state = model.load([complete, unused, missing], on='complete', off='unused', override='missing', enabled=True)
        result = model.create_levels(state)
        self.assertEqual([r['role'] for r in result.as_dict()['roles']], ['on', 'override'])
        for before, after in zip(complete.levels, result.state.groups[0].levels): self.assertIs(before, after)
        self.assertIs(unused, result.state.groups[1])
        self.assertEqual(result.state.groups[2].levels[-1].tag, 'Sched Overrd Zones:unsw,1,2,3,4')
        self.assertEqual(result.state.level_save_completed, 2)

    def test_one_outer_lock_defers_all_groups_and_explicit_release_flushes_once(self):
        model = ThermostatScheduling(); state = model.load([ScheduleGroup(x, n) for n, x in enumerate('abc', 1)],
                                                          on='a', off='b', override='c', enabled=True, save_lock=1)
        result = model.create_levels(state, policy='direct')
        self.assertEqual((result.state.save_lock, result.state.pending_save, result.state.storage_completed), (1, True, 0))
        seen = []
        released = model.end_save_lock(result.state, storage_save=lambda snapshot: seen.append(snapshot))
        self.assertEqual(len(seen), 1)
        self.assertEqual((released.state.save_lock, released.state.pending_save, released.state.storage_completed), (0, False, 1))
        self.assertEqual(released.state.groups, result.state.groups)
        self.assertEqual(released.state.project_requests, 97)

    def test_second_storage_failure_retains_completed_first_and_partial_second(self):
        model = ThermostatScheduling(); state = model.load([ScheduleGroup(x, n) for n, x in enumerate('abc', 1)], on='a', off='b', override='c')
        first = KeyboardInterrupt('second storage')
        def save(snapshot):
            if snapshot.storage_attempts == 2: raise first
        with self.assertRaises(KeyboardInterrupt) as caught: model.create_levels(state, policy='direct', storage_save=save)
        self.assertIs(caught.exception, first); self.assertIs(model.last_error, first)
        outcome = model.last_outcome
        self.assertEqual([len(g.levels) for g in outcome.state.groups], [31, 31, 0])
        self.assertEqual((outcome.state.save_lock, outcome.state.pending_save, outcome.state.storage_completed), (0, True, 1))
        self.assertEqual(len(outcome.as_dict()['roles']), 2)
        self.assertFalse(any(x['event'] == 'delay_finished' for x in outcome.as_dict()['events']))
        with self.assertRaisesRegex(ValueError, 'cannot be resumed'): model.create_levels(outcome.state)

    def test_global_save65_stops_second_group_after_default_creation(self):
        model = ThermostatScheduling(); state = model.load([ScheduleGroup(x, n) for n, x in enumerate('abc', 1)], on='a', off='b', override='c')
        failure = OSError('denied')
        def save(group, level, snapshot):
            if snapshot.level_save_attempts == 65: raise failure
        with self.assertRaises(OSError) as caught: model.create_levels(state, policy='direct', level_save=save)
        self.assertIs(caught.exception, failure)
        result = model.last_outcome.state
        self.assertEqual([len(g.levels) for g in result.groups], [31, 2, 0])
        self.assertEqual([x.tag for x in result.groups[1].levels], ['Sched Disable Zone:unsw', 'Level 2'])
        self.assertEqual((result.save_lock, result.pending_save, result.level_save_completed), (1, True, 64))

    def test_callback_snapshot_mutation_cannot_change_retained_group(self):
        model = ThermostatScheduling(); state = model.load([ScheduleGroup('a', 1)], on='a')
        def corrupt(group, level, snapshot): object.__setattr__(snapshot.groups[0], 'address', 99)
        with self.assertRaisesRegex(ValueError, 'changed'): model.create_levels(state, policy='direct', level_save=corrupt)
        self.assertEqual(model.last_outcome.state.groups[0].address, 1)
        self.assertEqual(model.last_outcome.state.level_save_completed, 0)

    def test_tampered_foreign_or_invalid_state_and_reentrant_callback(self):
        model = ThermostatScheduling(); state = model.load([ScheduleGroup('a', 1)], on='a')
        with self.assertRaises(ValueError): model.required(replace(state))
        with self.assertRaises(ValueError): model.load([ScheduleGroup('a', True)])
        with self.assertRaises(ValueError): model.load([ScheduleGroup('a', 1), ScheduleGroup('b', 1)])
        def recurse(group, level, snapshot): model.selected(state)
        with self.assertRaisesRegex(ValueError, 'already active'): model.create_levels(state, policy='direct', level_save=recurse)
        object.__setattr__(state, 'enabled', 0)
        with self.assertRaises(ValueError): model.selected(state)

    def test_first_failure_survives_result_export_and_export_only_failure_is_not_success(self):
        model = ThermostatScheduling(); state = model.load([ScheduleGroup('a', 1)], on='a')
        first = KeyboardInterrupt('first')
        def save(group, level, snapshot): raise first
        with patch.object(SchedulingState, 'as_dict', side_effect=SystemExit('export')):
            with self.assertRaises(KeyboardInterrupt) as caught: model.create_levels(state, policy='direct', level_save=save)
        self.assertIs(caught.exception, first)
        self.assertTrue(model.last_outcome.as_dict()['evidence_export_failed'])
        with patch.object(SchedulingState, 'as_dict', side_effect=SystemExit('export only')):
            with self.assertRaises(SystemExit): model.create_levels(state, policy='direct')
        self.assertIsInstance(model.last_error, SystemExit)
        with self.assertRaisesRegex(ValueError, 'cannot be resumed'): model.create_levels(model.last_outcome.state)

    def test_unused_address_255_is_shareable_but_other_duplicates_rejected(self):
        model = ThermostatScheduling()
        state = model.load([ScheduleGroup('a', 255), ScheduleGroup('b', 255), ScheduleGroup('c', 255)],
                           on='a', off='b', override='c', enabled=True)
        self.assertFalse(model.selected(state)['value'])
        self.assertFalse(model.required(state)['value'])
        with self.assertRaisesRegex(ValueError, 'unique'):
            model.load([ScheduleGroup('a', 1), ScheduleGroup('b', 1)])
        with self.assertRaisesRegex(ValueError, 'unique'):
            model.load([ScheduleGroup('a', 1), ScheduleGroup('a', 2)])

    def test_all_255_indistinguishable_from_empty_and_mixed_processes_only_real(self):
        model = ThermostatScheduling()
        all_unused = model.load([ScheduleGroup('a', 255)], on='a', enabled=True)
        empty = model.load([], enabled=True)
        self.assertEqual(model.selected(all_unused)['value'], model.selected(empty)['value'])
        self.assertEqual(model.required(all_unused)['value'], model.required(empty)['value'])
        mixed = model.load([ScheduleGroup('u', 255), ScheduleGroup('r', 1)], on='u', off='r', enabled=True)
        self.assertTrue(model.selected(mixed)['value'])
        result = model.create_levels(mixed, policy='direct')
        self.assertEqual([r['role'] for r in result.as_dict()['roles']], ['off'])

    def test_address_zero_is_real_actionable_not_sentinel(self):
        model = ThermostatScheduling()
        state = model.load([ScheduleGroup('z', 0)], on='z', enabled=True)
        self.assertTrue(model.selected(state)['value'])
        self.assertTrue(model.required(state)['value'])

    def test_button_disabled_noop_reports_complete_with_only_enabled_event(self):
        model = ThermostatScheduling()
        state = model.load([ScheduleGroup('a', 1)], on='a', enabled=False)
        result = model.create_levels(state)
        doc = result.as_dict()
        self.assertTrue(doc['complete'])
        self.assertEqual(doc['events'], [{'event': 'enabled', 'value': False}])

    def test_save_lock_bounds_load_vs_issued(self):
        model = ThermostatScheduling()
        with self.assertRaisesRegex(ValueError, 'save lock'):
            model.load([ScheduleGroup('a', 1)], on='a', save_lock=3)
        state = model.load([ScheduleGroup('a', 1)], on='a', save_lock=2, pending_save=True)
        self.assertEqual(state.save_lock, 2)
        self.assertTrue(state.pending_save)

    def test_nested_lock_two_delivers_depth_three_to_save_provider(self):
        model = ThermostatScheduling()
        state = model.load([ScheduleGroup('a', 1)], on='a', save_lock=2)
        seen = []
        result = model.create_levels(state, policy='direct',
                                     level_save=lambda group, level, snapshot: seen.append(snapshot.save_lock))
        self.assertEqual(seen, [3] * 62)
        self.assertEqual((result.state.save_lock, result.state.pending_save), (2, True))
        self.assertEqual(result.state.storage_attempts, 0)
        first_release = model.end_save_lock(result.state)
        self.assertEqual((first_release.state.save_lock, first_release.state.pending_save), (1, True))
        saved = []
        final = model.end_save_lock(first_release.state, storage_save=saved.append)
        self.assertEqual(len(saved), 1)
        self.assertEqual((final.state.save_lock, final.state.pending_save, final.state.storage_completed),
                         (0, False, 1))

    def test_nested_lock_failure_retains_depth_three_and_first_error(self):
        model = ThermostatScheduling()
        state = model.load([ScheduleGroup('a', 1)], on='a', save_lock=2)
        first = KeyboardInterrupt('level provider interrupted')
        seen = []
        def fail(group, level, snapshot):
            seen.append(snapshot.save_lock)
            raise first
        with self.assertRaises(KeyboardInterrupt) as caught:
            model.create_levels(state, policy='direct', level_save=fail)
        self.assertIs(caught.exception, first)
        self.assertEqual(seen, [3])
        self.assertIs(model.last_error, first)
        doc = model.last_outcome.as_dict()
        self.assertFalse(doc['complete'])
        self.assertNotIn('evidence_export_failed', doc)
        self.assertEqual(doc['state']['save_lock'], 3)
        self.assertEqual(doc['state']['level_save_attempts'], 1)
        self.assertEqual(doc['state']['level_save_completed'], 0)
        self.assertEqual(doc['state']['groups'][0]['levels'][0]['tag'], 'Level 1')
        with self.assertRaisesRegex(ValueError, 'cannot be resumed'):
            model.end_save_lock(model.last_outcome.state)

    def test_release_failure_retains_pending_save_and_first_error(self):
        model = ThermostatScheduling()
        state = model.load([ScheduleGroup('a', 1)], on='a', save_lock=1, pending_save=True)
        first = OSError('storage refused')
        def fail(snapshot):
            self.assertEqual((snapshot.save_lock, snapshot.pending_save), (0, True))
            raise first
        with self.assertRaises(OSError) as caught:
            model.end_save_lock(state, storage_save=fail)
        self.assertIs(caught.exception, first)
        doc = model.last_outcome.as_dict()
        self.assertFalse(doc['complete'])
        self.assertEqual((doc['state']['save_lock'], doc['state']['pending_save']), (0, True))
        self.assertEqual((doc['state']['storage_attempts'], doc['state']['storage_completed']), (1, 0))
        with self.assertRaisesRegex(ValueError, 'cannot be resumed'):
            model.create_levels(model.last_outcome.state)
