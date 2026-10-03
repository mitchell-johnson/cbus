from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_dynamic_label_control import (
    DynamicLabelControlState, drawing_descriptor, normalize_operation,
    run_dynamic_label_control,
)

VECTOR = json.loads((Path(__file__).parents[1] / 'research/fixtures/edlt-label-control-vectors.json').read_text())


class Model:
    def __init__(self):
        self.owner, self.text, self.index, self.calls = object(), 'Original', 0, []
        self.rows = [dict(row) for row in VECTOR['rows']]
    def get_text(self):
        self.calls.append(('read-text', self.text)); return self.text
    def get_index(self):
        self.calls.append(('read-index', self.index)); return self.index
    def set_text(self, text):
        self.calls.append(('write-text', text)); self.text = 'bound:' + text; return {'text':self.text}
    def set_index(self, index):
        self.calls.append(('write-index',index)); self.index = index; return {'index':index}
    def run(self, events, **kwargs):
        return run_dynamic_label_control(events,owner=self.owner,choices=self.rows,
            get_text=self.get_text,set_text=self.set_text,get_index=self.get_index,
            set_index=self.set_index,**kwargs)


class DynamicControlTests(unittest.TestCase):
    def test_enter_leave_and_key_enter_write_then_read(self):
        for event in ({'event':'enter'},{'event':'leave'},{'event':'key-preview','key':'enter'}):
            with self.subTest(event=event):
                model=Model(); result=model.run([{'event':'input','text':'New'},event],text_editable=True)
                self.assertEqual(model.calls,[('read-text','Original'),('read-index',0),('write-text','New'),('read-text','bound:New')])
                self.assertFalse(result.state.pending)
                self.assertEqual([row['action'] for row in result.as_dict()['binding_callbacks']],['WriteValue','ReadValue'])

    def test_input_is_inspectable_and_pending_close_refuses(self):
        model=Model(); result=model.run([{'event':'input','text':'Pending'}],text_editable=True)
        self.assertTrue(result.state.pending); self.assertEqual(model.text,'Original')
        self.assertEqual(result.as_dict()['binding_callbacks'],[])
        with self.assertRaisesRegex(EdltError,'Pending dynamic-label close'):
            model.run([{'event':'close'}],initial_state=result.state)
        resumed=model.run([{'event':'leave'},{'event':'close'}],initial_state=result.state)
        self.assertTrue(resumed.as_dict()['closed']); self.assertFalse(resumed.state.pending)

    def test_all_arrows_suppress_exactly_one_selection(self):
        for key in ('left','right','up','down'):
            with self.subTest(key=key):
                model=Model(); first=model.run([{'event':'key-preview','key':key}],text_editable=True)
                result=model.run([{'event':'selected-row','index':0,'identity':'label:56/42/0','value':0}],initial_state=first.state)
                self.assertTrue(result.state.pending);self.assertFalse(result.state.suppress_next_selection)
                self.assertEqual([x for x in model.calls if x[0].startswith('write')],[])
                committed=model.run([{'event':'selected-row','index':0,'identity':'label:56/42/0','value':0}],initial_state=result.state)
                self.assertEqual(committed.state.text,'bound:Plain')
                self.assertEqual([r['action'] for r in result.as_dict()['binding_callbacks']],['DetachListChanged','AttachListChanged','SuppressSelectionWrite'])

    def test_suppression_consumed_without_selected_object(self):
        model=Model(); result=model.run([{'event':'key-preview','key':'down'},
            {'event':'selected-row','index':-1}],text_editable=True)
        self.assertFalse(result.state.suppress_next_selection)
        self.assertEqual([x for x in model.calls if x[0].startswith('write')],[])

    def test_indexed_selection_writes_index_only(self):
        model=Model(); result=model.run([{'event':'selected-row','index':1,'identity':'label:56/42/1','value':1}])
        self.assertEqual(model.index,1);self.assertEqual(model.text,'Original')
        self.assertEqual([(r['action'],r.get('property')) for r in result.as_dict()['binding_callbacks']],
                         [('DetachListChanged',None),('WriteValue','SelectedValue'),('ReadValue','SelectedValue')])

    def test_editable_selection_uses_actual_formatted_display_and_not_input_limit(self):
        model=Model();model.rows[0]['formatted_display']='Z'*100
        result=model.run([{'event':'selected-row','index':0,'identity':'label:56/42/0','value':0}],text_editable=True)
        self.assertEqual(model.text,'bound:'+'Z'*100)
        self.assertEqual(result.state.text,model.text)

    def test_explicit_empty_formatted_display_is_not_replaced_with_name(self):
        model=Model();model.rows[0]['formatted_display']=''
        result=model.run([{'event':'selected-row','index':0,'identity':'label:56/42/0','value':0}],text_editable=True)
        self.assertEqual(model.text,'bound:')
        self.assertEqual(result.state.text,'bound:')
        self.assertEqual(next(row['value'] for row in result.as_dict()['binding_callbacks']
                              if row['action']=='WriteValue'),'')

    def test_selected_identity_and_order_are_literal(self):
        for kwargs in ({'index':1,'identity':'label:56/42/0','value':0},
                       {'index':0,'identity':'label:56/42/0','value':1},
                       {'index':4,'identity':'label:56/42/0','value':0}):
            with self.subTest(kwargs=kwargs):
                model=Model()
                with self.assertRaisesRegex(EdltError,'observed'):
                    model.run([{'event':'selected-row',**kwargs}])
                self.assertEqual([x for x in model.calls if x[0].startswith('write')],[])

    def test_literal_list_refresh_predicates(self):
        for case in VECTOR['list_refresh_cases']:
            with self.subTest(case=case):
                model=Model(); row={k:v for k,v in case.items() if k!='read'}
                result=model.run([{'event':'input','text':'Pending'},{'event':'list-refresh',**row}],text_editable=True)
                self.assertEqual(result.state.pending,not case['read'])
                self.assertEqual([r['action'] for r in result.as_dict()['binding_callbacks']],['ReadValue'] if case['read'] else [])
                self.assertEqual(model.text,'Original')

    def test_list_guards_precede_async_requirement(self):
        base={'event':'list-refresh','change_type':'item-added','new_index':0,'old_index':-1,'selected_index':1,'invoke_required':True}
        for kwargs in ({'text_editable':False},{'text_editable':True}):
            with self.subTest(kwargs=kwargs):
                model=Model()
                if kwargs['text_editable']:
                    with self.assertRaisesRegex(EdltError,'Asynchronous'):model.run([base],**kwargs)
                else:self.assertEqual(model.run([base],**kwargs).as_dict()['binding_callbacks'],[])
        model=Model();self.assertEqual(model.run([{**base,'list_updates_disabled':True}],text_editable=True).as_dict()['binding_callbacks'],[])

    def test_hidden_or_irrelevant_notification_never_reads(self):
        base={'event':'list-refresh','change_type':'item-added','new_index':0,'old_index':-1,'selected_index':1}
        for facts in ({'visible':False},{'list_updates_disabled':True},{'change_type':'item-moved'}):
            with self.subTest(facts=facts):
                model=Model();result=model.run([{'event':'input','text':'Pending'},{**base,**facts}],text_editable=True)
                self.assertTrue(result.state.pending);self.assertEqual(result.as_dict()['binding_callbacks'],[])

    def test_editable_transition_exact_binding_order_without_read(self):
        model=Model();result=model.run([{'event':'set-editable','value':True}]).as_dict()
        self.assertEqual([r['action'] for r in result['binding_callbacks']],['SetVisible','DetachSelectedIndexChanged','DetachPreviewKeyDown','DetachLeave','RemoveBinding','SetBindingMode','AddBinding','AttachPreviewKeyDown','AttachLeave','AttachSelectedIndexChanged','DetachListChanged','AttachListChanged'])
        mode=next(r for r in result['binding_callbacks'] if r['action']=='SetBindingMode')
        self.assertEqual({key:mode[key] for key in VECTOR['binding_modes']['editable']},VECTOR['binding_modes']['editable'])
        self.assertEqual(model.calls,[('read-text','Original'),('read-index',0)])

    def test_same_mode_or_source_identity_is_noop(self):
        model=Model();result=model.run([{'event':'set-editable','value':False},
            {'event':'binding-source-change','changed':False,'present':False}])
        self.assertEqual(result.as_dict()['binding_callbacks'],[]);self.assertTrue(result.state.binding_present)

    def test_unbinding_and_rebinding_do_not_infer_read(self):
        model=Model();result=model.run([{'event':'binding-source-change','changed':True,'present':False},
            {'event':'binding-source-change','changed':True,'present':True}]).as_dict()
        self.assertNotIn('ReadValue',[r['action'] for r in result['binding_callbacks']])
        mode=next(r for r in result['binding_callbacks'] if r['action']=='SetBindingMode')
        self.assertEqual({key:mode[key] for key in VECTOR['binding_modes']['indexed']},VECTOR['binding_modes']['indexed'])

    def test_other_key_closes_dropdown_but_arrows_do_not(self):
        model=Model();result=model.run([{'event':'drop-down','open':True},{'event':'key-preview','key':'up'}],text_editable=True)
        self.assertTrue(result.state.dropped_down)
        closed=model.run([{'event':'key-preview','key':'other'}],initial_state=result.state)
        self.assertFalse(closed.state.dropped_down)
        self.assertTrue(closed.state.suppress_next_selection)

    def test_state_is_immutable_sealed_owner_bound_and_receipt_non_importable(self):
        model=Model();result=model.run([])
        with self.assertRaises(FrozenInstanceError):result.state.pending=True
        for state in (result.as_dict()['state'],DynamicLabelControlState('Original',0,False,True),
                      replace(result.state,pending=True)):
            with self.subTest(state=type(state).__name__),self.assertRaises(EdltError):model.run([],initial_state=state)
        other=Model()
        with self.assertRaises(EdltError):other.run([],initial_state=result.state)
        with self.assertRaises(EdltError):
            other.run([],initial_state=replace(result.state,_owner=other.owner))
        self.assertEqual(other.calls,[])
        result.as_dict()['state']['text']='mutated'
        self.assertEqual(result.state.text,'Original')

    def test_input_unicode_limits_and_loaded_text_distinct(self):
        for text in ('A'*65,'\U0001f600'*33,'nul\0text','\ud800'):
            with self.subTest(text=repr(text)),self.assertRaises(EdltError):Model().run([{'event':'input','text':text}],text_editable=True)
        model=Model();model.text='Z'*120
        self.assertEqual(model.run([]).state.text,'Z'*120)
        self.assertTrue(model.run([{'event':'input','text':'\U0001f600'*32}],text_editable=True).state.pending)

    def test_failed_write_has_no_read_retry_or_restore(self):
        calls=[]
        def fail(value):calls.append(value);raise RuntimeError('source property rejected')
        with self.assertRaisesRegex(RuntimeError,'rejected'):
            run_dynamic_label_control([{'event':'selected-row','index':0,'identity':'label:56/42/0','value':0}],
                owner=object(),choices=VECTOR['rows'],get_text=lambda:'old',set_text=fail,
                get_index=lambda:0,set_index=fail)
        self.assertEqual(calls,[0])

    def test_drawing_literal_text_icon_null_empty_and_count_limit(self):
        for case in VECTOR['drawing']:
            with self.subTest(case=case):
                result=drawing_descriptor(VECTOR['rows'],index=case['index'])
                self.assertEqual((result['text'],result['image_present']),(case['text'],case['image_present']))
        self.assertEqual(drawing_descriptor(VECTOR['rows'],index=-1,text='Current')['text'],'Current')
        rows=[*VECTOR['rows'],{'identity':'fifth','value':4,'name':'Fifth','image_present':False}]
        self.assertFalse(drawing_descriptor(rows,index=0)['drawn'])

    def test_json_state_rows_or_modes_cannot_be_injected(self):
        for extra in ({'state':{}},{'choices':[]},{'owner':'forged'}):
            with self.subTest(extra=extra),self.assertRaises(EdltError):normalize_operation({'op':'dynamic-label-control','target':'label','events':[],**extra})
        with self.assertRaises(EdltError):Model().run([{'event':'input','text':'not editable'}])


if __name__=='__main__':unittest.main()
