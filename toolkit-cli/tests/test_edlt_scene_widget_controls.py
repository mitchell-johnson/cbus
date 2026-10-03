"""Exact owned SceneWidget callbacks, causal lists and retained static names."""
from copy import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import unittest

from cbus_toolkit.edlt import EdltError, _field
from cbus_toolkit.edlt_scene import EdltSceneWidget
from cbus_toolkit.edlt_scene_widget_controls import issue_scene_widget_binding, normalize_controls, project_scene_widget_controls
from cbus_toolkit.edlt_static_grid import scope, current, adopt_retained_names
from cbus_toolkit.edlt_scene_names import load_names
from tests.test_edlt import fixture
from tests.test_edlt_scene import prepared, OPAQUE


def choice(event, prefix, value, index, **extra):
    return dict(event=event, index=index, identity=prefix + ':' + str(value), value=value, **extra)


class SceneWidgetControlTests(unittest.TestCase):
    def setUp(self):
        self.editor = EdltSceneWidget(fixture())
        self.values = prepared(self.editor.snapshot(self.editor.spec.defaults()))
        self.values['NavWidgetType'] = (1,)
        self.raw = bytes.fromhex(OPAQUE)
        for offset, value in enumerate(self.raw): self.values[_field(6, offset)] = (value,)
        self.rows = tuple(dict(identity=f'scene:{i+1}', value=i, name=f'{i+1} - ' + ('Evening' if i == 1 else '')) for i in range(8))
        self.owner = object()

    def execute(self, events, *, values=None, record=None, binding=None, operation=None, owner=None):
        values = self.values if values is None else values
        operation = operation or dict(op='scene', page=1, position=1, scene=2, scene_controls=events)
        binding = binding or issue_scene_widget_binding(self.owner, operation_number=1,
            operation=operation, source_values=values, scene_rows=self.rows, project_sha256='a'*64)
        return project_scene_widget_controls(self.owner if owner is None else owner, binding,
            operation_number=1, operation=operation, values=values,
            record=bytes(values[_field(6, i)][0] for i in range(32)) if record is None else record,
            common=self.editor.common)

    def with_cycle(self, values):
        source = dict(self.values)
        for index, value in enumerate(values): source[_field(6, 13 + index)] = (value,)
        return source

    def test_view_and_set_widget_preserve_entire_pp_and_mutating_getter_not_inferred(self):
        raw, changes, result = self.execute([{'event': 'set-widget'}, {'event': 'get-view'}])
        self.assertEqual(raw, self.raw)
        self.assertEqual(changes, {})
        self.assertEqual(result['views'][0]['scene_choices'], list(self.rows))
        self.assertEqual(result['views'][0]['cycle_storage'], [255,14,15,16,17,18,19,20,21])
        self.assertFalse(any(item['action'] == 'ReadSceneCycle' for item in result['journal']))
        setup = result['journal'][0]
        self.assertEqual((setup['saved_label_variant'], setup['saved_status_variant'], setup['restored_status_index']), (11,12,12))
        self.assertEqual(setup['binding_requests'][-4:], ['ResetScenesFalse', 'ResetStatusVariantsTrue', 'RestoreStatusValueIndex', 'RestoreStatusText'])

    def test_type_variant_and_radio_rules_preserve_all_opaque_bytes(self):
        events = [choice('type-selected', 'label-type', 2, 2, target='label'),
                  choice('variant-selected', 'label-variant', 3, 3, target='label'),
                  choice('type-selected', 'status-type', 7, 2, target='status'),
                  choice('variant-selected', 'status-variant', 2, 2, target='status'),
                  {'event':'cycle-variant-checked','radio':'cycle','checked':True}]
        raw, changes, result = self.execute(events)
        self.assertEqual(raw.hex().upper(), '062726250405061E1F090A0302FF0E0F101112131415161718191A1B1C1D1E1F')
        self.assertEqual(set(changes), {_field(6,1), _field(6,11), _field(6,12)})
        self.assertFalse(result['pending'])

    def test_scene_choice_needs_actual_ordinal_and_current_single_mode(self):
        selected = dict(event='scene-selected',index=1,identity='scene:2',value=1)
        events = [choice('macro-selected', 'scene-macro', '26|27', 1), selected]
        raw, _, result = self.execute(events)
        self.assertEqual(raw.hex().upper(), '068026250405011A1B090A0B0CFF0E0F101112131415161718191A1B1C1D1E1F')
        self.assertTrue(result['state']['single_selection_editable'])
        with self.assertRaisesRegex(EdltError, 'visible'):
            self.execute([selected])
        with self.assertRaisesRegex(EdltError, 'ordinal'):
            self.execute([choice('macro-selected','scene-macro','26|27',1),choice('scene-selected','scene',1,0)])

    def test_invalid_trailing_cycle_only_changes_on_explicit_getter(self):
        values = self.with_cycle((0,8,9,2,3,4,5,6,7))
        raw, changes, _ = self.execute([{'event':'get-view'}], values=values)
        self.assertEqual(tuple(raw[13:22]), (0,8,9,2,3,4,5,6,7))
        self.assertFalse(changes)
        raw, changes, result = self.execute([{'event':'get-cycle'}], values=values)
        self.assertEqual(tuple(raw[13:22]), (0,8,9,255,255,255,255,255,255))
        self.assertEqual(set(changes), {_field(6,i) for i in range(16,22)})
        self.assertEqual(result['journal'][0]['result']['rows'], [
            {'identity':'cycle-slot:0','slot':0,'value':0}, {'identity':'cycle-slot:1','slot':1,'value':8}])

    def test_can_add_and_remove_explicitly_read_with_nine_raw_rows(self):
        raw, _, result = self.execute([{'event':'get-can-add'}, {'event':'get-can-remove'}], values=self.with_cycle((8,7,6,5,4,3,2,1,0)))
        self.assertEqual(tuple(raw[13:22]), (8,7,6,5,4,3,2,1,0))
        self.assertEqual([row['value'] for row in result['journal'] if row['action'].startswith('ReadCan')], [False, True])

    def test_add_preserves_ninth_and_journals_resets_without_implicit_read(self):
        raw, _, result = self.execute([{'event':'cycle-add'}], values=self.with_cycle((0,1,8,3,4,5,6,7,6)))
        self.assertEqual(tuple(raw[13:22]), (0,1,0,255,255,255,255,255,6))
        self.assertEqual(result['journal'][0]['source_requests'], ['Position=List.Count','ResetCurrentItem','ResetCycleBindingsFalse','Position=List.Count','ResetSceneBindingsFalse'])
        self.assertFalse(result['journal'][0]['automatic_position_or_cycle_read_inferred'])

    def test_delete_null_is_setup_free_then_current_delete_gets_and_shifts(self):
        source = self.with_cycle((0,1,9,3,4,5,6,7,8))
        raw, _, result = self.execute([{'event':'cycle-delete'}], values=source)
        self.assertEqual(tuple(raw[13:22]), (0,1,9,3,4,5,6,7,8))
        self.assertIsNone(result['journal'][0]['getter'])
        events = [{'event':'get-cycle'}, choice('cycle-current','cycle-slot',1,1), {'event':'cycle-delete-key'}]
        raw, _, result = self.execute(events, values=source)
        self.assertEqual(tuple(raw[13:22]), (0,9,255,255,255,255,255,255,255))
        self.assertEqual(result['journal'][-1], {'event_index':2,'event':'cycle-delete-key','action':'SetKeyHandled','value':True,'key_code':46})

    def test_cycle_current_and_move_need_observed_live_ppattribute_identity(self):
        with self.assertRaisesRegex(EdltError, 'earlier explicit'):
            self.execute([choice('cycle-current','cycle-slot',0,0)])
        events = [{'event':'get-cycle'}, {'event':'cycle-move-down','index':0,'identity':'cycle-slot:0'},
                  dict(event='cycle-current',index=0,identity='cycle-slot:0',value=1),
                  dict(event='cycle-row-selected',index=0,identity='scene:1',value=0,slot=0)]
        raw, _, result = self.execute(events, values=self.with_cycle((0,1,255,3,4,5,6,7,8)))
        self.assertEqual(tuple(raw[13:22]), (0,0,255,255,255,255,255,255,255))
        self.assertEqual(result['journal'][1]['target_position'], 1)
        with self.assertRaisesRegex(EdltError, 'actual PPAttribute'):
            self.execute([{'event':'get-cycle'}, {'event':'cycle-move-down','index':0,'identity':'cycle-slot:0'}, choice('cycle-current','cycle-slot',0,0)], values=self.with_cycle((0,1,255,3,4,5,6,7,8)))

    def test_dirty_data_error_requests_never_write_or_infer_cell_commit(self):
        raw, changes, result = self.execute([{'event':'cycle-dirty','dirty':True}, {'event':'cycle-dirty','dirty':False}, {'event':'cycle-data-error'}])
        self.assertEqual(raw, self.raw); self.assertEqual(changes, {})
        self.assertEqual([row['action'] for row in result['journal']], ['CommitEditRequest','NoCommitEditRequest','SetDataErrorCancel'])
        self.assertEqual(result['journal'][0]['error_context'], 512)
        self.assertFalse(result['journal'][0]['implicit_cell_write_inferred'])

    def static_events(self, text, ending='enter'):
        return [choice('type-selected','status-type',5,3,target='status'),
                {'event':'status-text','events':[{'event':'input','text':text},{'event':ending}]}]

    def test_static_status_commit_uses_old_reference_then_readvalue_cached_full_name(self):
        raw, changes, result = self.execute(self.static_events('New status'))
        self.assertEqual(raw[12], 63)
        self.assertEqual(changes['StaticTextString63'], tuple(b'New status'.ljust(64,b'\0')))
        self.assertEqual(result['allocations'][0]['index'], 63)
        self.assertIn(12, result['allocations'][0]['used_indices'])
        actions = result['journal'][-1]['result']['binding_callbacks']
        self.assertEqual([row['action'] for row in actions], ['WriteValue','ReadValue'])
        self.assertEqual(actions[-1]['text'], 'New status')

    def test_pending_static_status_is_a_receipt_and_close_refuses(self):
        events = [choice('type-selected','status-type',5,3,target='status'),
                  {'event':'status-text','events':[{'event':'input','text':'Pending'}]}]
        raw, changes, result = self.execute(events)
        self.assertEqual(raw[12],12); self.assertEqual(set(changes), {_field(6,1)})
        self.assertTrue(result['pending'])
        events[-1]['events'].append({'event':'close'})
        with self.assertRaisesRegex(EdltError, 'Pending'): self.execute(events)

    def test_pending_readonly_refresh_discards_then_reopen_preserves_status_index(self):
        refresh = {'event':'list-refresh','change_type':'item-changed','new_index':0,'old_index':-1,
                   'selected_index':1,'visible':True}
        events = [choice('type-selected','status-type',5,3,target='status'),
                  {'event':'status-text','events':[{'event':'input','text':'Discard'}, refresh]}, {'event':'set-widget'}]
        raw, _, result = self.execute(events)
        self.assertEqual(raw[12],12)
        self.assertFalse(result['pending'])
        self.assertEqual(result['journal'][1]['result']['binding_callbacks'], [{'event_index':1,'event':'list-refresh','action':'ReadValue','text':''}])

    def test_blank_static_status_uses255_without_replacing_any_string(self):
        raw, changes, result = self.execute(self.static_events(' \u00a0'))
        self.assertEqual(raw[12],255)
        self.assertFalse(any(name.startswith('StaticTextString') for name in changes))
        self.assertEqual(result['journal'][-1]['result']['bound_name'],'')

    def test_actual_cached_long_name_reuses_without_redecoding_and_live_membership(self):
        long_name = 'A'*62 + '\u0101'
        with scope():
            names = list(load_names(self.values)); names[3] = long_name
            adopt_retained_names(self.values,tuple(names))
            raw, _, result = self.execute(self.static_events(long_name))
            self.assertEqual(raw[12],3)
            self.assertTrue(result['allocations'][0]['reused'])
            self.assertEqual(result['journal'][-1]['result']['bound_name'],long_name)
        events = self.static_events('Fresh name')
        events[-1]['events'].append({'event':'selected-name','name':'Fresh name','selected_index':0})
        _, _, result = self.execute(events)
        self.assertEqual(len(result['allocations']),1)
        self.assertEqual(result['journal'][-1]['result']['bound_name'],'Fresh name')

    def test_same_name_skips_allocator_and_malformed_equal_pp_row_is_preserved(self):
        source = dict(self.values); source[_field(6,12)] = (3,)
        source['StaticTextString3'] = tuple((b'\xe0\x80\x00' + b'X'*61))
        raw, changes, result = self.execute(self.static_events('\ufffd'), values=source)
        self.assertEqual(raw[12],3)
        self.assertNotIn('StaticTextString3',changes)
        self.assertEqual(result['allocations'],[])
        self.assertFalse(result['journal'][-1]['result']['binding_callbacks'][0]['result']['static_allocator_invoked'])

    def test_exact_binding_issuer_instance_source_history_and_owner_are_required(self):
        events = [{'event':'get-view'}]
        operation = dict(op='scene',page=1,position=1,scene=2,scene_controls=events)
        binding = issue_scene_widget_binding(self.owner,operation_number=1,operation=operation,
            source_values=self.values,scene_rows=self.rows)
        for forged in (binding.as_dict(), replace(binding), replace(binding,_seal=copy(binding._seal)),
                       replace(binding,source_sha256='0'*64), replace(binding,_seal=object())):
            with self.subTest(forged=type(forged)), self.assertRaises(EdltError):
                self.execute(events,binding=forged,operation=operation)
        with self.assertRaises(EdltError): self.execute(events,binding=binding,operation=operation,owner=object())
        stale = dict(self.values); stale[_field(6,31)] = (200,)
        with self.assertRaises(EdltError): self.execute(events,binding=binding,operation=operation,values=stale)
        with self.assertRaises(EdltError): self.execute(events,binding=binding,operation={**operation,'scene':1})

    def test_equal_pp_different_full_retained_cache_cannot_reuse_binding(self):
        events = [{'event':'get-view'}]
        operation = dict(op='scene',page=1,position=1,scene=2,scene_controls=events)
        with scope():
            names = list(load_names(self.values)); names[3] = 'A'*62+'\u0101'
            adopt_retained_names(self.values,tuple(names))
            binding = issue_scene_widget_binding(self.owner,operation_number=1,operation=operation,
                source_values=self.values,scene_rows=self.rows,retained_names=tuple(names))
            names[3] = 'A'*62+'\u0102'
            adopt_retained_names(self.values,tuple(names))
            with self.assertRaisesRegex(EdltError,'full cache'): self.execute(events,binding=binding,operation=operation)

    def test_later_refused_event_never_adopts_speculative_status_allocation(self):
        with scope():
            previous = tuple(current(self.values).names)
            before = dict(self.values)
            events = self.static_events('Speculative allocation')
            events.append(dict(event='macro-selected',index=0,identity='scene-macro:26|27',value='26|27'))
            with self.assertRaisesRegex(EdltError,'ordinal'): self.execute(events)
            self.assertEqual(tuple(current(self.values).names),previous)
            self.assertEqual(self.values,before)

    def test_partial_scene_rows_and_invalid_control_shapes_fail_before_projection(self):
        operation = dict(op='scene',page=1,position=1,scene=2,scene_controls=[{'event':'get-view'}])
        for rows in (self.rows[:2], list(self.rows), tuple(reversed(self.rows))):
            with self.subTest(rows=rows), self.assertRaises(EdltError):
                issue_scene_widget_binding(self.owner,operation_number=1,operation=operation,source_values=self.values,scene_rows=rows)
        for events in ([],[{'event':'get-cycle','pending':True}],[{'event':'cycle-dirty','dirty':1}],
                       [choice('scene-selected','scene',True,0)], [{'event':'resume','state':{}}]):
            with self.subTest(events=events), self.assertRaises(EdltError): normalize_controls(events)
        with self.assertRaises(EdltError):
            issue_scene_widget_binding(None,operation_number=1,operation=operation,source_values=self.values,scene_rows=self.rows)
        with self.assertRaises(EdltError):
            issue_scene_widget_binding(self.owner,operation_number=1,operation=operation,source_values=self.values,scene_rows=self.rows,project_sha256='NO')

    def test_all_independent_literal_histories_preserve_complete_records_and_receipts(self):
        path = Path(__file__).parents[1] / 'research/fixtures/edlt-scene-widget-control-vectors.json'
        fixture_data = json.loads(path.read_text())
        for case in fixture_data['cases']:
            with self.subTest(case=case['id']), scope():
                values = dict(self.values)
                before = bytes.fromhex(case['record_before_hex'])
                for offset,value in enumerate(before): values[_field(6,offset)] = (value,)
                if 'retained_name_override' in case:
                    supplied = case['retained_name_override']
                    values[f'StaticTextString{supplied["index"]}'] = tuple(supplied['pp_bytes'])
                    names = list(load_names(values)); names[supplied['index']] = supplied['name']
                    adopt_retained_names(values,tuple(names))
                raw,changes,receipt = self.execute(case['events'],values=values)
                self.assertEqual(raw.hex(),case['record_after_hex'])
                self.assertFalse(receipt['original_host_executed'])
                self.assertFalse(receipt['automatic_framework_dispatch_inferred'])
                self.assertFalse(receipt['physical_device_verified'])
                if 'expected_pending' in case: self.assertEqual(receipt['pending'],case['expected_pending'])
                if 'expected_cycle_rows' in case:
                    observed = receipt['journal'][0]['result']
                    self.assertEqual([row['value'] for row in observed['rows']],case['expected_cycle_rows'])
                    self.assertEqual(observed['first_invalid_slot'],case['expected_first_invalid_slot'])
                for key,action in (('expected_can_add','ReadCanAddScene'),('expected_can_remove','ReadCanRemoveScene')):
                    if key in case:
                        self.assertEqual(next(item['value'] for item in receipt['journal'] if item['action'] == action),case[key])
                if 'expected_inserted_slot' in case:
                    self.assertEqual(receipt['journal'][0]['inserted_slot'],case['expected_inserted_slot'])
                if 'expected_target_position' in case:
                    self.assertEqual(receipt['journal'][1]['target_position'],case['expected_target_position'])
                if 'expected_key_handled' in case: self.assertEqual(receipt['journal'][-1]['value'],case['expected_key_handled'])
                if 'expected_commit_context' in case:
                    self.assertEqual(receipt['journal'][0]['error_context'],case['expected_commit_context'])
                    self.assertEqual(receipt['journal'][-1]['value'],case['expected_data_error_cancel'])
                if 'expected_bound_text' in case:
                    self.assertEqual(receipt['journal'][-1]['result']['bound_name'],case['expected_bound_text'])
                if 'expected_reused' in case: self.assertEqual(receipt['allocations'][0]['reused'],case['expected_reused'])
                if 'expected_used_status_index' in case:
                    self.assertIn(case['expected_used_status_index'],receipt['allocations'][0]['used_indices'])
                if 'expected_static_changes' in case:
                    self.assertEqual({name:list(value) for name,value in changes.items() if name.startswith('StaticTextString')},case['expected_static_changes'])
                if 'expected_notifications' in case:
                    self.assertEqual(receipt['journal'][0]['result']['property_changed'],case['expected_notifications'])

    def test_static_annex_is_sanitized_and_binds_exact_source_and_historical_basis(self):
        root = Path(__file__).parents[1]
        fixture_data = json.loads((root / 'research/fixtures/edlt-scene-widget-control-vectors.json').read_text())
        reference = fixture_data['source_annex']
        raw = (root / reference['path']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),reference['sha256'])
        annex = json.loads(raw)
        self.assertEqual(len(annex['managed_method_spans']),64)
        self.assertEqual(len(annex['decompiled_source_symbols']),25)
        self.assertEqual(len(annex['static_checks']),63)
        self.assertTrue(all(row['passed'] for row in annex['static_checks']))
        self.assertEqual(annex['limits']['original_instructions_executed'],0)
        self.assertFalse(annex['limits']['implicit_binding_reads_inferred'])
        self.assertFalse(annex['limits']['native_parent_raw_cycle8_admitted'])
        self.assertFalse(re.search(r'/(?:Users|private|Volumes)/|[A-Za-z]:\\',raw.decode()))
        self.assertEqual(annex['source_choices']['lLabelTypesScene'],[dict(name=name,value=value) for name,value in [('Blank',0),('Dynamic Label',1),('Dynamic Icon',2),('Scene Label',3)]])
        basis = fixture_data['historical_basis']
        self.assertEqual(hashlib.sha256((root / basis['path']).read_bytes()).hexdigest(),basis['sha256'])
        symbols = {row['symbol'] for row in annex['managed_method_spans']}
        self.assertIn('CBusLogicModel.Units.EDLT.WidgetData.SceneData::get_SceneCycle',symbols)
        self.assertIn('CBusLogicModel.Units.EDLT.WidgetData.BaseObjects.StatusLabelTypeData::set_StatusValueIndex',symbols)
