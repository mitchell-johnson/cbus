"""Source-qualified Lighting projection and sealed native binding ownership."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt import EdltError, _field
from cbus_toolkit.edlt_lighting_label_controls import (
    issue_lighting_label_binding, normalize_controls, project_lighting_label_controls,
)
from cbus_toolkit.edlt_parent_transaction import EdltParentTransaction, normalize_operations
from tests.test_edlt import Session
from tests.test_edlt_parent_form import fixture
from tests.test_edlt_parent_transaction import activation, transaction_cache

ROWS = (('0','Plain',False),('1','Icon',True),('2','',False),('3','Tail',False))


class LightingControlsTests(unittest.TestCase):
    def setUp(self):
        self.spec=fixture();self.editor=EdltParentTransaction(self.spec)
        self.session=Session(self.spec);self.source=self.editor.snapshot(self.session.values())
        self.metadata=transaction_cache(self.editor,self.source)
        next(row for row in self.metadata['groups'] if (row['application'],row['group'])==(56,42))['dynamic_images']=[False,True,False,False]

    def issue(self, controls, **options):
        operations=normalize_operations(({'op':'lighting','page':1,'position':1,'group':42,'mode':'dimmer',
            'label_controls':controls,**options},activation()))
        loaded=self.editor.lifecycle.load(self.source,metadata=self.metadata)
        op=operations[0];ordinary=self.editor.lighting_editor.plan(loaded.after_load,
            **{key:value for key,value in op.items() if key not in ('op','label_controls')})
        values={**ordinary.expected,**ordinary.changes}
        binding=issue_lighting_label_binding(self.editor,operation_number=1,application=56,group=42,
            source_values=values,operation=op,dynamic_rows=ROWS)
        return operations,binding,ordinary,values

    def test_dynamic_selection_uses_image_and_exact_stored_index(self):
        operations,binding,ordinary,values=self.issue([{'target':'label','type':10,'events':[
            {'event':'selected-row','index':1,'identity':'label:56/42/1','value':1}]}])
        record,changes,receipt=project_lighting_label_controls(self.editor,binding,
            operation_number=1,operation=operations[0],values=values,record=ordinary.record,
            common=self.editor.common)
        self.assertEqual((record[1]&0x70,record[13]),(0x20,1))
        self.assertEqual(changes[_field(6,13)],(1,))
        self.assertEqual(receipt['histories'][0]['control']['binding_callbacks'][-1]['property'],'SelectedValue')

    def test_parent_canonical_apply_replays_same_issued_binding(self):
        operations,binding,_,_=self.issue([{'target':'label','type':10,'events':[
            {'event':'selected-row','index':1,'identity':'label:56/42/1','value':1}]}])
        plan=self.editor.plan(self.source,metadata=self.metadata,operations=operations,
                              _lighting_label_bindings=(binding,))
        self.assertEqual(plan.after_controls[_field(6,13)],(1,))
        self.assertEqual(plan.after_controls[_field(6,1)][0]&0x70,0x20)
        self.assertEqual(plan.lighting_label_bindings,(binding,))
        result=self.editor.apply(self.session,plan)
        self.assertTrue(result['verified'])
        self.assertEqual(result['operation_results'][0]['label_controls']['state']['label_index'],1)

    def test_static_full_name_allocation_reserves_old_reference(self):
        text='\U0001f600'*32
        operations,binding,_,_=self.issue([{'target':'label','type':3,'events':[
            {'event':'input','text':text},{'event':'leave'}]}])
        plan=self.editor.plan(self.source,metadata=self.metadata,operations=operations,
                              _lighting_label_bindings=(binding,))
        receipt=plan.as_dict()['operation_results'][0]['label_controls']
        index=receipt['state']['raw_label_index']
        self.assertEqual(index,63)
        self.assertEqual(receipt['static_names'][index],text)
        self.assertEqual(len(bytes(plan.after_controls[f'StaticTextString{index}'])),64)
        self.assertEqual(receipt['allocations'][0]['index'],63)
        self.assertIn(0,receipt['allocations'][0]['used_indices'])
        self.assertFalse(receipt['pending'])
        self.assertTrue(self.editor.apply(self.session,plan)['verified'])

    def test_multiple_histories_resume_only_owner_state(self):
        operations,binding,_,_=self.issue([
            {'target':'status','type':5,'events':[{'event':'input','text':'Committed status'}]},
            {'target':'status','events':[{'event':'enter'}]}])
        plan=self.editor.plan(self.source,metadata=self.metadata,operations=operations,
                              _lighting_label_bindings=(binding,))
        histories=plan.as_dict()['operation_results'][0]['label_controls']['histories']
        self.assertTrue(histories[0]['control']['pending'])
        self.assertFalse(histories[1]['control']['pending'])
        self.assertEqual(histories[1]['control']['binding_callbacks'][0]['value'],'Committed status')

    def test_pending_parent_refuses_before_save_or_staging(self):
        operations,binding,_,_=self.issue([{'target':'label','type':3,'events':[{'event':'input','text':'Pending'}]}])
        with self.assertRaisesRegex(EdltError,'pending text'):
            self.editor.plan(self.source,metadata=self.metadata,operations=operations,
                             _lighting_label_bindings=(binding,))
        self.assertEqual(self.session.calls,[])

    def test_manual_cache_or_json_receipt_cannot_supply_binding(self):
        operations,binding,_,_=self.issue([{'target':'label','type':10,'events':[]}])
        for bindings in ((),(binding.as_dict(),)):
            with self.subTest(bindings=bool(bindings)),self.assertRaisesRegex(EdltError,'owner-issued'):
                self.editor.plan(self.source,metadata=self.metadata,operations=operations,
                                 _lighting_label_bindings=bindings)

    def test_foreign_mutated_source_and_future_binding_refuse(self):
        operations,binding,ordinary,values=self.issue([{'target':'label','type':10,'events':[]}])
        foreign_owner=object()
        cases=[(self.editor,replace(binding,group=43),values,operations[0],1),
               (object(),binding,values,operations[0],1),
               (foreign_owner,replace(binding,_owner=foreign_owner),values,operations[0],1),
               (self.editor,binding,{**values,'PrimaryApplication':(57,)},operations[0],1),
               (self.editor,binding,values,{**operations[0],'group':43},1),
               (self.editor,binding,values,operations[0],2)]
        for owner,binding,source,operation,number in cases:
            with self.subTest(number=number,foreign=owner is not self.editor),self.assertRaises(EdltError):
                project_lighting_label_controls(owner,binding,operation_number=number,
                    operation=operation,values=source,record=ordinary.record,common=self.editor.common)

    def test_static_ordinal_selection_and_caller_mode_facts_refuse(self):
        for events in ([{'event':'selected-row','index':0,'identity':'static:0','value':0}],
                       [{'event':'set-editable','value':False}],
                       [{'event':'binding-source-change','present':True,'changed':True}]):
            with self.subTest(events=events):
                operations,binding,_,_=self.issue([{'target':'label','type':3,'events':events}])
                with self.assertRaises(EdltError):
                    self.editor.plan(self.source,metadata=self.metadata,operations=operations,
                                     _lighting_label_bindings=(binding,))

    def test_invalid_nested_state_refuses_during_operation_normalization(self):
        with patch.object(self.editor.lifecycle,'load',side_effect=AssertionError('no load')):
            for extra in ({'state':{}},{'choices':[]},{'binding':{}}):
                with self.subTest(extra=extra),self.assertRaises(EdltError):
                    self.editor.plan(self.source,metadata=self.metadata,operations=(
                        {'op':'lighting','page':1,'position':1,'group':42,'mode':'dimmer',
                         'label_controls':[{'target':'label','events':[],**extra}]},activation()))

    def test_binding_images_and_rows_must_be_complete_exact_source_values(self):
        operations,_,ordinary,values=self.issue([{'target':'label','type':10,'events':[]}])
        for rows in ((('1','wrong',False),),(('0','unknown',None),),[('0','untyped',False)]):
            with self.subTest(rows=rows),self.assertRaises(EdltError):
                issue_lighting_label_binding(self.editor,operation_number=1,application=56,group=42,
                    source_values=values,operation=operations[0],dynamic_rows=rows)

    def test_group255_has_no_dynamic_choices_even_when_tags_were_observed(self):
        operations,_,_,values=self.issue([{'target':'label','type':10,'events':[]}])
        operation={**operations[0],'group':255}
        with self.assertRaisesRegex(EdltError,'group255'):
            issue_lighting_label_binding(self.editor,operation_number=1,application=56,group=255,
                source_values=values,operation=operation,dynamic_rows=ROWS)
        binding=issue_lighting_label_binding(self.editor,operation_number=1,application=56,group=255,
            source_values=values,operation=operation,dynamic_rows=())
        self.assertEqual(binding.as_dict()['dynamic_rows'],[])


if __name__=='__main__':unittest.main()
