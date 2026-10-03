"""Six ordinary widget projections with source-issued callback authorities."""
from dataclasses import replace
import unittest

from cbus_toolkit.edlt import EdltError, EdltLighting, _field
from cbus_toolkit.edlt_app_group_label_controls import (
    issue_app_group_label_binding, normalize_controls, project_app_group_label_controls,
)
from cbus_toolkit.edlt_app_group_label_properties import PROFILES
from cbus_toolkit.edlt_enable import EdltEnableWidget
from cbus_toolkit.edlt_fan import EdltFanWidget
from cbus_toolkit.edlt_multilevel import EdltMultiLevelWidget
from cbus_toolkit.edlt_room_courtesy import EdltRoomCourtesyWidget
from cbus_toolkit.edlt_shutter import EdltShutterWidget
from cbus_toolkit.edlt_timer import EdltTimerWidget
from cbus_toolkit.edlt_static_grid import scope, initialize, current, adopt_retained_names
from tests.test_edlt import Session
from tests.test_edlt_parent_form import fixture

ROWS=(('0','Plain',False),('1','Icon',True),('2','',False),('3','Tail',False))
EDITORS={'enable':EdltEnableWidget,'fan':EdltFanWidget,'multilevel':EdltMultiLevelWidget,
         'room-courtesy':EdltRoomCourtesyWidget,'shutter':EdltShutterWidget,'timer':EdltTimerWidget}


class AppGroupControlsTests(unittest.TestCase):
    def setUp(self):
        self.spec=fixture();self.common=EdltLighting(self.spec)
        self.source=self.common.snapshot(Session(self.spec).values());self.owner=object()

    def issued(self,family,controls,*,source=None,position=1,application='primary',rows=ROWS):
        source=self.source if source is None else source
        options={'page':1,'position':position}
        if family=='enable': options.update(variable=42,level=127)
        else: options.update(group=42,application=application)
        plan=EDITORS[family](self.spec).plan(source,**options)
        values={**plan.expected,**plan.changes}
        operation={'op':family,**options,'label_controls':normalize_controls(controls,family=family)}
        app=203 if family=='enable' else values['PrimaryApplication' if application=='primary' else 'SecondaryApplication'][0]
        binding=issue_app_group_label_binding(self.owner,operation_number=1,application=app,group=42,
            source_values=values,operation=operation,dynamic_rows=rows,
            provider_provenance={'profile':'invented-ordered-source-rows','sha256':'a'*64})
        return operation,binding,values,plan.record

    def project(self,issued,**overrides):
        operation,binding,values,record=issued
        return project_app_group_label_controls(overrides.get('owner',self.owner),overrides.get('binding',binding),
            operation_number=overrides.get('number',1),operation=overrides.get('operation',operation),
            values=overrides.get('values',values),record=overrides.get('record',record),common=self.common)

    def test_all_six_select_exact_image_variant_after_ordinary_widget_plan(self):
        for family,selected in PROFILES.items():
            app=203 if family=='enable' else 56
            issued=self.issued(family,[{'target':'label','type':10,'events':[
                {'event':'selected-row','index':1,'identity':f'label:{app}/42/1','value':1}]}])
            record,changes,receipt=self.project(issued)
            expected=bytearray(issued[3]);expected[1]=(expected[1]&0x8f)|0x20;expected[selected.label_offset]=1
            with self.subTest(family=family):
                self.assertEqual(record,bytes(expected))
                self.assertEqual(receipt['state']['label_index'],1)
                self.assertEqual(changes[_field(6,selected.label_offset)],(1,))
                self.assertEqual(receipt['histories'][0]['control_class'],'ComboImageTagDLT')
                self.assertFalse(receipt['original_host_executed'])

    def test_dynamic_status_selection_preserves_label_and_opaque_bytes(self):
        for family in ('enable','timer','shutter','room-courtesy'):
            app=203 if family=='enable' else 56
            issued=self.issued(family,[{'target':'status','type':10,'events':[
                {'event':'selected-row','index':1,'identity':f'label:{app}/42/1','value':1}]}])
            record,_,receipt=self.project(issued);selected=PROFILES[family]
            expected=bytearray(issued[3]);expected[1]=(expected[1]&0xf0)|7;expected[selected.status_offset]=1
            with self.subTest(family=family):
                self.assertEqual(record,bytes(expected));self.assertEqual(receipt['state']['status_index'],1)

    def test_fan_and_multilevel_all_four_static_status_callbacks_share_allocator(self):
        for family in ('fan','multilevel'):
            controls=[{'target':target,'events':[{'event':'input','text':text},{'event':'enter'}]}
                for target,text in (('status','Stopped'),('status-low','Quiet'),
                                    ('status-medium','Usual'),('status-high','Fast'))]
            issued=self.issued(family,controls)
            record,_,receipt=self.project(issued)
            with self.subTest(family=family):
                self.assertEqual([row['control_class'] for row in receipt['histories']],['ComboBoxStaticText']*4)
                self.assertEqual([receipt['static_names'][record[offset]] for offset in (10,11,12,13)],
                                 ['Stopped','Quiet','Usual','Fast'])
                self.assertEqual(record[1]&15,5)
                self.assertEqual([row['control']['binding_callbacks'][0]['action'] for row in receipt['histories']],
                                 ['WriteValue']*4)

    def test_static_full_names_reuse_and_keep_old_reference_reserved(self):
        text='\U0001f600'*32
        for family in PROFILES:
            with scope():
                initialize(self.source)
                selected=PROFILES[family]
                issued=self.issued(family,[{'target':'label','type':3,'events':[
                    {'event':'input','text':text},{'event':'leave'}]},
                    {'target':'label','events':[{'event':'leave'}]}])
                record,_,receipt=self.project(issued)
                with self.subTest(family=family):
                    index=record[selected.label_offset]
                    # Source default names remain referenced while the new
                    # assignment allocates: Timer Fan, Shutter Blind, four
                    # MultiLevel statuses, and those statuses plus Fan.
                    expected={'enable':63,'timer':62,'shutter':62,
                              'multilevel':59,'fan':58,'room-courtesy':63}[family]
                    self.assertEqual(index,expected);self.assertEqual(receipt['static_names'][index],text)
                    old_reference={'enable':0,'timer':63,'shutter':63,
                                   'multilevel':0,'fan':59,'room-courtesy':0}[family]
                    self.assertIn(old_reference,receipt['allocations'][0]['used_indices'])
                    self.assertTrue(receipt['allocations'][1]['reused'])
                    self.assertEqual(receipt['allocations'][1]['index'],index)
                    self.assertEqual(current(issued[2]).names[index],text)

    def test_static_extra_known_selection_is_membership_not_guessed_order(self):
        issued=self.issued('fan',[{'target':'status-low','events':[
            {'event':'selected-name','selected_index':17,'name':'Release the Hounds'}]}])
        record,_,receipt=self.project(issued)
        self.assertEqual(receipt['static_names'][record[11]],'Release the Hounds')
        self.assertFalse(receipt['histories'][0]['control']['suggestion_order_inferred'])

    def test_histories_retain_pending_until_explicit_commit_for_both_control_classes(self):
        for family,target in (('enable','label'),('multilevel','status-low')):
            first={'target':target,'events':[{'event':'input','text':'Committed'}]}
            if target=='label': first['type']=3
            issued=self.issued(family,[first,{'target':target,'events':[{'event':'leave'}]}])
            record,_,receipt=self.project(issued)
            with self.subTest(family=family):
                self.assertTrue(receipt['histories'][0]['control']['pending'])
                self.assertFalse(receipt['histories'][1]['control']['pending'])
                self.assertEqual(receipt['static_names'][record[PROFILES[family].label_offset if target=='label' else 11]],'Committed')

    def test_pending_histories_refuse_save_with_no_source_mutation(self):
        for family,target in (('enable','label'),('fan','status-high')):
            item={'target':target,'events':[{'event':'input','text':'Pending'}]}
            if target=='label':item['type']=3
            issued=self.issued(family,[item]);before=dict(issued[2])
            with self.subTest(family=family),self.assertRaisesRegex(EdltError,'pending text'):
                self.project(issued)
            self.assertEqual(issued[2],before)

    def test_refused_projection_keeps_existing_grid_and_pp_before_committed_allocation(self):
        for family in PROFILES:
            for failure in ('pending', 'invalid-choice'):
                with self.subTest(family=family,failure=failure),scope():
                    initialize(self.source)
                    first={'target':'label','type':3,'events':[
                        {'event':'input','text':'Speculative rejected name'},{'event':'leave'}]}
                    if failure=='pending':
                        last={'target':'label','events':[
                            {'event':'input','text':'Pending final text'}]}
                    else:
                        last={'target':'label','type':10,'events':[
                            {'event':'selected-row','index':1,'identity':'unissued-choice','value':1}]}
                    issued=self.issued(family,[first,last])
                    before_values=dict(issued[2])
                    before_names=tuple(current(issued[2]).names)
                    with self.assertRaises(EdltError):
                        self.project(issued)
                    self.assertEqual(issued[2],before_values)
                    self.assertEqual(tuple(current(issued[2]).names),before_names)

    def test_copied_mutated_foreign_or_detached_binding_cannot_issue_authority(self):
        issued=self.issued('enable',[{'target':'label','events':[]}]);binding=issued[1]
        foreign=object()
        for candidate,owner in ((replace(binding),self.owner),(replace(binding,group=43),self.owner),
                                (replace(binding,_owner=foreign),foreign),(binding.as_dict(),self.owner),
                                (binding,foreign),(binding,None)):
            with self.subTest(owner=owner is self.owner),self.assertRaises(EdltError):
                self.project(issued,binding=candidate,owner=owner)

    def test_binding_exact_position_source_operation_and_complete_record(self):
        issued=self.issued('timer',[{'target':'label','events':[]}]);op,_,values,record=issued
        badrecord=bytearray(record);badrecord[31]^=1
        cases=({'number':2},{'values':{**values,'PrimaryApplication':(57,)}},
               {'operation':{**op,'position':2}},{'record':bytes(badrecord)})
        for change in cases:
            with self.subTest(change=list(change)),self.assertRaises(EdltError):self.project(issued,**change)

    def test_same_pp_but_changed_retained_full_name_cache_refuses(self):
        with scope():
            initialize(self.source)
            issued=self.issued('timer',[{'target':'label','events':[]}])
            names=list(current(issued[2]).names);names[63]='Changed only the in-memory full Name'
            adopt_retained_names(issued[2],tuple(names))
            with self.assertRaisesRegex(EdltError,'retained name cache'):self.project(issued)

    def test_secondary_routing_enable_fixed203_and_single_page_position5(self):
        for family in PROFILES:
            issued=self.issued(family,[{'target':'label','events':[]}],position=5,application='secondary')
            record,_,receipt=self.project(issued)
            with self.subTest(family=family):
                self.assertEqual(receipt['binding']['application'],203 if family=='enable' else 57)
                self.assertEqual(record[6],42)

    def test_existing_extended_application_profiles_are_preserved(self):
        for family in ('multilevel','room-courtesy'):
            source={**self.source,'PrimaryApplication':(136,)}
            issued=self.issued(family,[{'target':'label','events':[]}],source=source)
            _,_,receipt=self.project(issued)
            self.assertEqual(receipt['binding']['application'],136)

    def test_actual_panel_choices_and_static_control_schema_refuse_inventions(self):
        for family,control in (('fan',{'target':'status','type':5,'events':[]}),
                ('multilevel',{'target':'status-low','type':5,'events':[]}),
                ('timer',{'target':'status','type':3,'events':[]}),
                ('room-courtesy',{'target':'status','type':1,'events':[]})):
            with self.subTest(family=family),self.assertRaisesRegex(EdltError,'actual panel choices'):
                normalize_controls([control],family=family)
        self.assertEqual(normalize_controls([{'target':'status','type':3,'events':[]}],family='shutter')[0]['type'],3)
        self.assertEqual(normalize_controls([{'target':'status','type':4,'events':[]}],family='timer')[0]['type'],4)

    def test_static_ordinal_async_caller_modes_and_json_state_refuse(self):
        for control in ({'target':'label','type':3,'events':[{'event':'selected-row','index':0,'identity':'static:0','value':0}]},
                        {'target':'label','events':[{'event':'set-editable','value':False}]},
                        {'target':'label','events':[],'state':{}},
                        {'target':'label','type':3,'events':[{'event':'list-refresh','change_type':'reset',
                            'new_index':0,'old_index':-1,'selected_index':1,'invoke_required':True}]}):
            with self.subTest(control=control),self.assertRaises(EdltError):self.project(self.issued('enable',[control]))

    def test_unassigned_group_and_unknown_image_fact_refuse(self):
        op,_,values,record=self.issued('enable',[{'target':'label','events':[]}])
        for rows in ((('0','Unknown',None),),[('0','Untyped',False)],(('1','Wrong',False),)):
            with self.subTest(rows=rows),self.assertRaises(EdltError):
                issue_app_group_label_binding(self.owner,operation_number=1,application=203,group=42,
                    source_values=values,operation=op,dynamic_rows=rows)
        with self.assertRaisesRegex(EdltError,'group255'):
            issue_app_group_label_binding(self.owner,operation_number=1,application=203,group=255,
                source_values=values,operation=op,dynamic_rows=ROWS)


if __name__ == '__main__': unittest.main()
