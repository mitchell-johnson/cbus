from pathlib import Path
import copy
import dataclasses
import json
import unittest
from unittest.mock import patch

from cbus_toolkit.thermostat_schedule_levels import (
    ScheduleLevel, ScheduleLevelsEngine, ScheduleLevelsOutcome,
    ScheduleLevelsState, level_to_zones,
)

VECTORS = Path(__file__).resolve().parents[1] / 'research' / 'fixtures' / 'thermostat-schedule-levels-vectors.json'


def projected_state(state):
    result = state.as_dict()
    for level in result['levels']:
        del level['identity']
    return result


def projected_event(event):
    result = {'event': event.event}
    if event.event == 'find_level_entry':
        result.update(address=event.address, create=event.create, state_count=len(event.state.levels))
    else:
        result['state'] = projected_state(event.state)
    if event.level is not None:
        result['level'] = {k: v for k, v in event.level.as_dict().items() if k != 'identity'}
    return result


class ScheduleLevelsTests(unittest.TestCase):
    def test_fourteen_original_cases_all_recorded_phases(self):
        vectors = json.loads(VECTORS.read_text())
        self.assertEqual(len(vectors['cases']), 14)
        for row in vectors['cases']:
            case = row['case']
            with self.subTest(case=case['id']):
                if case['kind'] == 'zones':
                    self.assertEqual({str(n): level_to_zones(n) for n in range(1, 32)}, row['labels'])
                    continue
                engine = ScheduleLevelsEngine()
                existing = tuple(ScheduleLevel('existing:' + str(n), **v) for n, v in enumerate(case['existing']))
                state = engine.load(existing, save_lock=case['initial_lock'], pending_save=case['initial_pending'])
                events = []; phases = []; failure = OSError('Supplied provider denial')
                def level_save(level, snapshot):
                    if snapshot.level_save_attempts == case['deny_level_save']:
                        raise failure
                def storage_save(snapshot):
                    if snapshot.storage_attempts == case['deny_storage_save']:
                        raise failure
                try:
                    for action in case['actions']:
                        outcome = engine.create_levels(state, action, level_save=level_save, storage_save=storage_save)
                        state = outcome.state; events.extend(outcome.events)
                        phases.append({'action': action, 'state': projected_state(state)})
                    if case['release_outer_locks']:
                        for _ in range(case['initial_lock']):
                            outcome = engine.end_save_lock(state, storage_save=storage_save)
                            state = outcome.state; events.extend(outcome.events)
                            phases.append({'action': 'explicit-owned-outer-EndSaveLock', 'state': projected_state(state)})
                except BaseException as error:
                    self.assertIs(error, failure)
                    outcome = engine.last_outcome; state = outcome.state; events.extend(outcome.events)
                self.assertEqual(outcome.complete, row['complete'])
                self.assertEqual(projected_state(state), row['final'])
                self.assertEqual(phases, row['phases'])
                self.assertEqual([projected_event(e) for e in events], row['events'])
                self.assertTrue(all(a is b for a, b in zip(existing, state.levels)))

    def test_new_default_and_retag_share_identity_with_detached_snapshots(self):
        engine = ScheduleLevelsEngine(); seen = []
        result = engine.create_levels(engine.load([]), 'Enable', level_save=lambda level, state: seen.append((level, state)))
        self.assertEqual(len(seen), 62)
        for n in range(31):
            first, second = seen[n * 2:n * 2 + 2]
            self.assertEqual(first[0].identity, second[0].identity)
            self.assertEqual(first[0].tag, f'Level {n + 1}')
            self.assertEqual(second[0].tag, f'Sched Enable {level_to_zones(n + 1)}')
            self.assertEqual(first[1].level_save_completed, n * 2)
        self.assertEqual(seen[0][1].levels[0].tag, 'Level 1')
        self.assertEqual(result.state.levels[0].tag, 'Sched Enable Zone:unsw')

    def test_all_byte_addresses_have_independent_values_and_no_retag(self):
        levels = tuple(ScheduleLevel(str(n), n, 255 - n, f'opaque {n}') for n in reversed(range(256)))
        engine = ScheduleLevelsEngine(); state = engine.load(levels)
        result = engine.create_levels(state, 'Disable')
        self.assertEqual(result.state.levels, levels)
        self.assertTrue(all(a is b for a, b in zip(levels, result.state.levels)))
        self.assertEqual(result.state.level_save_attempts, 0)
        self.assertEqual(result.state.storage_attempts, 0)

    def test_issued_identity_and_tampered_state_rejected(self):
        engine = ScheduleLevelsEngine(); state = engine.load([])
        for forged in (dataclasses.replace(state), copy.copy(state), ScheduleLevelsEngine().load([]), object()):
            with self.assertRaises(ValueError): engine.create_levels(forged, 'Enable')
        object.__setattr__(state, 'save_lock', 1)
        with self.assertRaises(ValueError): engine.create_levels(state, 'Enable')

    def test_tampered_record_rejected_and_input_list_detached(self):
        engine = ScheduleLevelsEngine(); level = ScheduleLevel('retained', 1, 203, 'keep'); levels = [level]
        state = engine.load(levels); levels.clear()
        self.assertEqual(state.levels, (level,))
        object.__setattr__(level, 'value', 1)
        with self.assertRaises(ValueError): engine.create_levels(state, 'Enable')

    def test_equal_valued_type_or_container_tampering_rejected(self):
        class Text(str): pass
        for target, field, value in [('level', 'value', True), ('level', 'address', True),
                                     ('level', 'identity', Text('kept')), ('level', 'tag', Text('label')),
                                     ('state', 'save_lock', False), ('state', 'pending_save', 0),
                                     ('state', 'levels', 'list')]:
            with self.subTest(target=target, field=field):
                engine = ScheduleLevelsEngine(); level = ScheduleLevel('kept', 1, 1, 'label')
                state = engine.load([level])
                if field == 'levels': value = list(state.levels)
                object.__setattr__(level if target == 'level' else state, field, value)
                with self.assertRaises(ValueError): engine.create_levels(state, 'Enable')

    def test_schema_preflight_exact_types_and_duplicates(self):
        valid = ScheduleLevel('id', 1, 17, 'keep')
        for levels in ((valid, dataclasses.replace(valid, identity='other')), (valid, dataclasses.replace(valid, address=2)), [object()], [valid] * 257, iter([valid])):
            with self.assertRaises(ValueError): ScheduleLevelsEngine().load(levels)
        for field, bad in [('address', True), ('address', -1), ('address', 256), ('value', True), ('value', -1), ('value', 256), ('identity', ''), ('tag', '\0'), ('tag', '\ud800'), ('tag', 'x' * 129)]:
            with self.assertRaises(ValueError): ScheduleLevelsEngine().load([dataclasses.replace(valid, **{field: bad})])
        for lock in (True, -1, 3):
            with self.assertRaises(ValueError): ScheduleLevelsEngine().load([], save_lock=lock)
        with self.assertRaises(ValueError): ScheduleLevelsEngine().load([], pending_save=1)

    def test_invalid_action_and_providers_do_not_invoke_callbacks(self):
        engine = ScheduleLevelsEngine(); state = engine.load([]); calls = []
        for action in (None, True, '', 'Override', 'Enable ', 1):
            with self.assertRaises(ValueError): engine.create_levels(state, action, level_save=lambda *x: calls.append(x))
        with self.assertRaises(ValueError): engine.create_levels(state, 'Enable', level_save=object())
        with self.assertRaises(ValueError): engine.end_save_lock(state, storage_save=lambda *x: calls.append(x))
        self.assertEqual(calls, [])

    def test_level_labels_reject_wrong_domain(self):
        for value in (0, 32, -1, True, 1.0, '1'):
            with self.assertRaises(ValueError): level_to_zones(value)

    def test_both_denials_retain_first_object_and_nonresumable_prefix(self):
        class RefusesEvidence(KeyboardInterrupt):
            def __setattr__(self, name, value):
                if name.endswith('_evidence'): raise SystemExit('secondary attachment')
                super().__setattr__(name, value)
            def with_traceback(self, value): raise SystemExit('secondary dispatch')
            def __str__(self): raise SystemExit('secondary formatting')
        for error in (OSError('save'), KeyboardInterrupt('save'), SystemExit('save'), RefusesEvidence()):
            for location in ('level', 'storage'):
                with self.subTest(error=type(error).__name__, location=location):
                    engine = ScheduleLevelsEngine(); state = engine.load([])
                    def level(level, state):
                        if location == 'level' and state.level_save_attempts == 3: raise error
                    def storage(state):
                        if location == 'storage': raise error
                    try: engine.create_levels(state, 'Enable', level_save=level, storage_save=storage)
                    except BaseException as observed: self.assertIs(observed, error)
                    else: self.fail('Expected supplied save failure')
                    self.assertIs(engine.last_error, error)
                    outcome = engine.last_outcome
                    self.assertFalse(outcome.complete); self.assertFalse(engine.last_evidence['complete'])
                    self.assertEqual(outcome.state.save_lock, int(location == 'level'))
                    self.assertTrue(outcome.state.pending_save)
                    with self.assertRaises(ValueError): engine.create_levels(outcome.state, 'Enable')

    def test_evidence_export_failure_does_not_replace_operational_error(self):
        engine = ScheduleLevelsEngine(); state = engine.load([]); first = KeyboardInterrupt('level')
        def fail(*args): raise first
        with patch.object(ScheduleLevelsOutcome, 'as_dict', side_effect=SystemExit('secondary export')):
            try: engine.create_levels(state, 'Enable', level_save=fail)
            except BaseException as error: self.assertIs(error, first)
            else: self.fail('Expected failure')
        self.assertIs(engine.last_error, first)
        self.assertFalse(engine.last_outcome.complete)
        self.assertTrue(engine.last_evidence['evidence_export_failed'])

    def test_success_export_fallback_and_detached_exports(self):
        engine = ScheduleLevelsEngine(); state = engine.load([])
        with patch.object(ScheduleLevelsOutcome, 'as_dict', side_effect=SystemExit('export')):
            result = engine.create_levels(state, 'Enable')
        self.assertTrue(result.complete); self.assertIsNone(engine.last_error)
        self.assertTrue(engine.last_evidence['complete'])
        exported = result.as_dict(); exported['state']['levels'][0]['value'] = 999
        self.assertEqual(result.state.levels[0].value, 1)

    def test_reused_engine_clears_failure_before_invalid_preflight(self):
        engine = ScheduleLevelsEngine(); state = engine.load([])
        def fail(*args): raise OSError('save')
        with self.assertRaises(OSError): engine.create_levels(state, 'Enable', level_save=fail)
        self.assertIsNotNone(engine.last_outcome)
        with self.assertRaises(ValueError): engine.create_levels(state, 'wrong')
        self.assertIsNone(engine.last_outcome); self.assertIsNone(engine.last_error); self.assertIsNone(engine.last_evidence)

    def test_callback_reentry_stops_with_reviewable_prefix(self):
        engine = ScheduleLevelsEngine(); state = engine.load([])
        def reenter(*args): engine.load([])
        with self.assertRaises(ValueError): engine.create_levels(state, 'Enable', level_save=reenter)
        self.assertFalse(engine.last_outcome.complete)
        self.assertEqual(engine.last_outcome.state.level_save_attempts, 1)
        self.assertEqual(engine.last_outcome.state.level_save_completed, 0)

    def test_callback_mutation_isolated_and_rejected(self):
        for location in ('level', 'storage'):
            engine = ScheduleLevelsEngine(); retained = ScheduleLevel('retained', 1, 203, 'keep')
            state = engine.load([retained])
            def level(record, snapshot):
                if location == 'level': object.__setattr__(snapshot.levels[0], 'value', 999)
            def storage(snapshot):
                if location == 'storage': object.__setattr__(snapshot, 'pending_save', 1)
            with self.assertRaisesRegex(ValueError, 'immutable snapshot'):
                engine.create_levels(state, 'Enable', level_save=level, storage_save=storage)
            self.assertFalse(engine.last_outcome.complete)
            self.assertIs(engine.last_outcome.state.levels[0], retained)
            self.assertEqual(retained.value, 203)
            self.assertTrue(all(type(x.value) is int and x.value <= 255 for x in engine.last_outcome.state.levels))

    def test_corrupt_callback_snapshot_then_interruption_keeps_first(self):
        for location in ('level', 'storage'):
            engine = ScheduleLevelsEngine(); state = engine.load([]); first = KeyboardInterrupt('callback')
            def level(record, snapshot):
                if location == 'level':
                    object.__setattr__(snapshot, 'levels', None); raise first
            def storage(snapshot):
                if location == 'storage':
                    object.__setattr__(snapshot, 'levels', None); raise first
            try: engine.create_levels(state, 'Enable', level_save=level, storage_save=storage)
            except BaseException as observed: self.assertIs(observed, first)
            else: self.fail('Expected original interruption')
            self.assertIs(engine.last_error, first)
            self.assertFalse(engine.last_outcome.complete)
            self.assertEqual(len(engine.last_outcome.state.levels), 1 if location == 'level' else 31)

    def test_generated_identity_avoids_retained_collision(self):
        engine = ScheduleLevelsEngine(); old = ScheduleLevel('schedule:1', 31, 9, 'keep')
        state = engine.create_levels(engine.load([old]), 'Overrd').state
        self.assertIs(state.levels[0], old)
        self.assertEqual(len({x.identity for x in state.levels}), 31)


if __name__ == '__main__': unittest.main(verbosity=2)
