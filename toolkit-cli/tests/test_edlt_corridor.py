"""Source-grounded Corridor control rules, preserved phases and guarded staging."""
from dataclasses import replace
import unittest
from unittest.mock import patch
from cbus_toolkit.edlt import EdltError, EdltApplyError
from cbus_toolkit.edlt_corridor import (EdltCorridor, CorridorEdit, CorridorSelectionError,
    CorridorConflictError, FIELDS)
from cbus_toolkit.edlt_lifecycle import LifecycleCache, LifecycleGroup, LifecycleMetadataError
from cbus_toolkit.edlt_application_cache import ApplicationCache, CachedDisplay, CachedGroupList
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from tests.test_edlt import Session
from tests.test_edlt_lifecycle import fixture as lifecycle_fixture, scene_values


def fixture():
    old=lifecycle_fixture(); parameters=dict(old.parameters)
    for name,address,bits,default in (('CorridorLinkingLinkGroup',0x132,8,255),
        ('CorridorLinkingOfficeGroup',0x133,8,255),('CorridorLinkingCorridorTime',0x134,16,300),
        ('CorridorLinkingCorridorGroup',0x136,8,255)):
        parameters[name]=ParameterSpec(name,'int','synthetic.xml',{'Name':name,'Type':'int',
            'Address':hex(address),'BitSize':str(bits),'DefaultValue':str(default)})
    return UnitSpec(old.filename,old.metadata,old.sources,parameters)


def cache(*, mode='complete', order=(255,0,1,2,12,42,254)):
    apps=(56,57,127,136,172,202,203,255)
    if mode.startswith('missing-app'):apps=tuple(a for a in apps if a!=int(mode[11:]))
    groups=[]; lists=[]
    for a in apps:
        actual=tuple(g for g in order if not(mode=='missing-group0' and a==56 and g==0))
        lists.append(CachedGroupList(a,True,tuple(CachedDisplay(g,'Owned group'+str(g),'Owned group'+str(g)) for g in actual)))
        for g in (*order,99):
            present=g in actual
            images=None if mode=='dynamic-null' and a==56 and g==42 else () if g==255 or mode=='dynamic-empty' and a==56 and g==42 else (False,)*4
            groups.append(LifecycleGroup(a,g,present,images if present else None,present,
                                         (0,1,2,42,254,255) if present else None))
    life=LifecycleCache(apps,tuple(groups))
    return ApplicationCache(life,True,tuple(CachedDisplay(a,'Owned application'+str(a),'Owned application'+str(a)) for a in apps),tuple(lists))


def edits(*pairs):return tuple(CorridorEdit(*pair) for pair in pairs)


class CorridorTests(unittest.TestCase):
    def setUp(self):
        self.spec=fixture();self.editor=EdltCorridor(self.spec);self.session=Session(self.spec)
        self.source=self.editor.snapshot(self.session.values())
        self.active={**self.source,FIELDS['link_group']:(42,),FIELDS['office_group']:(1,),FIELDS['corridor_group']:(2,)}

    def plan(self,source=None,steps=(),metadata=None):
        return self.editor.plan(self.active if source is None else source,cache=cache() if metadata is None else metadata,edits=steps)

    def test_original_timer_initial_validation_and_changed_byte_clamp(self):
        for initial,wanted,display in ((0,60,60),(59,60,60),(60,60,60),(300,300,300),
                (64799,64799,64799),(64800,64800,64800),(64801,255,64800),(65535,255,64800)):
            plan=self.plan({**self.active,FIELDS['seconds']:(initial,)})
            self.assertEqual(plan.before_save[FIELDS['seconds']],(wanted,))
            self.assertEqual(plan.as_dict()['timer']['displayed_seconds'],display)
        for initial in (254,300):
            for requested in (255,256,300):
                plan=self.plan({**self.active,FIELDS['seconds']:(initial,)},edits(('seconds',requested)))
                self.assertEqual(plan.before_save[FIELDS['seconds']],(300 if initial==requested==300 else 255,))
                self.assertEqual(plan.as_dict()['timer']['displayed_seconds'],requested)
        plan=self.plan(self.source,edits(('seconds',0)))
        self.assertEqual(plan.as_dict()['timer']['stored_seconds'],60)
        self.assertTrue(plan.as_dict()['timer']['enabled'])

    def test_ordered_choices_disabled_controls_and_duplicate_raw_preservation(self):
        plan=self.plan(steps=edits(('office_group',255),('link_group',1),('corridor_group',42),('office_group',2)))
        self.assertEqual(plan.as_dict()['corridor'],dict(link_group=1,office_group=2,corridor_group=42,seconds=300))
        for field,value in (('link_group',1),('office_group',42),('corridor_group',99)):
            with self.assertRaises(CorridorSelectionError):self.plan(steps=edits((field,value)))
        with self.assertRaises(CorridorSelectionError):self.plan(self.source,edits(('office_group',0)))
        source={**self.active,FIELDS['office_group']:(42,),FIELDS['corridor_group']:(42,)}
        plan=self.plan(source)
        for role in ('link_group','office_group','corridor_group'):
            self.assertEqual(plan.after_controls[FIELDS[role]],(42,));self.assertIsNone(plan.as_dict()['controls'][role]['selected'])
        plan=self.plan(source,edits(('link_group',255)))
        self.assertFalse(plan.as_dict()['controls']['office_group']['enabled'])
        self.assertEqual(plan.after_controls[FIELDS['office_group']],(42,))

    def test_missing_cached_roles_are_distinct_from_excluded_choices(self):
        source={**self.active,**{FIELDS[r]:(99,) for r in ('link_group','office_group','corridor_group')}}
        plan=self.plan(source,edits(('link_group',42),('office_group',1),('corridor_group',2)))
        shown=plan.as_dict()['control_stages'][1]['roles']
        self.assertEqual([shown[r]['stored'] for r in shown],[255,255,255])
        self.assertEqual(plan.as_dict()['corridor']['link_group'],42)
        source={**self.source,FIELDS['office_group']:(99,),FIELDS['corridor_group']:(99,)}
        plan=self.plan(source)
        self.assertEqual(plan.after_controls[FIELDS['office_group']],(255,))
        self.assertEqual(plan.after_controls[FIELDS['corridor_group']],(255,))

    def test_model_aware_conflicts_secondary_enable_scene_and_hidden_models(self):
        for kind in (2,3,4,5,15,16):
            source={**self.active,'Widget6WidgetType':(kind,),'Widget6WidgetByteValue6':(42,)}
            with self.assertRaises(CorridorConflictError):self.plan(source)
            plan=self.plan({**source,'Widget6WidgetByteValue1':(128,)})
            self.assertEqual(plan.as_dict()['key_function_groups'][0]['application'],57)
            with self.assertRaises(CorridorConflictError):self.plan({**source,'SecondaryApplication':(255,),'Widget6WidgetByteValue1':(128,)})
        plan=self.plan({**self.active,'Widget6WidgetType':(14,),'Widget6WidgetByteValue6':(42,)})
        self.assertEqual(plan.as_dict()['key_function_groups'][0]['application'],203)
        for kind in (6,17,127,254):
            self.assertEqual(self.plan({**self.active,'Widget6WidgetType':(kind,),'Widget6WidgetByteValue6':(42,)}).as_dict()['key_function_groups'],[])
        plan=self.plan({**self.active,'Widget6WidgetType':(255,),'Widget7WidgetType':(2,), 'Widget7WidgetByteValue6':(42,)})
        self.assertEqual(plan.as_dict()['key_function_groups'],[])
        plan=self.plan({**self.active,'Widget6WidgetType':(3,),'Widget6WidgetByteValue6':(99,)})
        self.assertEqual(plan.after_controls['Widget6WidgetByteValue6'],(99,))
        self.assertEqual(plan.as_dict()['key_function_groups'],[])

    def test_full_lifecycle_retains_scene_state_mra_and_recalculates_five_crcs(self):
        source={**self.active,**scene_values((3,1,42,2,26),((17,12,123),)),
            'Widget1WidgetType':(9,),'Widget1WidgetByteValue1':(0xed,),
            'Widget6WidgetType':(2,),'Widget6WidgetByteValue6':(12,),
            'Widget7WidgetType':(6,),'Widget8WidgetType':(7,),'Widget8WidgetByteValue1':(0x12,)}
        base=self.editor.lifecycle.plan(source,metadata=cache().lifecycle)
        plan=self.plan(source,edits(('link_group',0),('seconds',256)))
        self.assertEqual({k:v for k,v in plan.before_save.items() if k not in FIELDS.values()},
                         {k:v for k,v in base.before_save.items() if k not in FIELDS.values()})
        self.assertEqual(plan.before_save['Widget8WidgetByteValue1'],(0xea,))
        self.assertEqual(plan.before_save['SceneBucket'][:8],(3,1,42,2,26,17,12,123))
        final={**plan.expected,**plan.changes};self.assertEqual({k:final[k] for k in self.editor.crcs(final)},self.editor.crcs(final))
        self.assertEqual(len(self.editor.crcs(final)),5)
        self.assertFalse(plan.as_dict()['full_form_initialization_verified'])
        self.assertFalse(plan.as_dict()['physical_device_verified'])

    def test_cache_order_duplicate_names_unknown_and_incomplete_facts(self):
        original=cache(order=(42,255,12,0,2,1,254));lists=list(original.group_lists)
        lists[0]=replace(lists[0],groups=tuple(replace(g,name='same',formatted_display='same') for g in lists[0].groups))
        plan=self.plan(metadata=replace(original,group_lists=tuple(lists)))
        self.assertEqual([g['address'] for g in plan.as_dict()['controls']['link_group']['choices']],[255,42,12,0,254])
        for bad in (replace(original,group_lists=tuple(replace(g,complete=False) for g in original.group_lists)),cache(mode='missing-app56')):
            with self.assertRaises(LifecycleMetadataError):self.plan(metadata=bad)
        unknown=replace(original.lifecycle,groups=tuple(g for g in original.lifecycle.groups if not(g.application==56 and g.group==99)))
        with self.assertRaises(LifecycleMetadataError):self.plan({**self.active,'Widget6WidgetType':(3,),'Widget6WidgetByteValue6':(99,)},metadata=replace(original,lifecycle=unknown))

    def test_invalid_actions_layout_forged_stale_identity_before_writes(self):
        for field,value in (('bad',1),('seconds',True),('seconds',-1),('seconds',65536),('link_group',256),('link_group','1')):
            with self.assertRaises(EdltError):CorridorEdit(field,value)
        for bad in ({},[{'field':'seconds','value':1,'extra':1}],[{'field':True,'value':1}], [CorridorEdit('seconds',60)]*65):
            with self.assertRaises(EdltError):self.plan(steps=bad)
        parameters=dict(self.spec.parameters);name=FIELDS['seconds'];parameters[name]=replace(parameters[name],fields={**parameters[name].fields,'BitSize':'8'})
        with self.assertRaises(EdltError):EdltCorridor(replace(self.spec,parameters=parameters))
        plan=self.plan(self.source,edits(('seconds',256)))
        for bad in (replace(plan,evidence='{}'),replace(plan,changes={**plan.changes,FIELDS['seconds']:(1,)})):
            with self.assertRaises(EdltError):self.editor.apply(self.session,bad)
        zero='Widget1WidgetByteValue31'
        for phase in ('expected','after_load','after_controls','before_save'):
            original=getattr(plan,phase);self.assertEqual(original[zero],(0,))
            forged=replace(plan,**{phase:{**original,zero:(False,)}})
            with self.subTest(phase=phase),self.assertRaises(EdltError):self.editor.apply(self.session,forged)
        with self.assertRaises(EdltError):
            self.editor.apply(self.session,replace(plan,changes={**plan.changes,zero:(False,)}))
        self.assertEqual(self.session.calls,[])
        self.session.current[FIELDS['seconds']]='0'
        with self.assertRaisesRegex(EdltError,'changed since'):self.editor.apply(self.session,plan)
        self.session.current=dict(plan.expected);self.session.source='//REAL/254/p/20'
        with self.assertRaisesRegex(EdltError,'database'):self.editor.apply(self.session,plan)
        self.session.source='/db//EDLTTEST/254/p/20';self.assertTrue(self.editor.apply(self.session,plan)['verified'])

    def test_rollback_disconnection_and_original_interruptions(self):
        plan=self.plan(self.source,edits(('seconds',256)));self.session.failure=next(iter(plan.changes))
        with self.assertRaises(EdltApplyError) as caught:self.editor.apply(self.session,plan)
        self.assertTrue(caught.exception.as_dict()['rollback_verified']);self.assertEqual(self.editor.snapshot(self.session.values()),dict(plan.expected))
        for error in (KeyboardInterrupt('first'),SystemExit(4)):
            attempts=[]
            def interrupt(name,value):attempts.append(name);raise error
            self.session.set=interrupt
            with self.assertRaises(type(error)) as caught:self.editor.apply(self.session,plan)
            self.assertIs(caught.exception,error);self.assertEqual(len(attempts),1)
            self.assertEqual(error.edlt_corridor_evidence['attempted_parameters'],attempts)
        attempts=[]
        def disconnect(name,value):attempts.append(name);self.session.connected=False;raise RuntimeError('lost stream')
        self.session.set=disconnect
        with self.assertRaises(EdltApplyError) as caught:self.editor.apply(self.session,plan)
        self.assertEqual(len(attempts),1);self.assertFalse(caught.exception.as_dict()['rollback_verified'])
        self.assertIn('Connection lost',caught.exception.as_dict()['rollback_errors'][0])
        class Unprintable(RuntimeError):
            def __str__(self):raise SystemExit('secondary message failure')
        cause=Unprintable();cause.cgate_cleanup_errors=(KeyboardInterrupt('secondary close'),)
        self.session.connected=True;attempts.clear()
        def unprintable(name,value):attempts.append(name);self.session.connected=False;raise cause
        self.session.set=unprintable
        with self.assertRaises(EdltApplyError) as caught:self.editor.apply(self.session,plan)
        self.assertIs(caught.exception.__cause__,cause);self.assertEqual(len(attempts),1)
        self.assertEqual(caught.exception.as_dict()['error'],'<unprintable Unprintable>')
        self.assertIs(caught.exception.cgate_cleanup_errors,cause.cgate_cleanup_errors)
        first=KeyboardInterrupt('first');second=SystemExit('secondary export')
        with patch.object(type(plan),'as_dict',side_effect=second):
            evidence=self.editor._interrupted(first,plan,('one',))
        self.assertIs(first.edlt_corridor_evidence,evidence)
        self.assertFalse(evidence['evidence_export_complete'])
