"""Independent selector source/literal oracles; no vendor instructions execute."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_scene_manager import EdltSceneManager
from tests.test_edlt import Session
from tests.test_edlt_lifecycle import fixture

ROOT = Path(__file__).resolve().parents[1]
ANNEX_PATH = ROOT / 'research/fixtures/edlt-scene-selector-source-annex.json'
VECTOR_PATH = ROOT / 'research/fixtures/edlt-scene-selector-vectors.json'
_spec = importlib.util.spec_from_file_location('edlt_scene_selector_static', ROOT / 'research/edlt_scene_selector_static.py')
static = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(static)
ANNEX = json.loads(ANNEX_PATH.read_text())
VECTORS = json.loads(VECTOR_PATH.read_text())


class SceneSelectorStaticEvidenceTests(unittest.TestCase):
    def test_all_managed_source_and_framework_declarations_are_bounded(self):
        methods = ANNEX['managed_method_spans']
        self.assertEqual(len(methods), 34)
        self.assertEqual({row['symbol'] for row in methods}, {name for names in static.METHODS.values() for name in names})
        self.assertEqual(len(ANNEX['decompiled_source_symbols']), 36)
        self.assertEqual(len(ANNEX['framework_api_declarations']), 7)
        for row in methods:
            with self.subTest(symbol=row['symbol']):
                self.assertEqual(row['metadata_runtime'], 'v4.0.30319')
                self.assertEqual(int(row['token'], 16) >> 24, 6)
                self.assertGreaterEqual(row['body_bytes'], row['header_bytes'] + row['code_bytes'])
                self.assertRegex(row['body_sha256'], r'^[0-9a-f]{64}$')
                self.assertRegex(row['il_sha256'], r'^[0-9a-f]{64}$')
                self.assertTrue(row['static_decode_only'])
                self.assertTrue(all(0 <= call['il_offset'] < row['code_bytes'] for call in row['calls']))
        self.assertEqual(len(ANNEX['static_checks']), 17)
        chains = {row['id']: row for row in ANNEX['static_checks']}
        self.assertTrue(all(row['passed'] for row in chains.values()))
        self.assertEqual(chains['trigger-current-getter-before-refresh']['ordered_call_suffixes'][-2:], ['get_ActionSelector', 'RefreshDynamicLables'])
        self.assertEqual(chains['levels-current-no-read']['absent_call_suffix'], 'ReadValue')
        self.assertEqual(chains['application-selector-values-and-secondary-gate']['integer_anchors'], [0,1,255])

    def test_framework_profile_proves_declarations_without_host_schedule(self):
        profile = ANNEX['framework_profile']
        self.assertEqual(profile['name'], 'net4-explicit-binding-declarations')
        self.assertEqual(profile['update_modes'], {'OnValidation':'0','OnPropertyChanged':'1','Never':'2'})
        self.assertEqual(profile['primary_repository_commit'], '44845c0667b7d737c1f8a4821ff6bc16e21912f8')
        for row in ANNEX['framework_api_declarations']:
            with self.subTest(member=row['member']):
                self.assertIn('4.0.0.0', row['assembly_versions'])
                self.assertRegex(row['sha256'], r'^[0-9a-f]{64}$')
                self.assertGreater(row['utf8_bytes'], 100)
        for field, value in ANNEX['limits'].items():
            self.assertEqual(value, 0 if field.endswith('instructions_executed') else False, field)
        self.assertIn('actual', ANNEX['source_contract']['trigger_list'])
        self.assertIn('retain', ANNEX['source_contract']['scene_current'])
        self.assertIn('no ReadValue', ANNEX['source_contract']['levels_current'])
        self.assertIn('createfalse', ANNEX['source_contract']['refresh'])

    def test_public_source_pins_have_no_vendor_bodies_or_private_coordinates(self):
        inputs = ANNEX['original_inputs']
        self.assertEqual(len(inputs), 16)
        self.assertEqual({row['path']:row['sha256'] for row in inputs if row['role']=='original-static-input'}, static.VENDOR_PINS)
        for row in inputs:
            self.assertFalse(row['path'].startswith('/'))
            self.assertNotIn('..', Path(row['path']).parts)
        for path in (ANNEX_PATH, VECTOR_PATH):
            for forbidden in ('/private/','/Volumes/','/Users/','il_hex','body_hex'):
                self.assertNotIn(forbidden, path.read_text())
        self.assertFalse(VECTORS['limits']['host_gui_executed'])
        self.assertEqual(VECTORS['limits']['new_original_instructions_executed'], 0)

    def test_expression_declarations_cannot_borrow_next_body(self):
        raw = b'public int Value => Items[0].Value;\npublic int Next\n{ get { return 1; } }\n'
        row = static.declaration_span(raw, 'Value', 'public int Value')
        self.assertEqual(row['sha256'], hashlib.sha256(b'public int Value => Items[0].Value;').hexdigest())
        self.assertEqual((row['start_line'], row['end_line']), (1,1))
        with self.assertRaises(ValueError): static.declaration_span(raw+raw, 'Value', 'public int Value')
        with self.assertRaises(ValueError): static.require_order(['RefreshDynamicLables','get_ActionSelector'], ['get_ActionSelector','RefreshDynamicLables'], 'getter-before-refresh')

    def test_static_pinned_regeneration(self):
        vendor = os.environ.get('CBUS_SCENE_SELECTOR_STATIC_VENDOR_ROOT')
        framework = os.environ.get('CBUS_SCENE_SELECTOR_STATIC_FRAMEWORK_ROOT')
        if not vendor or not framework:
            self.skipTest('Explicit private pinned SceneSelector vendor/primary declaration inputs are not configured')
        rendered = (json.dumps(static.recover(Path(vendor), Path(framework)), indent=2, ensure_ascii=False)+'\n').encode()
        self.assertEqual(rendered, ANNEX_PATH.read_bytes())


class SceneSelectorLiteralOracles(unittest.TestCase):
    @staticmethod
    def loaded(case=None):
        spec = fixture(); editor = EdltSceneManager(spec); session = Session(spec)
        values = {**session.current, **VECTORS['fixture']['consumer_pp_parameters']}
        cache = deepcopy(VECTORS['fixture']['cache'])
        override = None if case is None else case.get('cache_override')
        if override == 'explicit255':
            cache['trigger_list']['groups'].insert(0, {'address':255,'name':'Group 255','formatted_display':'255 - Group 255'})
        elif override == 'secondary-unused': values['SecondaryApplication'] = '0xff'
        elif override == 'missing-actions-42': cache['action_lists'] = [row for row in cache['action_lists'] if row['group']!=42]
        return editor, editor.load(values, metadata=cache), values

    def assert_scenes(self, editor, state, expected):
        self.assertEqual(len(state.scenes), 8)
        for actual, oracle in zip(state.scenes, expected):
            self.assertEqual((actual.slot,actual.primary_secondary,actual.can_edit,actual.raw_trigger,actual.raw_action,actual.name_index,actual.label_value_index),
                             tuple(oracle[k] for k in ('scene','application_selector','can_edit','raw_trigger','raw_action','name_index','label_value_index')))
            self.assertEqual([row.as_dict() for row in actual.dynamic_labels], oracle['dynamic_labels'])
            self.assertEqual(editor.scene_name(state, scene=actual.slot), oracle['name'])
            self.assertEqual(list(actual.items), oracle['items'])

    def test_literal_fixture_geometry_and_historical_baseline_stays_immutable(self):
        f = VECTORS['fixture']; pp = f['consumer_pp_parameters']
        self.assertEqual(len(pp),76); self.assertEqual(f['scene_count'],8)
        self.assertEqual(f['scene_starts'],[0,5,10,15,20,25,30,35])
        self.assertEqual(bytes.fromhex(f['scene_bucket_hex'])[:10],bytes([2,0,42,7,63,2,0,43,9,62]))
        self.assertEqual(bytes.fromhex(f['scene_bucket_hex'])[10:40],bytes([2,0,255,255,255])*6)
        self.assertEqual(bytes.fromhex(f['scene_bucket_hex'])[40:],b'\xff'*192)
        self.assertEqual(len(f['static_rows_hex']),64)
        for index,row in enumerate(f['static_rows_hex']):
            with self.subTest(row=index):
                self.assertEqual(len(bytes.fromhex(row)),64)
                self.assertEqual(bytes.fromhex(row),bytes(int(value,16) for value in pp['StaticTextString'+str(index)].split()))
        old = ROOT / 'research/fixtures/edlt-scene-manager-vectors.json'
        self.assertEqual(hashlib.sha256(old.read_bytes()).hexdigest(),VECTORS['oracle']['historical_baseline_sha256'])
        self.assertEqual(len(VECTORS['cases']),20); self.assertEqual(len(VECTORS['refusals']),8)
        for case in VECTORS['cases']:
            self.assertEqual(len(bytes.fromhex(case['expected_scene_bucket_hex'])),232)
            self.assertEqual(case['expected_static_rows_hex'],f['static_rows_hex'])
            for stage in ('callbacks','before_save','fresh_load'): self.assertEqual(len(case['expected_scenes_after_'+stage]),8)

    def test_initial_getter_source_lists_and_duplicate_object_identities(self):
        editor,state,_ = self.loaded(); observation = editor.selector_view(state,scene=1)
        view = observation.as_dict()['view']; source = VECTORS['fixture']['exact_source_choices']
        self.assertEqual(view['application_choices'],source['applications'])
        self.assertEqual(view['trigger_choices'],source['triggers'])
        self.assertEqual(view['action_choices'],source['actions_by_group']['42'])
        self.assertEqual(view['dynamic_labels'],source['dynamic_labels_by_level']['42/7'])
        self.assertEqual([row['value'] for row in view['trigger_choices']],[44,42,43,45])
        self.assertNotIn(255,[row['value'] for row in view['trigger_choices']])
        self.assertEqual(view['action_choices'][0]['name'],view['action_choices'][2]['name'])
        self.assertNotEqual(view['action_choices'][0]['identity'],view['action_choices'][2]['identity'])
        self.assertEqual(view['action_selector'],7); self.assertTrue(view['action_getter_observed'])
        self.assert_scenes(editor,observation.state,VECTORS['fixture']['all_eight_scenes'])

    def test_all_source_literal_property_and_callback_states(self):
        for case in VECTORS['cases']:
            with self.subTest(case=case['name']):
                editor,state,_ = self.loaded(case)
                outcome = editor.edit(state,operations=case['operations'])
                self.assert_scenes(editor,outcome.state,case['expected_scenes_after_callbacks'])
                journal = [row for result in outcome.operation_results
                           for row in json.loads(result).get('scene_selector_control',{}).get('binding_callbacks',[])]
                # This projection maps named runtime records to the independently
                # authored source concepts. It does not claim an extra executed
                # getter record for SetDynamicLabelDataSource's observed value.
                mapping = {
                    'ClearActionBindings':['action-bindings-clear'],
                    'ResolveAvailableActionSelectors':['available-actions-get'],
                    'SetActionDataSource':['action-data-source-set'],
                    'BindActionSelectedValue':['action-binding-add'],
                    'ClearDynamicLabelBindings':['label-bindings-clear'],
                    'SetDynamicLabelDataSource':['dynamic-labels-get','label-data-source-set'],
                    'BindLabelSelectedIndex':['label-binding-add'],
                    'ClearSceneNameBindings':['name-bindings-clear'],
                    'BindSceneNameText':['name-binding-add'],
                    'ActionSelectorGetterThenRefreshDynamicLables':['action-get'],
                    'RefreshDynamicLables':['dynamic-labels-refresh'],
                    'SetControlEnabled':[]}
                writes = {'application-selected':'application-binding-write',
                          'trigger-selected':'trigger-binding-write',
                          'action-selected':'action-binding-write',
                          'level-current-changed':'action-binding-write',
                          'label-selected':'label-binding-write'}
                projected = []
                for row in journal:
                    self.assertNotEqual(row['action'],'ReadValue')
                    if row['action']=='WriteValue': projected.append(writes[row['event']])
                    else: projected.extend(mapping[row['action']])
                    if row['action'].startswith('Bind'):
                        self.assertTrue(row['formatting'])
                        self.assertEqual(row['update_mode'],2 if row['property']=='SceneName' else 1)
                self.assertEqual(projected,case['expected_source_actions'])
                expected_binding = case['expected_control_binding']
                if expected_binding is None:
                    self.assertIsNone(outcome.state.selector_control)
                else:
                    actual_binding = outcome.state.selector_control.as_dict()
                    self.assertEqual({key:actual_binding[key] for key in expected_binding},expected_binding)
                plan = editor.prepare_save(outcome.state)
                self.assertEqual(bytes(plan.before_save['SceneBucket']).hex(),case['expected_scene_bucket_hex'])
                self.assertEqual(plan.before_save['SceneCount'],(8,))
                self.assertEqual([plan.before_save[f'Scene{i}StartAddress'][0] for i in range(1,9)],case['expected_scene_starts'])
                self.assertEqual([bytes(plan.before_save[f'StaticTextString{i}']).hex() for i in range(64)],case['expected_static_rows_hex'])
                self.assert_scenes(editor,plan.terminal,case['expected_scenes_after_before_save'])
                fresh = editor.load(plan.before_save,metadata=outcome.state.cache)
                self.assert_scenes(editor,fresh,case['expected_scenes_after_fresh_load'])
                self.assertEqual(dict(state.loaded.after_load),dict(outcome.state.loaded.after_load))

    def test_literal_refusals_leave_source_state_and_raw_pp_intact(self):
        for case in VECTORS['refusals']:
            with self.subTest(case=case['name']):
                editor,state,values = self.loaded(case); before = state.as_dict()
                with self.assertRaises(EdltError): editor.edit(state,operations=case['operations'])
                self.assertEqual(state.as_dict(),before)
                self.assertEqual(dict(state.loaded.after_load),dict(editor.load(values,metadata=state.cache).loaded.after_load))

    def test_selected_label_indexes_are_retained_but_not_pp_persistence(self):
        cases = {row['name']:row for row in VECTORS['cases']}; baseline = cases['label-selection-0']['expected_scene_bucket_hex']
        for suffix,index in [('none',-1),('0',0),('1',1),('2',2),('3',3)]:
            case = cases['label-selection-'+suffix]
            self.assertEqual(case['expected_scenes_after_callbacks'][0]['label_value_index'],index)
            self.assertEqual(case['expected_scenes_after_fresh_load'][0]['label_value_index'],0)
            self.assertEqual(case['expected_scene_bucket_hex'],baseline)
        for name in ('trigger-callback-old-action-absent','trigger-no-levels-normalizes-to-none','trigger-explicit-getter-after-setter'):
            self.assertFalse(cases[name]['native_create_enabled_admission'])
            self.assertIn('null lookup',cases[name]['null_lookup_profile'])
        fact = next(row for row in VECTORS['source_handler_only_facts'] if row['name']=='non-scene-current-object')
        self.assertTrue(fact['expected_enabled']); self.assertFalse(fact['public_profile_admitted'])


if __name__=='__main__': unittest.main()
