"""Retained Blank transition, phase guards and interruption evidence."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from cbus_toolkit.edlt import EdltError, EdltApplyError
from cbus_toolkit.edlt_blank import EdltBlankWidget
from cbus_toolkit.edlt_lifecycle import EdltLifecycle, BlankedEdlt
from tests.test_edlt import Session
from tests.test_edlt_lifecycle import fixture, cache, scene_values


class BlankTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture(); self.editor = EdltBlankWidget(self.spec); self.session = Session(self.spec)
        self.values = self.editor.snapshot(self.session.values())
        self.values.update({'NavWidgetType': (1,), 'Widget6WidgetType': (2,),
            'Widget6WidgetByteValue6': (42,), 'Widget6RestoreLevel': (73,),
            'Widget6WidgetByteValue31': (171,), 'Widget7WidgetType': (2,),
            'Widget7WidgetByteValue6': (12,), 'Widget7RestoreLevel': (83,)})
        self.session.current = dict(self.values)

    def metadata(self, values=None, mode='complete'):
        return cache(self.editor.lifecycle, self.values if values is None else values, mode)

    def plan(self, values=None, **kwargs):
        source = self.values if values is None else values
        return self.editor.plan(source, metadata=self.metadata(source), **dict({"page":1, "position":1}, **kwargs))

    def test_changed_type_resets_restore_and_preserves_opaque_bytes(self):
        plan = self.plan()
        self.assertEqual(plan.after_load['Widget6RestoreLevel'], (73,))
        self.assertEqual(plan.after_controls['Widget6RestoreLevel'], (0,))
        self.assertEqual(plan.after_controls['Widget6WidgetByteValue31'], (171,))
        self.assertEqual(set(plan.as_dict()['phases']['controls']), {'Widget6WidgetType','Widget6RestoreLevel'})
        self.assertTrue(plan.type_changed)
        self.assertEqual(plan.before_save['Widget6WidgetByteValue12'], (0,))
        self.assertFalse(plan.as_dict()['physical_factory_reset_performed'])

    def test_same_blank_keeps_restore_and_model_identity(self):
        source = {**self.values, 'Widget6WidgetType': (0,)}
        life = self.editor.lifecycle; loaded = life.load(source, metadata=self.metadata(source))
        edited = life.blank_widget(loaded, 6)
        self.assertIsInstance(edited, BlankedEdlt)
        self.assertIs(edited.widgets, loaded.widgets)
        self.assertIs(edited.widgets[5], loaded.widgets[5])
        self.assertEqual(edited.after_controls['Widget6RestoreLevel'], (73,))
        self.assertFalse(edited.type_changed)
        self.assertEqual(self.plan(source).as_dict()['phases']['controls'], {})

    def test_engine_retains_scenes_private_actions_and_original_mra(self):
        source = {**self.values, **scene_values((3,1,42,2,26), ((0xf1,12,123),)),
                  'Widget6WidgetType': (7,), 'Widget6WidgetByteValue1': (0xed,),
                  'Widget7WidgetType': (8,), 'Widget7WidgetByteValue1': (0x12,)}
        life = self.editor.lifecycle; loaded = life.load(source, metadata=self.metadata(source,'missing-level2'))
        edited = life.blank_widget(loaded, 6)
        self.assertIs(edited.base, loaded)
        self.assertIs(edited.widgets[6], loaded.widgets[6]); self.assertIsNot(edited.widgets[5], loaded.widgets[5])
        self.assertEqual(loaded.scenes[0].action_selector, -1)
        with patch.object(life, 'load', side_effect=AssertionError('second load')), \
             patch.object(type(loaded.metadata), 'find', side_effect=AssertionError('group re-resolution')):
            saved = life.prepare_save(edited)
        self.assertEqual(saved.expected, loaded.expected); self.assertEqual(saved.after_load, loaded.after_load)
        self.assertEqual(saved.before_save['Widget7WidgetByteValue1'], (0xea,))
        self.assertEqual(saved.before_save['SceneBucket'][3], 0)
        self.assertEqual(loaded.scenes[0].action_selector, -1)
        self.assertIs(loaded.scenes[0].items[0].group, loaded.metadata.find(57,12))

    def test_owner_receipts_reject_replaced_cross_editor_and_chained_states(self):
        life = self.editor.lifecycle; loaded = life.load(self.values, metadata=self.metadata())
        edited = life.blank_widget(loaded, 6)
        for bad in (replace(loaded), loaded.as_dict()):
            with self.assertRaises(EdltError): life.blank_widget(bad,6)
        for bad in (replace(edited), replace(edited,base=replace(loaded)), edited.as_dict()):
            with self.assertRaises(EdltError): life.prepare_save(bad)
        with self.assertRaises(EdltError): EdltLifecycle(self.spec).prepare_save(edited)
        with self.assertRaises(EdltError): life.blank_widget(edited,7)
        for bad in (True,False,0,22,1.0,'6'):
            with self.assertRaises(EdltError): life.blank_widget(loaded,bad)
        with self.assertRaises(TypeError): edited.after_controls['NavWidgetType']=(0,)

    def test_layout_slots_and_navigation_position(self):
        for page in range(1,5):
            for position in range(1,5):
                self.assertEqual(self.plan(page=page,position=position).slot,6+(page-1)*4+position-1)
        for position in range(1,6):
            self.assertEqual(self.plan(page=0,position=position).slot,position)
            self.assertEqual(self.plan({**self.values,'NavWidgetType':(0,)},position=position).slot,5+position)
        for args in ({'page':True},{'position':False},{'page':5},{'position':0},{'position':5}):
            with self.assertRaises(EdltError):self.plan(**args)
        with self.assertRaises(EdltError):self.plan({**self.values,'NavWidgetType':(0,)},page=2)
        for bad in (2,255):
            with self.assertRaisesRegex(EdltError,'canonical'):self.plan({**self.values,'NavWidgetType':(bad,)})

    def test_standby_overlap_and_leader_clear_preserves_neighbor(self):
        source={**self.values,'Widget1WidgetType':(11,),'Widget2WidgetType':(13,),
                'Widget2WidgetByteValue31':(199,)}
        with self.assertRaisesRegex(EdltError,'covered'):self.plan(source,page=0,position=2)
        plan=self.plan(source,page=0,position=1)
        self.assertEqual(plan.after_controls['Widget1WidgetType'],(0,))
        self.assertEqual(plan.after_controls['Widget2WidgetType'],(13,))
        self.assertEqual(plan.after_controls['Widget2WidgetByteValue31'],(199,))

    def test_last_functional_blank_becomes_end_marker(self):
        source={**self.values,'Widget7WidgetType':(0,),'Widget7RestoreLevel':(83,)}
        plan=self.plan(source)
        self.assertEqual(plan.after_controls['Widget6WidgetType'],(0,))
        self.assertEqual(plan.before_save['Widget6WidgetType'],(255,))
        self.assertEqual(plan.before_save['Widget7RestoreLevel'],(83,))
        self.assertEqual(plan.as_dict()['stored_type_after_save'],255)

    def test_unknown_model_clear_and_legacy_load_are_distinct(self):
        plan=self.plan({**self.values,'Widget6WidgetType':(127,)})
        self.assertEqual(plan.as_dict()['source_model_family'],'BlankData');self.assertTrue(plan.type_changed)
        plan=self.plan({**self.values,'Widget6WidgetType':(1,)})
        self.assertEqual(plan.after_load['Widget6RestoreLevel'],(0,));self.assertFalse(plan.type_changed)

    def test_forged_plan_phases_boolean_and_stale_guard_before_writes(self):
        plan=self.plan()
        for phase in ('expected','after_load','after_controls','before_save'):
            values=dict(getattr(plan,phase));values['Widget6WidgetByteValue31']=(True,)
            with self.assertRaises(EdltError):self.editor.apply(self.session,replace(plan,**{phase:values}))
        for args in ({'type_changed':1},{'slot':True},{'changes':{**plan.changes,'Widget6WidgetType':(False,)}},
                     {'evidence':'{}'},{'position':2}):
            with self.assertRaises(EdltError):self.editor.apply(self.session,replace(plan,**args))
        self.assertEqual(self.session.calls,[])
        self.session.current['Widget6WidgetByteValue31']=(172,)
        with self.assertRaisesRegex(EdltError,'changed since'):self.editor.apply(self.session,plan)
        self.assertEqual(self.session.calls,[])

    def test_apply_readback_rollback_and_identity(self):
        plan=self.plan();result=self.editor.apply(self.session,plan)
        self.assertTrue(result['verified']);self.assertFalse(result['saved'])
        self.assertEqual(self.editor.snapshot(self.session.values()),{**plan.expected,**plan.changes})
        self.session.current=dict(self.values);self.session.calls=[];self.session.failure=next(iter(plan.changes))
        with self.assertRaises(EdltApplyError) as caught:self.editor.apply(self.session,plan)
        self.assertEqual(caught.exception.rollback_errors,())
        self.assertEqual(self.editor.snapshot(self.session.values()),self.values)
        self.session.current=dict(self.values);self.session.calls=[];self.session.identity['UnitType']='KEY4'
        with self.assertRaises(EdltError):self.editor.configure(self.session,metadata=self.metadata(),page=1,position=1)
        self.assertEqual(self.session.calls,[])

    def test_configure_clears_previous_evidence_before_preflight(self):
        for mode in ('identity','cache','layout'):
            with self.subTest(mode=mode):
                self.session=Session(self.spec);self.session.current=dict(self.values)
                previous=self.editor.configure(self.session,metadata=self.metadata(),page=1,position=1)
                self.assertTrue(previous['verified']);self.assertIs(self.editor.last_evidence,previous)
                self.session.current=dict(self.values);self.session.calls=[]
                options={'metadata':self.metadata(),'page':1,'position':1}
                if mode=='identity':self.session.identity['UnitType']='KEY4'
                elif mode=='cache':options['metadata']={}
                else:options['position']=5
                with self.assertRaises(EdltError):self.editor.configure(self.session,**options)
                self.assertIsNone(self.editor.last_evidence);self.assertEqual(self.session.calls,[])

    def test_interrupt_preserves_identity_and_unattachable_fallback_without_recovery(self):
        class Unattachable(KeyboardInterrupt):
            def __setattr__(self,name,value):raise RuntimeError('attributes rejected')
        for error in (KeyboardInterrupt('stop'),SystemExit(7),Unattachable()):
            self.session.current=dict(self.values);self.session.calls=[]
            def stop(name,value):self.session.calls.append((name,value));raise error
            with patch.object(self.session,'set',side_effect=stop):
                with self.assertRaises(type(error)) as caught:self.editor.apply(self.session,self.plan())
            self.assertIs(caught.exception,error);self.assertEqual(len(self.session.calls),1)
            self.assertEqual(self.editor.last_evidence['attempted_parameters'],[self.session.calls[0][0]])
            self.assertFalse(self.editor.last_evidence['saved'])

    def test_disconnection_stops_rollback_and_preserves_cause(self):
        self.session.connected=True;error=OSError('stream lost')
        def stop(name,value):self.session.calls.append((name,value));self.session.connected=False;raise error
        with patch.object(self.session,'set',side_effect=stop):
            with self.assertRaises(EdltApplyError) as caught:self.editor.apply(self.session,self.plan())
        self.assertIs(caught.exception.cause,error);self.assertEqual(len(self.session.calls),1)
        self.assertIn('Connection lost',caught.exception.rollback_errors[0])


class OriginalBlankPlacementTests(unittest.TestCase):
    def test_original_filtered_rows_and_two_slice_exclusions(self):
        import hashlib,json
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        data=json.loads((root/'research/fixtures/edlt-blank-placements.json').read_text())
        self.assertTrue(data['source_unchanged']);self.assertEqual(len(data['placements']),7);self.assertEqual(len(data['covered']),4)
        self.assertEqual(hashlib.sha256((root/'research/NativeEdltBlankPlacementProbe.cs').read_bytes()).hexdigest(),data['source_before']['probe.cs'])
        for row in data['placements']:
            source={'NavWidgetType':(row['mode'],),**{f'Widget{i}WidgetType':(0,) for i in range(1,22)}}
            observed=[]
            for position in range(1,6):
                if row['page']>0 and row['mode']==1 and position==5:
                    with self.assertRaisesRegex(EdltError,'navigation'):EdltBlankWidget._slot(source,row['page'],position)
                    observed.append(-1)
                else:observed.append(EdltBlankWidget._slot(source,row['page'],position))
            self.assertEqual(observed,row['slots'])
        for row in data['covered']:
            source={'NavWidgetType':(1,),**{f'Widget{i}WidgetType':(0,) for i in range(1,22)},f'Widget{row["leader"]}WidgetType':(11,)}
            observed=[]
            for position in range(1,6):
                if position==row['leader']+1:
                    with self.assertRaisesRegex(EdltError,'covered'):EdltBlankWidget._slot(source,0,position)
                else:observed.append(EdltBlankWidget._slot(source,0,position))
            self.assertEqual(observed,row['slots'])


if __name__=="__main__":unittest.main()
