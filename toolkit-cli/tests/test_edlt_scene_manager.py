"""Retained SceneManager state, literal original validation, native full PP save."""
from dataclasses import replace
import base64
import hashlib
import json
import os
from pathlib import Path
import unittest
from uuid import uuid4

from cbus_toolkit.edlt import EdltError, EdltApplyError
from cbus_toolkit.edlt_scene_manager import EdltSceneManager, SceneManagerCache
from cbus_toolkit.unitspec import UnitSpecStore
from tests.test_edlt_lifecycle import fixture
from tests.test_edlt import Session

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / 'research/fixtures/edlt-scene-manager-vectors.json'


def vectors(): return json.loads(VECTORS.read_text())


def cache():
    applications = [56, 57, 172, 202, 203, 255]; groups = [255, *range(70), 254]; levels = [0, 1, 2, 3, 4, 5, 6, 7, 42, 254, 255]
    def display(n, name): return {'address': n, 'name': name, 'formatted_display': name}
    return {'format': 'cbus-edlt-scene-manager-cache-v1', 'application_cache': {
        'format': 'cbus-edlt-application-cache-v1', 'applications_complete': True,
        'applications': [display(a, 'Owned application ' + str(a)) for a in applications],
        'lifecycle': {'format': 'cbus-edlt-lifecycle-cache-v1', 'applications': applications, 'groups': [
            {'application': a, 'group': g, 'exists': True, 'dynamic_images': [False] * 4, 'levels': levels}
            for a in applications for g in groups]},
        'group_lists': [{'application': a, 'complete': True, 'groups': [display(g, 'Owned ' + str(a) + '/' + str(g)) for g in groups]} for a in applications]},
        'level_labels': [{'group': g, 'action': level, 'labels': [{'value': str(n), 'name': 'Owned action ' + str(level), 'image_present': False} for n in range(4)]}
                         for g in groups for level in levels]}


def op(name, scene=1, **values): return dict(op=name, scene=scene, **values)


def operations(name):
    rows = {
        'baseline': [], 'add-remove': [op('add-groups', groups=[7]), op('remove-items', item_ids=[1])],
        'cross-application': [op('set-application', selector=1), op('add-groups', groups=[12]), op('set-application', selector=0)],
        'copy-paste': [op('copy'), op('set-level', item_id=1, level=51), op('set-name-index', index=28), op('paste', 3)],
        'clear-items': [op('clear-items')], 'clear-scene': [op('clear-scene')],
        'level-percent': [op('set-percent', item_id=1, percent=100)], 'ramp': [op('set-ramp', item_id=1, ramp_rate=15)],
        'sync': [op('set-percent', item_id=1, percent=50), op('sync-levels', item_id=1)],
        'validate-valid': [], 'validate-trigger-duplicate': [op('set-action', 2, action=1)],
        'validate-name-duplicate': [op('set-name-index', 2, index=26)],
        'validate-missing-trigger': [op('set-trigger', group=255)],
        'validate-missing-action': [op('set-action', action=99)], 'validate-missing-name': [op('set-name-index', index=255)],
        'validate-all-four': [op('set-action', 2, action=1), op('set-name-index', 2, index=26), op('add-groups', 3, groups=[1])],
        'validate-shortcut-first': [op('set-trigger', group=255), op('set-name-index', index=255),
            op('set-trigger', 3, group=42), op('set-action', 3, action=2), op('set-name-index', 3, index=27)],
        'validate-shortcut-second': [op('set-name-index', index=255), op('set-trigger', 2, group=255),
            *[v for s in (3, 4) for v in (op('set-trigger', s, group=42), op('set-action', s, action=3), op('set-name-index', s, index=28))]],
        'validate-empty-duplicates': [op('clear-items'), op('clear-items', 2), op('set-action', 2, action=1), op('set-name-index', 2, index=26)],
        'validate-action255': [op('set-action', action=255), op('set-action', 2, action=255)],
        'validate-missing-action-duplicate': [op('set-action', action=99), op('set-action', 2, action=99)],
        'validate-all-empty': [op('clear-scene', s) for s in range(1, 9)],
        'get-new-missing-trigger': [op('set-trigger', group=99), op('get-trigger'), op('get-action')],
        'get-set-action-valid': [op('set-action', action=2), op('get-trigger'), op('get-action')],
        'get-set-action-missing': [op('set-action', action=99), op('get-trigger'), op('get-action')],
        'get-disabled-trigger': [op('set-trigger', group=255), op('set-action', action=2), op('get-trigger'), op('get-action')],
    }
    if name == 'capacity-add': return [op('clear-items', s) for s in range(1, 9)] + [op('add-groups', groups=list(range(63))), op('add-groups', 2, groups=[63, 64])]
    if name == 'capacity-paste': return [op('clear-items', s) for s in range(1, 9)] + [op('add-groups', groups=list(range(4))), op('add-groups', 2, groups=list(range(59))), op('copy'), op('paste', 3)]
    return rows[name]


def check_scenes(test, state, expected):
    for s in state.scenes:
        actual = expected['scenes'][str(s.slot)]
        test.assertEqual((s.primary_secondary, s.can_edit, s.raw_trigger, s.raw_action, s.name_index, s.label_value_index, len(s.dynamic_labels)),
            tuple(actual[k] for k in ('variant', 'editable', 'trigger', 'action', 'name', 'label', 'dynamic_count')), 'scene ' + str(s.slot))
        test.assertEqual([(v.group.application, v.group.group, v.level, v.ramp_rate, v.can_edit) for v in s.items],
            [tuple(v[k] for k in ('app', 'group', 'level', 'ramp', 'editable')) for v in expected['items'].get(str(s.slot), [])])
        if expected['dynamic'].get(str(s.slot)) is not None:
            test.assertEqual([v.as_dict() for v in s.dynamic_labels], expected['dynamic'][str(s.slot)])


class SceneManagerTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture(); self.editor = EdltSceneManager(self.spec); self.session = Session(self.spec)
        self.source = {**self.session.current, **{k: v for k, v in vectors()['input'].items() if k in self.spec.parameters}}
        self.session.current = dict(self.source); self.state = self.editor.load(self.source, metadata=cache())

    def test_original_retained_model_operations_and_private_fields(self):
        data = vectors()
        check_scenes(self, self.state, data['cases']['model-baseline']['stages']['after-original-load'])
        for name in ('baseline', 'add-remove', 'cross-application', 'copy-paste', 'clear-items', 'clear-scene', 'level-percent', 'ramp'):
            with self.subTest(name=name):
                outcome = self.editor.edit(self.state, operations=operations(name)); self.assertTrue(outcome.complete)
                plan = self.editor.prepare_save(outcome.state)
                check_scenes(self, plan.terminal, data['cases']['model-' + name]['stages']['after-original-crc'])
                literal = {**data['input'], **data['cases']['model-' + name]['pp_delta']}
                expected = self.editor.snapshot({**self.source, **{k: v for k, v in literal.items() if k in self.spec.parameters}})
                self.assertEqual(plan.before_save['SceneBucket'], expected['SceneBucket'])
                self.assertEqual(dict(self.state.loaded.after_load), dict(outcome.state.loaded.after_load))
                self.assertFalse(plan.as_dict()['full_form_validation_verified'])

    def test_original_validation_four_flags_and_shortcut(self):
        data = vectors()
        for name in [n.removeprefix('model-') for n in data['cases'] if n.startswith('model-validate')]:
            with self.subTest(name=name):
                edited = self.editor.edit(self.state, operations=operations(name)).state
                validation = self.editor.validate(edited)
                original = data['cases']['model-' + name]
                check_scenes(self, validation.state, original['stages']['original-validation'])
                self.assertEqual(validation.valid, original['validation']['original-validation']['valid'])
                phrases = {'duplicate-trigger-action': 'identical Trigger Group', 'populated-missing-trigger-action': 'not been assigned a Trigger Group',
                           'populated-missing-name': 'not been assigned a scene label', 'duplicate-name': 'identical scene labels'}
                message = original['validation']['original-validation']['message']
                self.assertEqual(set(validation.warnings), {k for k, phrase in phrases.items() if phrase in message})
                plan = self.editor.prepare_save(validation.state)
                check_scenes(self, plan.terminal, original['stages']['after-original-crc'])
                self.assertFalse(plan.as_dict()['validation']['save_blocking'])
        first = self.editor.validate(self.editor.edit(self.state, operations=operations('validate-shortcut-first')).state)
        self.assertEqual(first.skipped_slots, (2, 3, 4, 5, 6, 7, 8))

    def test_missing_getters_mutate_only_original_fields_and_no_cache_creation(self):
        for name in ('get-new-missing-trigger', 'get-set-action-valid', 'get-set-action-missing', 'get-disabled-trigger'):
            with self.subTest(name=name):
                state = self.editor.edit(self.state, operations=operations(name)).state
                observed = vectors()['cases']['model-' + name]
                check_scenes(self, state, observed['stages']['action-getter'])
                plan = self.editor.prepare_save(self.editor.validate(state).state)
                check_scenes(self, plan.terminal, observed['stages']['after-original-crc'])
        disabled = self.editor.edit(self.state, operations=[op('set-trigger', group=255), op('set-action', action=2)]).state.scenes[0]
        self.assertEqual(disabled.raw_action, 1); self.assertIs(disabled.dynamic_labels, self.state.scenes[0].dynamic_labels)

    def test_cross_application_identity_and_copy_asymmetry(self):
        switched = self.editor.edit(self.state, operations=[op('set-application', selector=1)]).state
        self.assertIn(12, [v.address for v in self.editor.available_groups(switched, scene=1)])
        added = self.editor.edit(switched, operations=[op('add-groups', groups=[12])]).state
        self.assertIs(added.scenes[0].items[0].group, self.state.scenes[0].items[0].group)
        self.assertIsNot(added.scenes[0].items[-1].group, added.scenes[0].items[0].group)
        self.assertEqual([i.group.group for i in added.scenes[0].items], [12, 42, 12])
        copied = self.editor.edit(self.state, operations=[op('copy'), op('paste', 2)]).state
        self.assertIs(copied.scenes[1].dynamic_labels, self.state.scenes[1].dynamic_labels)
        self.assertIs(copied.scenes[1].items[0].group, self.state.scenes[0].items[0].group)
        self.assertTrue(copied.scenes[1].items[0].can_edit); self.assertFalse(self.state.scenes[0].items[0].can_edit)
        self.assertNotEqual(copied.scenes[1].items[0].item_id, self.state.scenes[0].items[0].item_id)
        cleared = self.editor.edit(self.state, operations=[op('clear-scene')]).state
        self.assertIs(cleared.scenes[0].dynamic_labels, self.state.scenes[0].dynamic_labels)

    def test_capacity_partial_prefix_is_reviewable_and_never_persistable(self):
        for name, counts in (('capacity-add', (63, 1, 0)), ('capacity-paste', (4, 59, 1))):
            with self.subTest(name=name):
                outcome = self.editor.edit(self.state, operations=operations(name)); self.assertFalse(outcome.complete)
                self.assertEqual(tuple(len(s.items) for s in outcome.state.scenes[:3]), counts)
                check_scenes(self, outcome.state, vectors()['cases']['model-' + name]['stages']['ordered-add-until-full' if name == 'capacity-add' else 'partial-paste-empty'])
                self.assertEqual(outcome.state.as_dict()['storage_used_percent'], 100)
                self.assertEqual(json.loads(outcome.operation_results[-1])['applied_count'], 1)
                with self.assertRaisesRegex(EdltError, 'incomplete'): self.editor.prepare_save(outcome.state)
                with self.assertRaisesRegex(EdltError, 'review-only'): self.editor.edit(outcome.state, operations=[])
        complete = self.editor.edit(self.state, operations=operations('capacity-add')[:-1] + [op('add-groups', 2, groups=[63])])
        self.assertTrue(complete.complete); self.assertEqual(len(self.editor.prepare_save(complete.state).before_save['SceneBucket']), 232)

    def test_bounds_unknown_facts_and_issued_object_guards(self):
        invalid = [op('set-level', item_id=1, level=True), op('set-level', item_id=1, level=256), op('set-percent', item_id=1, percent=101),
            op('set-ramp', item_id=1, ramp_rate=16), op('set-name-index', index=64), op('set-name-index', index=254), op('copy', 0),
            op('add-groups', groups=[12]), op('add-groups', groups=[7, 7]), op('add-groups', groups=[255]), op('remove-items', item_ids=[999]),
            op('set-level', item_id=3, level=1), op('paste'), {'op':'copy','scene':1,'extra':0}]
        for operation in invalid:
            with self.subTest(op=operation), self.assertRaises(EdltError): self.editor.edit(self.state, operations=[operation])
        for fake in (replace(self.state), replace(self.state, complete=False), self.state.as_dict()):
            with self.assertRaises(EdltError): self.editor.prepare_save(fake)
        with self.assertRaises(EdltError): EdltSceneManager(self.spec).prepare_save(self.state)
        with self.assertRaises(EdltError): self.editor.load(self.source, metadata=cache(), scope='control')
        unknown = cache(); unknown['level_labels'] = []
        with self.assertRaisesRegex(EdltError, 'DynamicAll'): self.editor.load(self.source, metadata=unknown)
        unknown = cache(); unknown['application_cache']['group_lists'] = []
        state = self.editor.load(self.source, metadata=unknown)
        with self.assertRaisesRegex(EdltError, 'group list'): self.editor.available_groups(state, scene=1)
        with self.assertRaises(EdltError): self.editor.load(self.source, metadata={**cache(), 'extra': 1})
        self.assertFalse(self.session.calls)

    def test_apply_guards_rollback_interrupt_and_disconnection(self):
        plan = self.editor.prepare_save(self.editor.edit(self.state, operations=[op('set-level', item_id=1, level=77)]).state)
        with self.assertRaises(EdltError): self.editor.apply(self.session, replace(plan, changes={}))
        self.session.identity['FirmwareVersion'] = '5.4.00'
        with self.assertRaises(EdltError): self.editor.apply(self.session, plan)
        self.session.identity['FirmwareVersion'] = '5.5.00'; self.session.current['PrimaryApplication'] = (57,)
        with self.assertRaises(EdltError): self.editor.apply(self.session, plan)
        self.assertFalse(self.session.calls); self.session.current = dict(self.source)
        self.session.failure = 'SceneBucket'
        with self.assertRaises(EdltApplyError) as caught: self.editor.apply(self.session, plan)
        self.assertTrue(caught.exception.details['rollback_verified'])
        self.assertIs(caught.exception.edlt_scene_manager_evidence, self.editor.last_evidence)
        self.assertTrue(self.editor.last_evidence['rollback_verified'])
        self.assertEqual(self.editor.snapshot(self.session.values()), self.editor.snapshot(self.source))
        for error in (KeyboardInterrupt(), SystemExit(3), ConnectionError('lost')):
            session = Session(self.spec); session.current = dict(self.source); calls = []
            def fail(name, value):
                calls.append(name); session.current[name] = value; session.connected = False; raise error
            session.set = fail
            with self.subTest(error=type(error).__name__), self.assertRaises(type(error) if not isinstance(error, Exception) else EdltApplyError) as caught:
                self.editor.apply(session, plan)
            self.assertEqual(len(calls), 1)
            if isinstance(error, Exception): self.assertFalse(caught.exception.details['rollback_verified'])
            else: self.assertEqual(error.edlt_scene_manager_evidence['attempted_parameters'], calls)
        self.assertFalse(plan.as_dict()['saved'])

    def test_readback_mismatch_rolls_back_and_numeric_endpoints(self):
        for percent, expected in ((0,0), (1,2), (50,127), (99,252), (100,255)):
            state = self.editor.edit(self.state, operations=[op('set-percent', item_id=1, percent=percent)]).state
            self.assertEqual(state.scenes[0].items[0].level, expected)
        for level, expected in ((0,0), (1,1), (253,100), (255,100)):
            state = self.editor.edit(self.state, operations=[op('set-level', item_id=1, level=level)]).state
            self.assertEqual(state.scenes[0].items[0].as_dict()['percent'], expected)
        plan = self.editor.prepare_save(self.state); count = 0; original_values = self.session.values
        def corrupt_read():
            nonlocal count
            count += 1; values = original_values()
            if count == 2: values['SceneCount'] = (7,)
            return values
        self.session.values = corrupt_read
        with self.assertRaises(EdltApplyError) as caught: self.editor.apply(self.session, plan)
        self.assertIn('readback differs', str(caught.exception.cause))
        self.assertTrue(caught.exception.details['rollback_verified'])
        self.assertEqual(self.editor.snapshot(original_values()), self.editor.snapshot(self.source))

    def test_interruption_rejected_evidence_setattr_export_failure_and_stale_reuse(self):
        from unittest.mock import patch
        from cbus_toolkit.edlt_scene_manager import SceneManagerPlan
        class RefusingInterrupt(KeyboardInterrupt):
            def __setattr__(self, key, value):
                if key == 'edlt_scene_manager_evidence': raise SystemExit('secondary attachment failure')
                super().__setattr__(key, value)
        plan = self.editor.prepare_save(self.state)
        interrupted = RefusingInterrupt('first interrupt'); calls = []
        def fail(name, value):
            calls.append(name); self.session.current[name] = value
            raise interrupted
        self.session.set = fail
        with self.assertRaises(RefusingInterrupt) as caught: self.editor.apply(self.session, plan)
        self.assertIs(caught.exception, interrupted); self.assertEqual(self.editor.last_evidence['attempted_parameters'], calls)
        self.assertFalse(self.editor.last_evidence['saved'])
        with self.assertRaises(EdltError): self.editor.apply(self.session, replace(plan))
        self.assertIsNone(self.editor.last_evidence)
        with patch.object(SceneManagerPlan, 'as_dict', side_effect=SystemExit('secondary export failure')):
            self.editor._interrupted(interrupted, plan, ['SceneBucket'])
        self.assertFalse(self.editor.last_evidence['evidence_export_complete'])
        self.assertEqual(self.editor.last_evidence['attempted_parameters'], ['SceneBucket'])
        original = RuntimeError('original SET failure'); session = Session(self.spec); session.current = dict(self.source); calls = []
        def rollback_fail(name, value):
            calls.append(name)
            if len(calls) == 1: session.current[name] = value; raise original
            raise interrupted
        session.set = rollback_fail
        with self.assertRaises(RefusingInterrupt) as caught: self.editor.apply(session, plan)
        self.assertIs(caught.exception, interrupted); self.assertEqual(len(calls), 2)
        self.assertEqual(self.editor.last_evidence['original_error']['error'], 'original SET failure')
        self.assertEqual(self.editor.last_evidence['rollback_errors'], [])



@unittest.skipUnless(all(os.environ.get(k) for k in ('CBUS_UNITSPEC_DIR', 'CBUS_CGATE_TEST_HOST')), 'Set native C-Gate and exact unit specs')
class NativeSceneManagerTests(unittest.TestCase):
    def test_original_full874_raw_crc_save_close_load_and_metadata_preservation(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.programming import Programmer, xml_text
        spec = UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR']).load('KEYGL5.xml'); editor = EdltSceneManager(spec)
        source_values = editor.snapshot(vectors()['input']); project = 'SM' + uuid4().hex[:6].upper(); network = '//' + project + '/254'; source = '/db' + network + '/p/20'
        records = []
        from xml.etree import ElementTree as ET
        def metadata(reply):
            root = ET.fromstring(xml_text(reply))
            for parent in root.iter():
                for node in list(parent):
                    if node.tag == 'PP': parent.remove(node)
            return ET.tostring(root, encoding='unicode')
        with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')), timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client); projects.operation('new', project); projects.operation('save', project)
            try:
                database.create_network(project, 254, 'SceneManagerFixture', 'Cni', '127.0.0.1:1')
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                with Programmer(client).load(network, source) as session:
                    for field, value in source_values.items(): session.set(field, value if isinstance(value, str) else ' '.join(map(str, value)))
                    session.save_to_source()
                for action in ('save','close','load'): projects.operation(action, project)
                before_metadata = metadata(database.get(network, xml=True))
                for name in ('baseline', 'add-remove', 'cross-application', 'copy-paste', 'clear-scene', 'validate-all-four', 'get-new-missing-trigger', 'capacity-add'):
                    with Programmer(client).load(network, source) as session:
                        current = editor.snapshot(session.values())
                        for field, value in source_values.items():
                            if current[field] != value: session.set(field, value if isinstance(value, str) else ' '.join(map(str, value)))
                        ops = operations(name)
                        if name == 'capacity-add': ops = ops[:-1] + [op('add-groups', 2, groups=[63])]
                        state = editor.edit(editor.load(session.values(), metadata=cache()), operations=ops).state
                        if name.startswith('validate-') or name.startswith('get-'): state = editor.validate(state).state
                        plan = editor.prepare_save(state); expected = {**plan.expected, **plan.changes}
                        original = {**vectors()['input'], **vectors()['cases']['model-' + name]['pp_delta']}
                        if name == 'capacity-add':
                            tokens = original['SceneBucket'].split(); self.assertEqual(len(tokens), 233); self.assertEqual(tokens[-1], '0xff')
                            original['SceneBucket'] = ' '.join(tokens[:232])
                        literal = editor.snapshot(original)
                        if name == 'capacity-add':
                            session.set('SceneBucket', vectors()['cases']['model-capacity-add']['pp_delta']['SceneBucket'])
                            self.assertEqual(editor.snapshot(session.values())['SceneBucket'], literal['SceneBucket'])
                            session.set('SceneBucket', ' '.join(map(str, plan.expected['SceneBucket'])))
                        self.assertEqual({k: (literal[k], expected[k]) for k in expected if literal[k] != expected[k]}, {}, name)
                        self.assertEqual(len(expected), 874); self.assertTrue(editor.apply(session, plan)['verified'])
                        raw = bytes.fromhex(session.get_raw_data(0x2112, 232).lines[-1].split('RawData=')[1])
                        self.assertEqual(raw, bytes(expected['SceneBucket']))
                        crc = bytes.fromhex(session.get_raw_data(0x102, 10).lines[-1].split('RawData=')[1])
                        self.assertEqual(crc, bytes(sum((expected[k] for k in ('OverallCRC','GlobalParameterCRC','WidgetsCRC','StaticTextCRC','ScenesCheckSum')), ())))
                        session.save_to_source()
                    for action in ('save','close','load'): projects.operation(action, project)
                    with Programmer(client).load(network, source) as session: self.assertEqual(editor.snapshot(session.values()), expected)
                    self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                    self.assertEqual(metadata(database.get(network, xml=True)), before_metadata)
                    records.append({'metadata_unchanged': True, 'case': name, 'parameters': 874, 'crcs': list(crc), 'scene_bucket_sha256': hashlib.sha256(raw).hexdigest(), 'saved_closed_reloaded': True})
            finally:
                projects.operation('close', project); projects.operation('delete', project)
        output = Path(os.environ.get('CBUS_EDLT_SCENE_MANAGER_REPORT', ROOT / 'research/runtime/edlt-scene-manager/native-report.json'))
        output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps({'passed': True, 'cases': records, 'physical_device_verified': False}, indent=2) + '\n')


@unittest.skipUnless(all(os.environ.get(k) for k in ('CBUS_TOOLKIT_EXE','CBUS_UNITSPEC_DIR')), 'Set original Toolkit and exact specs')
class OriginalSceneManagerTests(unittest.TestCase):
    def test_original_validation_and_retained_control_literals(self):
        from research.original_oracle import OriginalModelOracle
        source = ROOT / 'research/NativeEdltSceneManagerProbe.cs'; spec = Path(os.environ['CBUS_UNITSPEC_DIR']) / 'KEYGL5.xml'
        data = vectors(); values = ''.join(k + '\t' + v + '\n' for k, v in data['input'].items()).encode()
        records = []
        with OriginalModelOracle(source, Path(os.environ['CBUS_TOOLKIT_EXE']).parent, references=('eDLT.dll','SharpCGateCommunicator.dll'), gui=True, docker_image='sha256:23a8bfba16d732eff819f71edeec551e84e576eab40a15ec9e97018f649fb568') as oracle:
            for scope, name in [('model', n.removeprefix('model-')) for n in data['cases'] if n.startswith('model-validate')] + [('model','get-new-missing-trigger'), ('control','baseline'), ('control','sync'), ('control','copy-paste')]:
                result = oracle.run_result(('KEYGL5.xml','values.tsv',scope,name), files={'KEYGL5.xml':spec.read_bytes(),'values.tsv':values})
                self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr)
                self.assertIn('complete:true:', result.stdout); self.assertIn('peer-cleanup:accepted=0:bytes=0', result.stdout)
                phases = {}
                for line in result.stdout.splitlines():
                    if line.startswith('pp\t'):
                        _, stage, field, value, _ = line.split('\t'); phases.setdefault(stage,{})[field] = base64.b64decode(value).decode()
                self.assertTrue(all(len(v) == 874 for v in phases.values()))
                expected = {**data['input'], **data['cases'][scope+'-'+name]['pp_delta']}
                self.assertEqual(phases['after-original-crc'], expected)
                records.append({'scope':scope,'case':name,'stdout_sha256':hashlib.sha256(result.stdout.encode()).hexdigest(),'process_evidence':result.process_evidence})
        output = Path(os.environ.get('CBUS_EDLT_SCENE_MANAGER_ORIGINAL_REPORT',ROOT/'research/runtime/edlt-scene-manager/original-report.json'))
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps({'passed':True,'cases':records,'physical_device_verified':False},indent=2)+'\n')
