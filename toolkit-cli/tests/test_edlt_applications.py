"""Original model/global-control observations with no implicit group getters."""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_application_cache import ApplicationCache, CachedDisplay, CachedGroupList
from cbus_toolkit.edlt_applications import EdltApplications, ApplicationEdit, ApplicationApplyError, ApplicationsPlan
from cbus_toolkit.edlt_lifecycle import LifecycleCache, LifecycleGroup, LifecycleMetadataError
from cbus_toolkit.unitspec import UnitSpecStore
from tests.test_edlt_lifecycle import fixture, Session, cache as lifecycle_cache

ROOT = Path(__file__).resolve().parents[1]
CAPTURE_SHA = 'f2898e63d92ee7deedeb4a6020ad593d961c1e18e239e344d63f527867419d91'


def observations(document, row):
    return [{'kind': kind, 'stage': stage, 'value': document['observation_values'][index]}
            for kind, stage, index in row['observations']]


def captured_cache(document, row):
    apps, groups, facts = [], {}, []
    for obs in observations(document, row):
        if obs['stage'] != 'raw-input': continue
        fields = obs['value'].split('|')
        if obs['kind'] == 'cache-app':
            address = int(fields[0]); apps.append(CachedDisplay(address, fields[1], fields[1])); groups[address] = []
        elif obs['kind'] == 'cache-group':
            application, address = map(int, fields[:2])
            groups[application].append(CachedDisplay(address, fields[2], fields[2]))
            levels = tuple(map(int, fields[4].removeprefix('levels=').split(','))) if fields[4] != 'levels=' else ()
            labels = fields[5].removeprefix('labels=')
            facts.append(LifecycleGroup(application, address, True,
                (False,) * len(labels.split(',')) if labels else (), True, levels))
    # The declared original fixture cache is complete. These explicit absent
    # facts cover its eight tested addresses without consulting an editor.
    for app in apps:
        present = {group.address for group in groups[app.address]}
        facts.extend(LifecycleGroup(app.address, number, False)
                     for number in (0, 1, 2, 7, 12, 42, 254, 255) if number not in present)
    return ApplicationCache(LifecycleCache(tuple(app.address for app in apps), tuple(facts)), True, tuple(apps),
        tuple(CachedGroupList(app.address, True, tuple(groups[app.address])) for app in apps))


def cache_for(editor, source):
    base = LifecycleCache.from_dict(lifecycle_cache(editor.lifecycle, source))
    apps = (56, 57, 136, 202, 203)
    facts = list(base.groups)
    for app in apps:
        for group in (7, 12, 42, 255):
            if not any(f.application == app and f.group == group for f in facts):
                facts.append(LifecycleGroup(app, group, True, (False,) * 4, True, (0, 1, 2, 255)))
    return ApplicationCache(LifecycleCache(apps, tuple(facts)), True,
        tuple(CachedDisplay(a, 'Same name', 'App ' + str(a)) for a in apps),
        tuple(CachedGroupList(a, True, tuple(CachedDisplay(g.group, 'Group', str(g.group))
            for g in facts if g.application == a and g.exists)) for a in apps))


class ApplicationStateTests(unittest.TestCase):
    def setUp(self):
        self.editor = EdltApplications(fixture())
        self.source = self.editor.snapshot(Session(fixture()).values())
        self.source.update(PrimaryApplication=(56,), SecondaryApplication=(57,),
            Widget6WidgetType=(2,), Widget6WidgetByteValue1=(128,), Widget6WidgetByteValue6=(7,))
        self.cache = cache_for(self.editor, self.source)

    def bound(self):
        return self.editor.bind_global_applications(self.editor.prepare_applications(
            self.editor.load(self.source, cache=self.cache)))

    def test_noop_disable_reenable_and_retained_model_identity(self):
        state = self.bound(); original = state
        with patch.object(self.editor.lifecycle, 'load', side_effect=AssertionError('second load')):
            state = self.editor.commit_application(state, field='secondary', address=57)
            self.assertEqual(state.wrapper_change_count, 0)
            state = self.editor.commit_application(state, field='secondary', address=255)
            self.assertEqual(state.values['Widget6WidgetByteValue1'], (0,))
            state = self.editor.commit_application(state, field='secondary', address=57)
            self.assertEqual(state.values['Widget6WidgetByteValue1'], (0,))
            self.assertEqual(state.wrapper_change_count, 2)
        self.assertIs(state.loaded, original.loaded)
        self.assertEqual(original.values['Widget6WidgetByteValue1'], (128,))
        self.assertFalse(state.as_dict()['dependency_getters_invoked'])

    def test_unavailable_selection_and_invalid_phase_do_not_change_state(self):
        state = self.bound(); diagnostic = state.as_dict()
        with self.assertRaisesRegex(EdltError, 'unavailable'):
            self.editor.commit_application(state, field='primary', address=57)
        self.assertEqual(state.as_dict(), diagnostic)
        loaded = self.editor.load(self.source, cache=self.cache)
        with self.assertRaises(EdltError): self.editor.commit_application(loaded, field='primary', address=136)
        with self.assertRaises(EdltError): self.editor.bind_global_applications(loaded)
        with self.assertRaises(EdltError): self.editor.prepare_applications(state)
        with self.assertRaises(EdltError): self.editor.bind_global_applications(state)
        state = self.editor.validate_bound_controls(state)
        with self.assertRaises(EdltError): self.editor.validate_bound_controls(state)
        with self.assertRaisesRegex(EdltError, 'terminal'):
            self.editor.commit_application(state, field='primary', address=136)

    def test_unknown_post_edit_group_is_not_treated_as_absent(self):
        facts = replace(self.cache.lifecycle, groups=tuple(g for g in self.cache.lifecycle.groups
                                                        if g.application != 136))
        partial = replace(self.cache, lifecycle=facts,
                          group_lists=tuple(row for row in self.cache.group_lists if row.application != 136))
        state = self.editor.bind_global_applications(self.editor.prepare_applications(
            self.editor.load(self.source, cache=partial)))
        state = self.editor.commit_application(state, field='secondary', address=255)
        with self.assertRaises(LifecycleMetadataError) as caught:
            self.editor.commit_application(state, field='primary', address=136)
        self.assertEqual(caught.exception.fact, {'application': 136, 'group': 7, 'widget': 6})
        self.assertEqual(state.values['PrimaryApplication'], (56,))

    def test_issued_state_is_immutable_and_replacements_are_rejected(self):
        state = self.bound()
        with self.assertRaises(TypeError): state.values['PrimaryApplication'] = (136,)
        with self.assertRaises(FrozenInstanceError): state.bound = False
        with self.assertRaises(EdltError): self.editor.validate_bound_controls(replace(state, bound=False))
        with self.assertRaises(EdltError): EdltApplications(fixture()).validate_bound_controls(state)
        with self.assertRaises(EdltError): self.editor.validate_bound_controls(state.as_dict())

    def test_typed_actions_and_sequence_bound(self):
        for field, address in (('bad', 56), ('primary', True), ('secondary', 256), ('primary', '56')):
            with self.assertRaises(EdltError): ApplicationEdit(field, address)
        with self.assertRaises(EdltError): ApplicationEdit.from_dict({'field': 'primary', 'address': 56, 'extra': 1})
        self.assertEqual(ApplicationEdit.from_dict({'field': 'primary', 'address': 56}).as_dict(),
                         {'field': 'primary', 'address': 56})
        state = self.bound()
        for _ in range(64): state = self.editor.commit_application(state, field='primary', address=56)
        with self.assertRaises(EdltError): self.editor.commit_application(state, field='primary', address=56)

    def test_save_projection_preserves_forcing_and_cached_scene_references(self):
        from tests.test_edlt_lifecycle import scene_values
        source = {**self.source, 'Widget6WidgetType': (16,), 'Widget6WidgetByteValue1': (134,),
            'Widget6WidgetByteValue10': (93,), **scene_values((3, 1, 42, 2, 26), ((17, 12, 123),))}
        state = self.editor.bind_global_applications(self.editor.prepare_applications(
            self.editor.load(source, cache=cache_for(self.editor, source))))
        original_reference = state.loaded.scenes[0].items[0].group
        state = self.editor.commit_application(state, field='secondary', address=255)
        state = self.editor.validate_bound_controls(state)
        with patch.object(self.editor.lifecycle, 'load', side_effect=AssertionError('second load')):
            plan = self.editor.prepare_save(state)
        self.assertEqual(plan.before_save['Widget6WidgetByteValue1'], (5,))
        self.assertEqual(plan.before_save['Widget6WidgetByteValue10'], (0,))
        self.assertEqual(plan.before_save['SceneBucket'][:8], (3, 1, 42, 2, 26, 17, 12, 123))
        self.assertEqual(original_reference.application, 57)
        self.assertIs(state.loaded.scenes[0].items[0].group, original_reference)
        self.assertEqual(plan.before_save['Application'], (56, 255))

    def test_apply_replay_staleness_full_readback_and_rollback(self):
        session = Session(fixture()); session.current = dict(self.source)
        plan = self.editor.plan(self.source, cache=self.cache, edits=[{'field': 'secondary', 'address': 255}])
        changed = {**plan.changes, 'PrimaryApplication': (136,)}
        with self.assertRaisesRegex(EdltError, 'canonical'): self.editor.apply(session, replace(plan, changes=changed))
        self.assertFalse(session.calls)
        session.current['Widget6RestoreLevel'] = (17,)
        with self.assertRaisesRegex(EdltError, 'changed since'): self.editor.apply(session, plan)
        self.assertFalse(session.calls)
        session.current = dict(self.source); session.failure = next(iter(plan.changes))
        with self.assertRaises(ApplicationApplyError) as caught: self.editor.apply(session, plan)
        self.assertTrue(caught.exception.details['rollback_verified'])
        self.assertEqual(self.editor.snapshot(session.values()), self.source)
        self.assertTrue(self.editor.apply(session, plan)['verified'])
        self.assertEqual(self.editor.snapshot(session.values()), {**plan.expected, **plan.changes})

    def test_disconnection_and_rollback_interrupt_never_trigger_recovery_io(self):
        class Unprintable(RuntimeError):
            def __str__(self): raise SystemExit('rendering must not replace primary evidence')
        plan = self.editor.plan(self.source, cache=self.cache, edits=[ApplicationEdit('secondary', 255)])
        session = Session(fixture()); session.current = dict(self.source); calls = []
        def disconnect(name, value):
            calls.append(name); session.programmer.client.connected = False; raise Unprintable()
        session.set = disconnect
        with self.assertRaises(ApplicationApplyError) as caught: self.editor.apply(session, plan)
        self.assertEqual(len(calls), 1); self.assertFalse(caught.exception.details['rollback_verified'])
        self.assertEqual(caught.exception.details['error'], '<unprintable Unprintable>')
        session.programmer.client.connected = True; calls.clear(); interrupted = KeyboardInterrupt('owned interrupt')
        def fail_then_interrupt(name, value):
            calls.append(name)
            if len(calls) == 1: raise Unprintable()
            raise interrupted
        session.set = fail_then_interrupt
        with self.assertRaises(KeyboardInterrupt) as caught: self.editor.apply(session, plan)
        self.assertIs(caught.exception, interrupted); self.assertEqual(len(calls), 2)
        self.assertEqual(interrupted.edlt_applications_evidence['original_error']['error'], '<unprintable Unprintable>')
        self.assertTrue(interrupted.edlt_applications_evidence['pp_state_uncertain'])

    def test_interruption_evidence_failure_preserves_first_interrupt(self):
        session = Session(fixture()); session.current = dict(self.source)
        plan = self.editor.plan(self.source, cache=self.cache, edits=[ApplicationEdit('secondary', 255)])
        interrupted = KeyboardInterrupt('first owned interrupt'); failed = False; calls = []
        export = ApplicationsPlan.as_dict
        def render(plan):
            if failed: raise SystemExit('secondary export failure')
            return export(plan)
        def fail(name, value):
            nonlocal failed
            calls.append(name); failed = True; raise interrupted
        session.set = fail
        with patch.object(ApplicationsPlan, 'as_dict', render):
            with self.assertRaises(KeyboardInterrupt) as caught: self.editor.apply(session, plan)
        self.assertIs(caught.exception, interrupted); self.assertEqual(len(calls), 1)
        self.assertFalse(interrupted.edlt_applications_evidence['evidence_export_complete'])
        self.assertTrue(interrupted.edlt_applications_evidence['pp_state_uncertain'])

    def test_cleanup_evidence_survives_application_wrapper(self):
        session = Session(fixture()); session.current = dict(self.source)
        plan = self.editor.plan(self.source, cache=self.cache, edits=[ApplicationEdit('secondary', 255)])
        primary = RuntimeError('primary failure'); primary.cgate_cleanup_errors = [{'operation': 'close', 'error': 'owned cleanup failure'}]
        first = True; setter = session.set
        def fail_once(name, value):
            nonlocal first
            setter(name, value)
            if first: first = False; raise primary
        session.set = fail_once
        with self.assertRaises(ApplicationApplyError) as caught: self.editor.apply(session, plan)
        self.assertIs(caught.exception.cause, primary)
        self.assertEqual(caught.exception.cgate_cleanup_errors, primary.cgate_cleanup_errors)
        self.assertEqual(caught.exception.edlt_applications_evidence['cgate_cleanup_errors'], primary.cgate_cleanup_errors)


@unittest.skipUnless(os.environ.get('CBUS_UNITSPEC_DIR'), 'Set exact vendor specification for original application vectors')
class ApplicationWindowsVectorTests(unittest.TestCase):
    def test_canonical_original_scenes_mra_forcing_and_terminal_save(self):
        path = ROOT / 'research/fixtures/edlt-application-terminal-vectors.json'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         '55e1a618054602361466d5d61145c5a26e4185ea01ed56991e88c0237182d54e')
        document = json.loads(path.read_text()); self.assertEqual(len(document['vectors']), 40)
        editor = EdltApplications(UnitSpecStore(Path(os.environ['CBUS_UNITSPEC_DIR'])).load('KEYGL5.xml'))
        snapshots = 0; rejected = 0
        for row in document['vectors']:
            with self.subTest(case=row['case']):
                source = {**document['baseline'], **row['initial']}
                cache = captured_cache(document, row); action = row['input_case']['action']
                actions = action['steps'] if action['kind'] == 'sequence' else [action]
                edits = [ApplicationEdit(item['field'], item['value']) for item in actions if item['kind'] != 'bind-only']
                obs = observations(document, row)
                if any(item['kind'] == 'action-unavailable' for item in obs):
                    with self.assertRaisesRegex(EdltError, 'unavailable'): editor.plan(source, cache=cache, edits=edits)
                    rejected += 1; continue
                plan = editor.plan(source, cache=cache, edits=edits)
                for stage, actual in (('after-original-load', plan.after_load), ('validation', plan.after_controls),
                    ('original-save', plan.before_save), ('crc', {**plan.expected, **plan.changes})):
                    expected = editor.snapshot({**source, **row['phases'][stage]})
                    self.assertEqual(len(expected), 874)
                    self.assertEqual({name: (actual[name], value) for name, value in expected.items()
                                      if actual[name] != value}, {}, stage)
                    snapshots += 1
                # Observe retained scalars/references without triggering a
                # scene selection, group lookup or re-resolution on new apps.
                actual_scenes = plan.as_dict()['control_state']['scene_objects']
                original_scenes = [item['value'] for item in obs
                                   if item['stage'] == 'validation' and item['kind'] == 'scene-object']
                self.assertEqual(len(original_scenes), 8)
                for actual, expected in zip(actual_scenes, original_scenes):
                    text = str(actual['slot']) + '|variant=' + str(actual['primary_secondary'])
                    text += '|trigger=' + str(actual['trigger_group']) + '|action=' + str(actual['stored_action_selector'])
                    text += '|name=' + str(actual['name_index']) + '|items=' + ','.join(
                        str(item['group_reference']['application']) + '/' + str(item['group_reference']['group'])
                        for item in actual['items'])
                    self.assertEqual(text, expected)
        self.assertEqual((snapshots, rejected), (156, 1))

    def test_all_selected_global_ui_phases_and_explicit_exclusions(self):
        path = ROOT / 'research/fixtures/edlt-application-observations.json'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), CAPTURE_SHA)
        document = json.loads(path.read_text()); self.assertEqual(len(document['vectors']), 435)
        editor = EdltApplications(UnitSpecStore(Path(os.environ['CBUS_UNITSPEC_DIR'])).load('KEYGL5.xml'))
        counts = {'cases': 0, 'snapshots': 0, 'unavailable': 0, 'excluded': 0}
        for row in document['vectors']:
            if row['mode'] not in ('model', 'global'): continue
            actions = row['input_case']['action']
            actions = actions['steps'] if actions['kind'] == 'sequence' else [actions]
            if any(action['kind'] not in ('bind-only', 'ui-commit') for action in actions): continue
            source = {**document['baseline'], **row['initial']}
            obs = observations(document, row)
            with self.subTest(mode=row['mode'], case=row['case']):
                if row['case'] in ('choices-duplicate-cache', 'choices-empty-cache', 'choices-missing-primary',
                    'choices-missing-secondary') or 'scene_variant' in row['input_case']['fixture']:
                    # Existing diagnostic SceneBucket has 256 raw values. A
                    # fresh canonical scene capture is required; never trim it.
                    with self.assertRaises(EdltError):
                        editor.prepare_applications(editor.load(source, cache=captured_cache(document, row)))
                    counts['excluded'] += 1; continue
                state = editor.load(source, cache=captured_cache(document, row))
                def check(stage, current):
                    expected = editor.snapshot({**source, **row['phases'][stage]})
                    self.assertEqual(dict(current.values), expected, stage); counts['snapshots'] += 1
                    if stage != 'after-original-load':
                        actual = current.as_dict()
                        for role in ('primary', 'secondary'):
                            lists = [x['value'] for x in obs if x['kind'] == 'list-' + role and x['stage'] == stage]
                            if lists:
                                self.assertEqual('|'.join(str(a['address']) + '=' + a['formatted_display']
                                    for a in actual['choices'][role]), lists[-1])
                check('after-original-load', state)
                state = editor.prepare_applications(state); check('populate-primsec', state)
                state = editor.bind_global_applications(state)
                if row['mode'] == 'global': check('after-bind', state)
                for index, action in enumerate(actions):
                    unavailable = any(x['kind'] == 'action-unavailable' and x['stage'] == 'action' + str(index) for x in obs)
                    if action['kind'] == 'ui-commit':
                        options = dict(field=action['field'], address=action['value'])
                        if unavailable:
                            with self.assertRaisesRegex(EdltError, 'unavailable'): editor.commit_application(state, **options)
                            counts['unavailable'] += 1
                        else: state = editor.commit_application(state, **options)
                    check('action' + str(index), state); check('action' + str(index) + '-event-pump', state)
                    if unavailable: break
                state = editor.validate_bound_controls(state); check('validation', state)
                wrapper_events = sum(x['kind'] == 'wrapper-event' and x['stage'].startswith('action') for x in obs)
                self.assertEqual(state.wrapper_change_count, wrapper_events)
                counts['cases'] += 1
        self.assertEqual(counts, {'cases': 210, 'snapshots': 1167, 'unavailable': 18, 'excluded': 16})
        print('Application phase comparisons: ' + json.dumps(counts, sort_keys=True))


if __name__ == '__main__': unittest.main()
