"""Independent literal button traces; no original host or service execution."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_scene_button_control import (
    SceneButtonContext, check_button_context, issue_button_context,
    normalize_operation, run_scene_button_control,
)


FIXTURES = Path(__file__).resolve().parents[1] / 'research' / 'fixtures'
VECTOR = json.loads((FIXTURES / 'edlt-scene-button-vectors.json').read_text())
SOURCE, HISTORY = 'a' * 64, 'b' * 64


def operation(button='add-action-selector', **extra):
    return {'op': 'scene-button-control', 'scene': 1, 'button': button, **extra}


class Host:
    def __init__(self, returned='2', **facts):
        self.owner, self.returned = object(), returned
        self.requests, self.ui, self.observations = [], [], []
        self.facts = dict(scene=1, current_scene=1,
            primary_application=56, secondary_application=57,
            selected_trigger_group={'identity': 'trigger:202/42', 'address': '42'},
            raw_trigger_group=42, trigger_items=deepcopy(VECTOR['items']['trigger']),
            action_items=deepcopy(VECTOR['items']['action']),
            application_items=deepcopy(VECTOR['items']['application']))
        self.facts.update(facts)
        self.context = issue_button_context(owner=self.owner,
            source_fingerprint=SOURCE, history_fingerprint=HISTORY, **self.facts)

    def group(self, app):
        self.requests.append(['group', app]); return self.returned

    def level(self, app, group):
        self.requests.append(['level', app, group]); return self.returned

    def callback(self, action, facts):
        self.ui.append((action, facts))

    def run(self, op=None, **overrides):
        args = dict(context=self.context, owner=self.owner,
            source_fingerprint=SOURCE, history_fingerprint=HISTORY,
            request_add_group=self.group, request_add_level=self.level,
            ui_callback=self.callback)
        args.update(overrides)
        return run_scene_button_control(op or operation(), **args)


class ButtonControlTests(unittest.TestCase):
    def test_independent_all_three_button_literal_matrix(self):
        for case in VECTOR['cases']:
            with self.subTest(name=case['name']):
                host = Host(case['returned'], **case.get('context', {}))
                op = operation(case['button'])
                if 'selected_scenes' in case: op['selected_scenes'] = case['selected_scenes']
                result = host.run(op).as_dict()
                self.assertEqual(host.requests, [] if case['request'] is None else [case['request']])
                self.assertEqual([row[0] for row in host.ui], case['ui'])
                selected = result['selected_item']
                actual = None if selected is None else [selected['control'], selected['index'], selected['item']['identity']]
                self.assertEqual(actual, case['selection'])
                self.assertFalse(result['implicit_callbacks_inferred'])
                self.assertFalse(result['scene_items_changed_by_handler'])
                self.assertEqual(result['original_instructions_executed'], 0)

    def test_exact_value_ordinal_not_numeric_alias_or_display_name(self):
        for returned in ('042', '0x2a', 'Duplicate', ' 42', '42 '):
            with self.subTest(returned=returned):
                host = Host(returned)
                self.assertIsNone(host.run(operation('add-trigger-group')).as_dict()['selected_item'])
                self.assertEqual([row[0] for row in host.ui], ['ResetCurrentItem','ResetBindings','ResetBindings'])

    def test_first_duplicate_value_object_wins(self):
        host = Host('42', trigger_items=[
            {'identity':'first','value':'42','name':'Duplicate'},
            {'identity':'second','value':'42','name':'Duplicate'}])
        result = host.run(operation('add-trigger-group')).as_dict()
        self.assertEqual(result['selected_item']['item']['identity'], 'first')
        self.assertEqual(host.ui[1][1]['position'], 0)

    def test_action_does_not_write_or_refresh_after_selected_item(self):
        host = Host('7'); result = host.run().as_dict()
        self.assertEqual([row[0] for row in host.ui], ['SetSelectedItem','ResetCurrentItem','ResetBindings','ResetBindings'])
        self.assertFalse(any(row['action'] == 'WriteValue' for row in result['callbacks']))

    def test_exact_selected_group_address_preserved_independent_of_raw_trigger(self):
        host = Host('2', raw_trigger_group=43,
            selected_trigger_group={'identity':'trigger:202/042','address':'042'})
        host.run(); self.assertEqual(host.requests, [['level','202','042']])

    def test_items_observed_after_request_with_replaced_old_action_collection(self):
        host = Host('2')
        log=[]
        def request(app, group):
            log.append('request'); return '2'
        def observe(field):
            log.append(field)
            return VECTOR['items']['action']  # Old bound collection lacks new2.
        result=host.run(request_add_level=request, observe_items=observe).as_dict()
        self.assertEqual(log, ['request','action_items'])
        self.assertIsNone(result['selected_item'])

    def test_trigger_observer_can_supply_source_refreshed_complete_list(self):
        host=Host('2')
        rows=[*VECTOR['items']['trigger'], {'identity':'trigger:202/2','value':'2','name':'New'}]
        result=host.run(operation('add-trigger-group'), observe_items=lambda field:rows).as_dict()
        self.assertEqual(result['selected_item']['index'],2)
        self.assertEqual(host.ui[2][1]['item']['value'],'2')

    def test_null_and_empty_return_are_distinct_exact_strings(self):
        for returned, selected in ((None,False),('',True)):
            with self.subTest(returned=returned):
                host=Host(returned, action_items=[{'identity':'empty','value':'','name':'Empty'}])
                result=host.run().as_dict()
                self.assertEqual(result['selected_item'] is not None,selected)
                self.assertEqual(any(row['action']=='ObserveItems' for row in result['callbacks']),selected)

    def test_empty_initialization_can_scan_without_a_request(self):
        host=Host('unused', unit_form_present=False,
            trigger_items=[{'identity':'empty','value':'','name':'Empty'}])
        result=host.run(operation('add-trigger-group')).as_dict()
        self.assertEqual(host.requests,[])
        self.assertEqual(result['selected_item']['item']['identity'],'empty')

    def test_missing_lighting_currency_refuses_at_dereference_after_index(self):
        host=Host('0', application_currency_present=False)
        with self.assertRaisesRegex(EdltError,'CurrencyManager'):
            host.run(operation('new-lighting-group',selected_scenes=[1]))
        self.assertEqual(host.requests,[['group','56']])
        self.assertEqual([row[0] for row in host.ui],['SetSelectedIndex'])

    def test_missing_lighting_currency_is_not_consumed_without_match(self):
        host=Host('2',application_currency_present=False)
        host.run(operation('new-lighting-group',selected_scenes=[1]))
        self.assertEqual([row[0] for row in host.ui],['ResetCurrentItem','ResetBindings','ResetBindings'])

    def test_lighting_refuses_unproved_current_application_and_candidate_cast_before_add(self):
        for facts in ({'current_scene':None}, {'primary_application':None},
                      {'primary_application':255}, {'candidate_rows_are_groups':False}):
            with self.subTest(facts=facts):
                host=Host('0',**facts)
                with self.assertRaises(EdltError):
                    host.run(operation('new-lighting-group',selected_scenes=[1]))
                self.assertEqual((host.requests,host.ui),([],[]))

    def test_lighting_early_return_does_not_consume_invalid_candidate_or_current(self):
        host=Host('0',selected_scene_count=0,current_scene=None,candidate_rows_are_groups=False)
        self.assertTrue(host.run(operation('new-lighting-group',selected_scenes=[])).as_dict()['early_return'])
        self.assertEqual((host.requests,host.ui),([],[]))

    def test_selected_scene_count_must_equal_issued_facts(self):
        host=Host('0')
        with self.assertRaisesRegex(EdltError,'disagree'):
            host.run(operation('new-lighting-group',selected_scenes=[]))
        self.assertEqual(host.requests,[])

    def test_requested_dialog_shape_delegates_component_name_type(self):
        self.assertEqual(normalize_operation(operation(dialog={'cancel':False,'name':' Level '}))['dialog'], {'cancel':False,'name':' Level '})
        self.assertEqual(normalize_operation(operation(dialog={'cancel':True}))['dialog'], {'cancel':True})
        for dialog in ({}, {'cancel':0}, {'cancel':True,'name':'Unused'}, {'cancel':False,'name':None}, {'cancel':False,'address':2}):
            with self.subTest(dialog=dialog),self.assertRaises(EdltError):
                normalize_operation(operation(dialog=dialog))

    def test_public_shape_cannot_inject_choices_or_sealed_state(self):
        for extra in ({'context':{}},{'state':{}},{'returned_value':'2'},{'items':[]},{'current_scene':1}):
            with self.subTest(extra=extra),self.assertRaises(EdltError):
                normalize_operation(operation(**extra))
        for selected in (None,[1,1],[0],[9],[True],list(range(1,10))):
            with self.subTest(selected=selected),self.assertRaises(EdltError):
                normalize_operation(operation('new-lighting-group',selected_scenes=selected))
        with self.assertRaises(EdltError):normalize_operation(operation('new-lighting-group'))

    def test_foreign_export_modified_source_and_out_of_order_history_refuse_before_callback(self):
        host=Host()
        for overrides in ({'context':host.context.as_dict()}, {'owner':object()},
                          {'source_fingerprint':'c'*64}, {'history_fingerprint':'d'*64},
                          {'context':replace(host.context,history_fingerprint='e'*64)},
                          {'context':replace(host.context,_facts_json='{}')},
                          {'context':replace(host.context,_facts_json='broken')}):
            with self.subTest(overrides=list(overrides)),self.assertRaises(EdltError):
                host.run(**overrides)
                self.assertEqual(host.requests,[])

    def test_missing_owner_refuses_before_requests_ui_or_bound_list_observation(self):
        host=Host('7')
        def observe(field):
            host.observations.append(field)
            return host.facts[field+'_items']
        with self.assertRaisesRegex(EdltError,'requires its issued owner'):
            host.run(owner=None,observe_items=observe)
        self.assertEqual(host.requests,[])
        self.assertEqual(host.ui,[])
        self.assertEqual(host.observations,[])

    def test_lighting_no_unit_form_does_not_dereference_a_null_application(self):
        host=Host('unused',unit_form_present=False,primary_application=None)
        result=host.run(operation('new-lighting-group',selected_scenes=[1])).as_dict()
        self.assertIsNone(result['request'])
        self.assertEqual([row[0] for row in host.ui],['ResetCurrentItem','ResetBindings','ResetBindings'])

    def test_context_is_detached_immutable_and_receipt_exports_do_not_change_owner_facts(self):
        host=Host('7'); before=host.context.as_dict()
        host.facts['action_items'].clear()
        exported=host.context.as_dict();exported['facts']['action_items'].clear()
        with self.assertRaises(FrozenInstanceError):host.context.history_fingerprint='c'*64
        first=host.run().as_dict();first['selected_item']['item']['name']='Changed'
        self.assertEqual(host.context.as_dict(),before)
        self.assertEqual(host.run().as_dict()['selected_item']['item']['name'],'Duplicate')

    def test_callbacks_cannot_mutate_recorded_item_or_replay_on_failure(self):
        host=Host('43')
        def mutate(action,facts):
            if 'item' in facts:facts['item']['name']='Mutated'
        result=host.run(operation('add-trigger-group'),ui_callback=mutate).as_dict()
        self.assertEqual(result['selected_item']['item']['name'],'Duplicate')
        for fail in ('request','WriteValue','ResetCurrentItem'):
            with self.subTest(fail=fail):
                host=Host('43');calls=[]
                def request(app):
                    calls.append('request')
                    if fail=='request':raise RuntimeError('request failed')
                    return '43'
                def callback(action,facts):
                    calls.append(action)
                    if action==fail:raise RuntimeError('callback failed')
                with self.assertRaises(RuntimeError):host.run(operation('add-trigger-group'),request_add_group=request,ui_callback=callback)
                self.assertEqual(calls.count('request'),1)
                self.assertNotIn('ResetBindings',calls)

    def test_items_reject_unknown_types_duplicate_identities_and_unicode(self):
        for rows in ([{'identity':'x','value':42,'name':'Name'}],
                     [{'identity':'x','value':'1','name':'Name'}]*2,
                     [{'identity':'x','value':'1','name':'\ud800'}]):
            with self.subTest(rows=repr(rows)),self.assertRaises(EdltError):Host(action_items=rows)

    def test_static_receipt_hashes_methods_and_scope_without_original_claim(self):
        proof=json.loads((FIXTURES/'edlt-scene-button-source-evidence.json').read_text())
        hashes={row['symbol'].rsplit('::',1)[-1]:row['body_sha256'] for row in proof['managed_method_spans']}
        self.assertEqual(hashes['BtnAddTriggerGroupClick'],'ae52e609a313e1462ded41f9e6f9fcd9574f0fd89d93f8efee6a2552a78e32dd')
        self.assertEqual(hashes['BtnAddActionSelectorClick'],'2c37abcbec1e3fb437d0319681d53448490a03e7e88ac3842c6126c6afef7b1b')
        self.assertEqual(hashes['btnNewGroup_Click'],'49fb587bea148b46106814f56b0db67133aebe1179b528a7b11c4fe3551e04ef')
        self.assertEqual(len(proof['static_checks']),14)
        self.assertTrue(all(row['passed'] for row in proof['static_checks']))
        self.assertEqual(proof['limits']['original_instructions_executed'],0)
        self.assertFalse(proof['limits']['automatic_event_schedule_verified'])
