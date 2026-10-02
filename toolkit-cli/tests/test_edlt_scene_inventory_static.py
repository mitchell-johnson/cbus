"""Independent causal source and literal oracles; never execute vendor code."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.edlt import EdltError, _render
from cbus_toolkit.edlt_display_model import EdltDisplayPreferences
from cbus_toolkit.edlt_scene_metadata import resolve_native_scene_metadata
from cbus_toolkit.edlt_scene_manager import EdltSceneManager
from tests.test_edlt import Session
from tests.test_edlt_lifecycle import fixture
from tests.test_edlt_scene_metadata import SceneMetadataClient

ROOT = Path(__file__).resolve().parents[1]
ANNEX_PATH = ROOT / 'research/fixtures/edlt-scene-inventory-source-annex.json'
VECTOR_PATH = ROOT / 'research/fixtures/edlt-scene-inventory-vectors.json'
ANNEX = json.loads(ANNEX_PATH.read_text())
VECTOR = json.loads(VECTOR_PATH.read_text())
_spec = importlib.util.spec_from_file_location('scene_inventory_static', ROOT / 'research/edlt_scene_inventory_static.py')
static = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(static)


def cases():
    return {row['name']:row for row in VECTOR['cases']}


class SceneInventoryStaticSourceTests(unittest.TestCase):
    def test_exact_managed_native_and_declaration_roster(self):
        managed = ANNEX['managed_method_spans']
        self.assertEqual(len(managed),48)
        self.assertEqual({r['symbol'] for r in managed}, {s for rows in static.METHODS.values() for s in rows})
        self.assertEqual(len(ANNEX['native_method_spans']),15)
        self.assertEqual({r['symbol'] for r in ANNEX['native_method_spans']},set(static.NATIVE_METHODS))
        self.assertEqual(len(ANNEX['decompiled_source_symbols']),41)
        for row in managed:
            with self.subTest(symbol=row['symbol']):
                self.assertEqual(row['metadata_runtime'],'v4.0.30319')
                self.assertEqual(int(row['token'],16)>>24,6)
                self.assertTrue(row['static_decode_only'])
                self.assertGreater(row['code_bytes'],0)
                self.assertGreaterEqual(row['body_bytes'],row['code_bytes']+row['header_bytes'])
                self.assertRegex(row['body_sha256'],r'^[0-9a-f]{64}$')
                self.assertRegex(row['il_sha256'],r'^[0-9a-f]{64}$')
                self.assertTrue(all(0<=r['il_offset']<row['code_bytes'] for r in row['calls']))
        for row in ANNEX['native_method_spans']:
            with self.subTest(native=row['symbol']):
                self.assertEqual(int(row['end'],16)-int(row['start'],16),row['bytes'])
                self.assertTrue(row['static_decode_only'])
                self.assertRegex(row['sha256'],r'^[0-9a-f]{64}$')

    def test_initial_callback_terminal_phases_are_distinct_source_chains(self):
        checks={r['id']:r for r in ANNEX['static_checks']}
        self.assertEqual(len(checks),36)
        self.assertTrue(all(r['passed'] for r in checks.values()))
        self.assertEqual(checks['all-64-static-rows']['integer_anchors'],[64])
        self.assertEqual(checks['eight-scenes-exact-trigger-application']['integer_anchors'],[8,255,202])
        self.assertEqual(checks['terminal-getter-before-zero-before-second-getter']['ordered_call_suffixes'][-5:],
                         ['get_ActionSelector','set_ActionSelector','get_ActionSelector','get_NameIndex','SetPPAttibuteValue'])
        self.assertEqual(checks['trigger-setter-no-action-create']['absent_call_suffix'],'GetLevelByAddress')
        self.assertEqual(checks['add-action-no-explicit-write']['absent_call_suffix'],'WriteValue')
        self.assertEqual(checks['add-action-selected-trigger-request-before-selection-and-resets']['ordered_call_suffixes'][:3],
                         ['get_SelectedItem','get_Address','AddLevelRequest'])
        self.assertTrue(any('bShowDialog=false' in r['establishes'] for r in json.loads((ROOT/'research/fixtures/edlt-scene-metadata-evidence.json').read_text())['original_methods']))

    def test_whole_network_bridge_preserves_groups_and_replaces_levels(self):
        checks={r['id']:r for r in ANNEX['static_checks']}
        self.assertEqual(checks['native-project-xml-callback-dispatches-managed-update']['direct_call_target'],
                         'SharpContainer_TLB.TSharkUnitDialogFactory.UpdateDatabase')
        self.assertEqual([r['field'] for r in checks['managed-update-uses-retained-network-refresh-event']['exact_field_references']],
                         ['NetworkRefreshEvent','NetworkRefreshEvent'])
        self.assertIn('RefreshData',checks['bridge-binds-network-refresh-and-add-delegates']['ordered_call_suffixes'])
        self.assertEqual(checks['whole-network-xml-read-virtual-dispatch']['ordered_call_suffixes'],['DBGetXML','ReadXmlData'])
        self.assertIn('InitialiseGroup',checks['reload-replaces-level-list-before-sort-add']['ordered_call_suffixes'])
        self.assertEqual(checks['group-initializer-replaces-levels']['ordered_call_suffixes'][-1],'set_Levels')
        self.assertIn('reuses-groups',next(k for k in checks if k=='reload-reuses-groups-and-mutates-list'))
        contract=ANNEX['source_contract']
        self.assertIn('Whole Network',contract['bridge_refresh'])
        self.assertIn('reconstruct',contract['bridge_refresh'])
        self.assertIn('old bound Levels list',contract['level_collection'])
        self.assertFalse(ANNEX['limits']['original_live_append_order_verified'])
        self.assertFalse(VECTOR['limits']['original_live_append_policy_inferred'])

    def test_five_dwords_and_transport_framework_bounds_are_explicit(self):
        p={'format':'cbus-edlt-display-preferences-v1','registry_key_present':True,'values':{
            'DisplayHexAddress':0,'DisplayAddressValue':0,'SortModeApplications':0,'SortModeGroups':1,'SortModeLevels':1}}
        self.assertEqual(VECTOR['fixture']['display_preferences'],p)
        self.assertEqual({k:ANNEX['display_profile'][k] for k in p},p)
        for name,value in ANNEX['limits'].items():
            self.assertEqual(value,0 if name.endswith('instructions_executed') else False,name)
        self.assertFalse(VECTOR['limits']['host_gui_executed'])
        self.assertFalse(VECTOR['limits']['automatic_notification_schedule_verified'])
        self.assertIn('Qualified accepted-dialog lowering',ANNEX['source_contract']['action_add'])
        self.assertIn('terminal save',ANNEX['source_contract']['terminal_save'])

    def test_historical_dependencies_are_unchanged_and_public_evidence_has_no_code(self):
        for row in ANNEX['historical_dependencies']:
            with self.subTest(path=row['path']):
                self.assertEqual(hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest(),row['sha256'])
        historical=ROOT/VECTOR['oracle']['input_only_historical_fixture']
        self.assertEqual(hashlib.sha256(historical.read_bytes()).hexdigest(),VECTOR['oracle']['input_only_historical_fixture_sha256'])
        for path in (ANNEX_PATH,VECTOR_PATH):
            text=path.read_text()
            for forbidden in ('/Users/','/private/','/Volumes/','body_hex','il_hex','private_key','BEGIN PRIVATE'):
                self.assertNotIn(forbidden,text)
        for row in ANNEX['original_inputs']:
            self.assertFalse(row['path'].startswith('/'))
            self.assertNotIn('..',Path(row['path']).parts)

    def test_static_regeneration_reads_only_explicit_private_inputs(self):
        vendor=os.environ.get('CBUS_SCENE_INVENTORY_STATIC_VENDOR_ROOT')
        original=os.environ.get('CBUS_SCENE_INVENTORY_STATIC_ORIGINAL_APP')
        if not vendor or not original:
            self.skipTest('Explicit pinned SceneInventory static vendor/EXE/MAP inputs are not configured')
        result=static.recover(Path(vendor),Path(original))
        raw=(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode()
        self.assertEqual(raw,ANNEX_PATH.read_bytes())


class SceneInventoryIndependentLiteralTests(unittest.TestCase):
    def test_complete_literal_geometry_and_source_empty_serialization(self):
        self.assertEqual(len(VECTOR['cases']),25)
        self.assertEqual(len(VECTOR['parent_acceptance_edges']),5)
        self.assertEqual(len(VECTOR['refusals']),12)
        f=VECTOR['fixture'];self.assertEqual(len(f['consumer_pp_parameters']),76)
        self.assertEqual(len(f['static_rows_hex']),64)
        self.assertEqual(bytes.fromhex(f['scene_bucket_hex'])[:10],bytes([2,0,42,7,63,2,0,43,9,62]))
        for case in VECTOR['cases']:
            with self.subTest(case=case['name']):
                self.assertEqual(case['expected_scene_count'],8)
                self.assertEqual(case['expected_scene_starts'],[0,5,10,15,20,25,30,35])
                self.assertEqual(len(case['input_consumer_pp_parameters']),76)
                raw=bytes.fromhex(case['expected_scene_bucket_hex'])
                self.assertEqual(len(raw),232);self.assertEqual(raw[40:],b'\xff'*192)
                self.assertEqual(bytes(int(v,16) for v in case['expected_scene_bucket_pp'].split()),raw)
                self.assertEqual(len(case['expected_static_rows_hex']),64)
                for row in case['expected_static_rows_hex']:self.assertEqual(len(bytes.fromhex(row)),64)
                for phase in ('before_save','after_terminal_save','after_fresh_load'):
                    rows=case['expected_scenes_'+phase]
                    self.assertEqual([r['scene'] for r in rows],list(range(1,9)))
                    self.assertTrue(all(r['items']==[] for r in rows))
                for i,s in enumerate(case['expected_scenes_after_terminal_save']):
                    expected=[2 if s['can_edit'] else 0,0,s['raw_trigger'],255 if s['raw_trigger']==255 else max(s['raw_action'],0),s['name_index']]
                    self.assertEqual(list(raw[i*5:i*5+5]),expected)

    def test_exact_ordered_choice_identity_and_full_dynamic_rows(self):
        f=VECTOR['fixture'];c=f['exact_source_choices']
        self.assertEqual([r['value'] for r in c['triggers']],[42,43,44,45])
        self.assertEqual([r['value'] for r in c['actions_by_group']['42']],[0,1,7])
        self.assertEqual([r['value'] for r in c['actions_by_group']['43']],[0,7,9])
        self.assertNotIn(255,[r['value'] for r in c['triggers']])
        self.assertEqual(c['actions_by_group']['42'][1]['name'],c['actions_by_group']['42'][2]['name'])
        self.assertNotEqual(c['actions_by_group']['42'][1]['identity'],c['actions_by_group']['42'][2]['identity'])
        for case in VECTOR['cases']:
            for v in case['expected_intermediate_views']:
                with self.subTest(case=case['name'],operation=v['operation']):
                    self.assertGreaterEqual(v['operation'],1);self.assertLessEqual(v['operation'],len(case['operations']))
                    for row in v['dynamic_labels']:
                        self.assertEqual(set(row),{'identity','value','raw_value','name','image_present'})
                        self.assertEqual(type(row['value']),int)
                        self.assertRegex(row['identity'],r'^label:202/\d+/\d+/[0-3]$')
                    self.assertEqual(len({r['identity'] for r in v['action_choices']}),len(v['action_choices']))
                    self.assertTrue(all(r['formatted_display']==r['name'] for r in v['action_choices']))

    def test_literal_creation_phases_allocation_and_no_future_borrow(self):
        c=cases()
        earlier=c['getter-reserves-before-first-free-action-add']['expected_created_objects']
        reverse=c['action-add-before-getter-reuses-new-address']['expected_created_objects']
        self.assertEqual([(r['address'],r['name']) for r in earlier],[(2,'Action Selector 2'),(3,'Level 3')])
        self.assertEqual([(r['address'],r['name']) for r in reverse],[(2,'Level 2')])
        initial=c['all-eight-loader-getters-reserve-before-first-dialog']['expected_created_objects']
        self.assertEqual([(r['phase'],r['address']) for r in initial],[('initial-load',n) for n in range(8)]+[('operation',8)])
        fallback=c['terminal-fallback-zero-not-borrowed-early']
        self.assertEqual(fallback['expected_intermediate_views'][0]['action_choices'],[])
        self.assertEqual(fallback['expected_scenes_before_save'][0]['raw_action'],-1)
        self.assertEqual(fallback['expected_scenes_after_terminal_save'][0]['raw_action'],0)
        self.assertEqual([(r['phase'],r['address']) for r in fallback['expected_created_objects']],[('terminal-save',0)])
        self.assertEqual(c['canceled-action-add-keeps-bound-generation']['expected_created_objects'],[])
        self.assertEqual(c['canceled-trigger-add-keeps-current-and-inventory']['expected_created_objects'],[])
        p={r['name']:r for r in VECTOR['parent_acceptance_edges']}
        self.assertEqual(p['earlier-parent-add-visible']['expected_initial_actions42'],[0,1,2,7])
        self.assertEqual(p['future-parent-add-invisible']['expected_initial_actions42'],[0,1,7])
        self.assertFalse(p['reset-fresh-owner-and-pending-name']['expected_old_timeline_admitted'])

    def test_current_vs_bound_and_name_oracles_require_explicit_rebind(self):
        c=cases();case=c['action-add-explicit-rebind-sees-new-generation']
        self.assertEqual([r['value'] for r in case['expected_intermediate_views'][0]['action_choices']],[0,1,7])
        self.assertEqual([r['value'] for r in case['expected_intermediate_views'][1]['action_choices']],[0,1,2,7])
        self.assertEqual(case['operations'][3]['events'],[{'event':'scene-current-changed','current':True}])
        mismatch=c['old42-choice-writes-current43-setter']
        self.assertEqual(mismatch['operations'][2]['events'][0]['choice_identity'],'action:202/42/1')
        self.assertEqual(mismatch['expected_created_objects'][0]['group'],43)
        pending=c['pending-name-cancel-blocks-save'];self.assertFalse(pending['expected_composable'])
        commit=c['pending-name-explicit-rebind-correct-target-commit']
        self.assertEqual(commit['expected_scenes_before_save'][0]['name_index'],61)
        self.assertEqual(bytes.fromhex(commit['expected_static_rows_hex'][61]),b'Pending'+b'\0'*57)
        negatives={r['name'] for r in VECTOR['refusals']}
        self.assertTrue({'new-choice-stale-bound-generation','divergent-action-add-combo-target','pending-name-wrong-bound-target','foreign-timeline-owner','mutated-timeline-frame','out-of-order-replay'}<=negatives)

    def test_noncreating_literal_states_are_bound_to_actual_manager(self):
        # These are product observations against independent authored oracles.
        # Causal creation cases require the separately owner-issued native
        # timeline and are consumed by its owning/public modules, never forged
        # by this test through a JSON import capability.
        selected=('populated-history-unchanged','old42-existing-choice-current43-existing-labels',
                  'disabled-save-ff-without-action-zero','valid-getter-preserves-old-labels',
                  'setter-adopts-existing-new-labels','disabled-current-retains-old-action-target',
                  'copy-preserves-target-labels-until-refresh','pending-name-explicit-rebind-correct-target-commit',
                  'duplicate-display-choice-ordinal-identity')
        for name in selected:
            with self.subTest(case=name):
                case=cases()[name];spec=fixture();editor=EdltSceneManager(spec);session=Session(spec)
                state=editor.load({**session.current,**case['input_consumer_pp_parameters']},metadata=deepcopy(VECTOR['fixture']['cache']))
                result=editor.edit(state,operations=case['operations'])
                for actual,expected in zip(result.state.scenes,case['expected_scenes_before_save']):
                    self.assertEqual((actual.slot,actual.primary_secondary,actual.can_edit,actual.raw_trigger,actual.raw_action,actual.name_index,actual.label_value_index),
                                     tuple(expected[k] for k in ('scene','application_selector','can_edit','raw_trigger','raw_action','name_index','label_value_index')))
                    self.assertEqual([r.as_dict() for r in actual.dynamic_labels],expected['dynamic_labels'])
                raw={**result.state.loaded.after_load,**result.state.static_text_overlay}
                for i,expected in enumerate(case['expected_static_rows_hex']):
                    self.assertEqual(bytes(raw['StaticTextString'+str(i)]).hex(),expected)


    @staticmethod
    def native_loaded(case):
        """Build invented native input from fixture facts, never from outcomes."""
        f=VECTOR['fixture'];spec=fixture();editor=EdltSceneManager(spec)
        client=SceneMetadataClient(spec)
        appcache=f['cache']['application_cache']
        group_lists={r['application']:r for r in appcache['group_lists']}
        action_lists={r['group']:r for r in f['cache']['action_lists']}
        level_labels={(r['group'],r['action']):r['labels'] for r in f['cache']['level_labels']}
        original=client.applications
        client.applications={}
        for a in appcache['applications']:
            app=a['address']
            if app==255:continue
            native=deepcopy(original[app]);native['tag']=a['name'];native['groups']={}
            for g in group_lists.get(app,{'groups':[]})['groups']:
                group=g['address']
                if group==255:continue
                source=deepcopy(original[app]['groups'][group]);source['tag']=g['name']
                source['levels']=tuple(r['address'] for r in action_lists.get(group,{'actions':[]})['actions']) if app==202 else ()
                if app==202:
                    source['level_names']={r['address']:r['name'] for r in action_lists[group]['actions']}
                    source['level_tags']={level:tuple({'variant':i,'type':'TEXT','value':r['name']} for i,r in enumerate(level_labels[group,level])) for level in source['levels']}
                for target in case['input_overrides'].get('remove_levels',[]):
                    if app==202 and target[0]==group:source['levels']=tuple(v for v in source['levels'] if v!=target[1])
                native['groups'][group]=source
            client.applications[app]=native
        raw={**client.values,**case['input_consumer_pp_parameters']}
        values=editor.snapshot(raw)
        client.values={name:_render(value) for name,value in values.items()}
        xml=client.xml().replace('<Address>TEST</Address>', '<Address>TEST</Address><TagName>Inventory Fixture</TagName>',1)
        resolved=resolve_native_scene_metadata(xml,'//TEST/254/p/20',values,editor,case['operations'],
            display_preferences=EdltDisplayPreferences.from_dict(f['display_preferences']))
        return editor,editor.load(values,metadata=resolved.cache),resolved

    def test_native_owner_issued_timeline_consumes_all_independent_literals(self):
        for case in VECTOR['cases']:
            with self.subTest(case=case['name']):
                editor,state,resolved=self.native_loaded(case)
                outcome=editor.edit(state,operations=resolved.operations)
                for actual,expected in zip(outcome.state.scenes,case['expected_scenes_before_save']):
                    self.assertEqual((actual.slot,actual.primary_secondary,actual.can_edit,actual.raw_trigger,actual.raw_action,actual.name_index,actual.label_value_index),
                        tuple(expected[k] for k in ('scene','application_selector','can_edit','raw_trigger','raw_action','name_index','label_value_index')))
                    self.assertEqual([r.as_dict() for r in actual.dynamic_labels],expected['dynamic_labels'])
                results=outcome.as_dict()['operation_results']
                for expected in case['expected_intermediate_views']:
                    ordinal=expected['operation']-1-sum(op.get('cancel',False) for op in case['operations'][:expected['operation']-1])
                    actual=results[ordinal]['view']
                    self.assertEqual(actual['trigger_group'],expected['raw_trigger'])
                    self.assertEqual(actual['raw_action_selector'],expected['raw_action_selector'])
                    self.assertEqual(actual['action_selector'],expected['action_selector'])
                    for field in ('application_choices','trigger_choices','action_choices','dynamic_labels','label_value_index'):
                        self.assertEqual(actual[field],expected[field],field)
                observed=[(r['kind'].lower(),r.get('group'),r['address'],r['name']) for r in resolved.as_dict()['planned_creations']]
                literal=[(r['kind'],r['group'] if r['kind']=='level' else None,r['address'],r['name']) for r in case['expected_created_objects']]
                self.assertEqual(observed,literal)
                if not case['expected_composable']:
                    with self.assertRaisesRegex(EdltError,'pending|uncommitted|commit'):editor.prepare_composition(outcome.state)
                    continue
                composition=editor.prepare_composition(outcome.state)
                self.assertEqual(bytes(composition.fields['SceneBucket']).hex(),case['expected_scene_bucket_hex'])
                self.assertEqual(composition.fields['SceneCount'],(8,))
                self.assertEqual([composition.fields[f'Scene{i}StartAddress'][0] for i in range(1,9)],case['expected_scene_starts'])
                for i,row in enumerate(case['expected_static_rows_hex']):
                    self.assertEqual(bytes({**outcome.state.loaded.after_load,**outcome.state.static_text_overlay,**composition.fields}['StaticTextString'+str(i)]).hex(),row)


    def test_later_initial_getter_cannot_replace_earlier_scene_label_objects(self):
        case=cases()['later-initial-getter-keeps-earlier-label-generation']
        editor,state,resolved=self.native_loaded(case)
        prior=state.scenes[0].dynamic_labels
        current=state.cache.labels(42,7)
        self.assertEqual([r.name for r in prior],['Evening on','Evening wait','Evening off',''])
        self.assertEqual([r.name for r in current],['Evening on','Evening wait','Evening off',''])
        self.assertTrue(all(a is not b for a,b in zip(prior,current)))
        outcome=editor.edit(state,operations=resolved.operations)
        self.assertTrue(all(a is b for a,b in zip(prior,outcome.state.scenes[0].dynamic_labels)))
        self.assertEqual(outcome.as_dict()['operation_results'][1]['view']['dynamic_labels'],case['expected_intermediate_views'][0]['dynamic_labels'])

    def test_literal_refusals_have_no_admitted_model_execution(self):
        cases_by_name=cases()
        refusals={row['name']:row for row in VECTOR['refusals']}
        for name in ('new-choice-stale-bound-generation','divergent-action-add-combo-target',
                     'pending-name-wrong-bound-target','future-parent-choice-before-creation','invalid-transport-name'):
            with self.subTest(case=name):
                case=deepcopy(cases_by_name['populated-history-unchanged'])
                case['operations']=deepcopy(refusals[name]['operations'])
                with self.assertRaises((EdltError,ValueError)):
                    editor,state,resolved=self.native_loaded(case)
                    before=state.as_dict()
                    try:
                        editor.edit(state,operations=resolved.operations)
                    finally:
                        self.assertEqual(state.as_dict(),before)
