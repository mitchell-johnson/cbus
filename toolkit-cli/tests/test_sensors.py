"""Independent sensor event vectors, binary mappings and closed native PP tests."""
from dataclasses import replace
from html import unescape
import json
import os
from pathlib import Path
import re
import struct
import unittest
from uuid import uuid4

from cbus_toolkit.sensors import (LAYOUTS, PROFILE, Multisensor, SensorError, SensorApplyError,
                                  margin_percent, profile_refusal, saved_margin)
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore
from test_macros import Session


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / 'docs/sensor-profile-review.json'
MARGIN_VECTORS = ROOT / 'research/fixtures/sensor-margin-original-vectors.json'
# Newly admitted firmware/catalogue boundaries plus the retained 2.3.00 case.
NATIVE_PROFILES = (('2.0.01','5753PEIRL'),('2.1.00','SLC5753PEIRL'),('2.2.00','5753PEIRL'),
                   ('2.3.00','5753PEIRL'),('2.3.9','SLC5753PEIRL'))
# Layout-identical types refused for their Toolkit class, a registration gap,
# and neighbouring profiles whose layout differs or is a superset.
NATIVE_REFUSED = (('SENPIROA','2.3.00','5750WPL',True),('SENPIROA','2.4.00','5750WPL',True),
                  ('SENPIRIA','2.3.00','5751L',True),('SENPIRIA','2.4.00','5751L',True),
                  ('SENPIRIB','2.3.00','5753L',True),('SENLL','2.3.00','5031PE',True),
                  ('SENPILL','2.3.10','5753PEIRL',True),('SENPILL','2.0.00','5753PEIRL',False),
                  ('SENPILL','2.4.00','5753PEIRL',False),('SENPILLA','2.4.00','5754ODPEIR',False),
                  ('SENPIRIC','2.4.00','5754ODPE',False),('SENPIRIB','2.4.00','5753L',False))
VECTORS = {'day': (7,0,0,0), 'night': (13,7,7,0), 'any': (13,7,0,7),
           'sunset': (13,15,7,15), 'disabled': (0,0,0,0)}
STAGES = ('JPCommand','SRCommand','LPCommand','LRCommand')


def fixture():
    rows = [
        ('JPCommand',104,8,4,4,1,[7,13,13,0,0,0,0,0]),
        ('SRCommand',104,8,4,0,1,[0,7,15,0,0,0,0,0]),
        ('LPCommand',105,8,4,4,1,[0,7,7,0,0,0,0,0]),
        ('LRCommand',105,8,4,0,1,[0,0,15,0,0,0,0,0]),
        ('BlockAllocation',54,8,8,0,0,[2,2,4,8,16,32,64,128]),
        ('GroupAddress',80,8,8,0,0,[255]*8), ('Application',33,2,8,0,0,[56,255]),
        ('SecondApplicationBlocks',69,1,8,0,0,[0]), ('SceneKeySelector',96,8,1,7,0,[0]*8),
        ('TimerHighByte',136,8,8,0,0,[1]*8), ('TimerLowByte',144,8,8,0,0,[44]*8),
        ('TimerExpiryCommand',72,8,4,0,0,[15]*8), ('BlockBankSwitchActive',72,8,1,5,0,[0]*8),
        ('PIRLightMovement',50,1,8,0,0,[1]), ('PIRDarkMovement',51,1,8,0,0,[2]),
        ('PIRDark',52,1,8,0,0,[4]), ('PECTargetLux',27,1,8,0,0,[70]),
        ('PECMarginLux',28,1,8,0,0,[4]), ('PIREnablerGroup',88,1,8,0,0,[255]),
        ('PIREnablerGroupLogic',99,1,1,6,0,[0]), ('SingleJoinEnablerGroup',90,1,8,0,0,[255]),
        ('DualJoinEnablerGroup',91,1,8,0,0,[255]), ('PECFunctionActive',96,1,1,6,0,[0]),
        ('PECFunctionBlock',96,1,3,3,0,[0]), ('BroadcastActive',70,1,3,5,0,[0]),
        ('BroadcastBlock',70,1,3,0,0,[0]), ('PotentiometerAFunction',101,1,2,3,0,[1]),
        ('PotentiometerBFunction',101,1,2,5,0,[0]), ('PotentiometerATimerBlock',102,1,3,3,0,[0]),
        ('PotentiometerBTimerBlock',103,1,3,3,0,[0])]
    parameters={}
    for name,address,count,bits,bit,skip,values in rows:
        kind='bit' if name in ('PIREnablerGroupLogic','PECFunctionActive') else 'int'
        fields={'Name':name,'Type':kind,'Address':str(address),'ArraySize':str(count),
                'BitSize':str(bits),'BitAddress':str(bit),'ArraySkip':str(skip),
                'DefaultValue':' '.join(map(str,values))}
        parameters[name]=ParameterSpec(name,kind,'literal-sensor-fixture.xml',fields)
    return UnitSpec('SENPILL_ST7.xml',{'Type':'SENPILL'},('literal-sensor-fixture.xml',),parameters)


class SensorTest(unittest.TestCase):
    def setUp(self):
        self.spec=fixture();self.sensor=Multisensor(self.spec)

    def test_every_event_all_keys_masks_and_stage_bytes(self):
        for key in range(1,9):
            for event,vector in VECTORS.items():
                with self.subTest(key=key,event=event):
                    plan=self.sensor.plan(self.spec.defaults(),key=key,event=event,block=key,group=17,
                                          allow_shared_block=True)
                    values=dict(plan.expected);values.update(plan.changes);bit=1<<(key-1)
                    self.assertEqual(values['PIRLightMovement'][0],1|bit if event in ('day','any') else 1&~bit)
                    self.assertEqual(values['PIRDarkMovement'][0],2|bit if event in ('night','any') else 2&~bit)
                    self.assertEqual(values['PIRDark'][0],4|bit if event=='sunset' else 4&~bit)
                    self.assertEqual(tuple(values[n][key-1] for n in STAGES),vector)
                    encoded=self.sensor.codec.encode_many({n:values[n]for n in STAGES}).apply(MemoryImage.from_bytes(b'\xa5'*256))
                    self.assertEqual(encoded.read(104+(key-1)*2,2),bytes((vector[0]<<4|vector[1],vector[2]<<4|vector[3])))

    def test_bank_and_scene_bits_cleared_without_neighbor_damage(self):
        current=self.spec.defaults();current['BlockBankSwitchActive']='1 1 1 1 1 1 1 1';current['SceneKeySelector']='1 1 1 1 1 1 1 1'
        plan=self.sensor.plan(current,key=3,event='night',group=17,timer_seconds=300,expiry='ramp_off')
        self.assertEqual(plan.changes['BlockBankSwitchActive'],(1,1,0,1,1,1,1,1))
        self.assertEqual(plan.changes['SceneKeySelector'],(1,1,0,1,1,1,1,1))
        memory=self.sensor.codec.encode_many(plan.changes).apply(MemoryImage.from_bytes(b'\xff'*256))
        self.assertEqual(memory.read(74,1),b'\xd9')
        self.assertEqual(memory.read(98,1),b'\x7f')

    def test_shared_day_night_timer_requires_explicit_shared_edit(self):
        with self.assertRaisesRegex(SensorError,'shared'):
            self.sensor.plan(self.spec.defaults(),key=2,event='night',group=9,timer_seconds=301)
        plan=self.sensor.plan(self.spec.defaults(),key=2,event='night',group=9,timer_seconds=301,allow_shared_block=True)
        self.assertEqual(plan.shared_keys,(1,));self.assertEqual(plan.block,2)
        self.assertEqual(plan.changes['TimerLowByte'][1],45)
        self.assertNotIn('BlockAllocation',plan.changes)

    def test_threshold_exact_steps_x87_margin_and_pot_dependency(self):
        with self.assertRaisesRegex(SensorError,'potentiometer'):
            self.sensor.plan(self.spec.defaults(),target_lux=450,margin_percent=10)
        # 500 lux at 59% and 1900 lux at 15%: the original x87 save gives 29; exact half-even gives 30 and 28.
        for lux,percent,target,margin in ((450,10,45,4),(550,10,55,6),(500,59,50,29),(1900,15,190,29),
                                          (2550,100,255,255),(0,0,0,0)):
            plan=self.sensor.plan(self.spec.defaults(),target_lux=lux,margin_percent=percent,disable_potentiometer_override=True)
            result=dict(plan.expected);result.update(plan.changes)
            self.assertEqual(result['PECTargetLux'],(target,));self.assertEqual(result['PECMarginLux'],(margin,))
            self.assertEqual(result['PotentiometerAFunction'],(0,))
        with self.assertRaisesRegex(SensorError,'10-lux'):
            self.sensor.plan(self.spec.defaults(),target_lux=451,margin_percent=10)
        with self.assertRaisesRegex(SensorError,'margin_percent'):
            self.sensor.plan(self.spec.defaults(),target_lux=450)

    def test_timer_pot_does_not_disable_an_unrelated_pot(self):
        current=self.spec.defaults();current['PotentiometerBFunction']='2';current['PotentiometerBTimerBlock']='2'
        with self.assertRaisesRegex(SensorError,'Timer is controlled'):
            self.sensor.plan(current,key=3,event='night',group=9,timer_seconds=65535)
        plan=self.sensor.plan(current,key=3,event='night',group=9,timer_seconds=65535,disable_potentiometer_override=True)
        self.assertEqual(plan.changes['PotentiometerBFunction'],(0,));self.assertNotIn('PotentiometerAFunction',plan.changes)
        self.assertEqual(plan.changes['TimerHighByte'][2],255);self.assertEqual(plan.changes['TimerLowByte'][2],255)

    def test_occupancy_enable_group_polarity_and_clear(self):
        plan=self.sensor.plan(self.spec.defaults(),enable_group=23,enabled_when='off')
        self.assertEqual(plan.changes['PIREnablerGroup'],(23,));self.assertEqual(plan.changes['PIREnablerGroupLogic'],(1,))
        current=dict(plan.expected);current.update(plan.changes)
        self.assertEqual(self.sensor.plan(current,enable_group=255).changes['PIREnablerGroup'],(255,))
        with self.assertRaisesRegex(SensorError,'assigned'):
            self.sensor.plan(self.spec.defaults(),enabled_when='on')
        current=self.spec.defaults();current['Application']='202 255'
        with self.assertRaisesRegex(SensorError,'primary Lighting'):
            self.sensor.plan(current,enable_group=23)

    def test_dependencies_reject_join_broadcast_maintenance_and_secondary_mismatch(self):
        for changes,message in (({'SingleJoinEnablerGroup':'4'},'Join'),({'DualJoinEnablerGroup':'5'},'Join'),
                                ({'BroadcastActive':'4','BroadcastBlock':'2'},'broadcasting'),
                                ({'PECFunctionActive':'1','PECFunctionBlock':'2'},'maintenance'),
                                ({'SecondApplicationBlocks':'4'},'Lighting')):
            current=self.spec.defaults();current.update(changes)
            with self.subTest(changes=changes),self.assertRaisesRegex(SensorError,message):
                self.sensor.plan(current,key=3,event='night',group=1)
        current=self.spec.defaults();current.update({'Application':'56 57','SecondApplicationBlocks':'4'})
        self.sensor.plan(current,key=3,event='night',group=1)

    def test_disabled_event_needs_no_group_and_does_not_erase_timer(self):
        plan=self.sensor.plan(self.spec.defaults(),key=2,event='disabled')
        self.assertEqual(plan.changes['PIRDarkMovement'],(0,));self.assertNotIn('GroupAddress',plan.changes)
        self.assertNotIn('TimerLowByte',plan.changes);self.assertIsNone(plan.block)

    def test_invalid_and_unsupported_inputs(self):
        for options in ({'key':True,'event':'day'},{'key':9,'event':'day'},{'key':1},
                        {'event':'day'},{'key':3,'event':'motion'},{'group':4},
                        {'key':3,'event':'night','group':255},{'target_lux':2560},
                        {'margin_percent':101},{'enable_group':False},{'enabled_when':'unknown'},
                        {'expiry':'ramp_off'},{'allow_shared_block':1}):
            with self.subTest(options=options),self.assertRaises(ValueError):self.sensor.plan(self.spec.defaults(),**options)
        with self.assertRaisesRegex(SensorError,'Assign a Lighting'):
            self.sensor.plan(self.spec.defaults(),key=3,event='night')
        current=self.spec.defaults();current['BlockAllocation']='2 2 3 8 16 32 64 128'
        with self.assertRaisesRegex(SensorError,'multiple-block'):
            self.sensor.plan(current,key=3,event='night',group=1)
        with self.assertRaises(SensorError):Multisensor(replace(self.spec,filename='SENPILLA.xml'))
        for identity in (('SENPILL','2.3.00'),['SENPILL','2.3.00','5753PEIRL'],('SENPIRIA','2.3.00','5751L')):
            with self.subTest(identity=identity),self.assertRaises(SensorError):
                self.sensor.plan(self.spec.defaults(),identity=identity)
        bad=replace(self.spec.get('PIRDark'),fields=dict(self.spec.get('PIRDark').fields,Address='55'))
        with self.assertRaises(SensorError):Multisensor(replace(self.spec,parameters=dict(self.spec.parameters,PIRDark=bad)))

    def session(self):
        session=Session(self.spec);session.firmware='2.3.00';session.catalog_number='5753PEIRL'
        return session

    def test_apply_checks_native_profile_schema_staleness_and_preserves_unrelated(self):
        session=self.session();session.current['Other']='unchanged'
        plan=self.sensor.plan(session.values(),key=3,event='day',group=19)
        result=self.sensor.apply(session,plan)
        self.assertTrue(result['verified']);self.assertFalse(result['saved']);self.assertFalse(result['device_verified'])
        self.assertEqual(session.current['Other'],'unchanged')
        with self.assertRaisesRegex(SensorError,'changed since'):self.sensor.apply(session,plan)
        for field,value in (('firmware','2.4.00'),('firmware','2.3.10'),('firmware','2.0.00'),
                            ('catalog_number','5753L'),('catalog_number',None),('unit_type','SENPIRIB')):
            session=self.session();setattr(session,field,value)
            with self.assertRaisesRegex(SensorError,'Native session'):self.sensor.apply(session,plan)
            self.assertEqual(session.calls,[])

    def test_admitted_firmware_catalogue_range_and_explicit_refusals(self):
        for firmware in ('2.0.01','2.0.99','2.1.00','2.2.50','2.3.00','2.3.09','2.3.9'):
            for catalog in PROFILE['catalog_numbers']:
                with self.subTest(firmware=firmware,catalog=catalog):
                    self.assertIsNone(profile_refusal('SENPILL',firmware,catalog))
        for identity,reason in ((('SENPILL','2.0.00','5753PEIRL'),'outside'),(('SENPILL','2.3.10','5753PEIRL'),'no Toolkit ST7'),
                                (('SENPILL','2.3.99','SLC5753PEIRL'),'outside'),(('SENPILL','2.4.00','5753PEIRL'),'outside'),
                                (('SENPILL','2.3.00a','5753PEIRL'),'outside'),(('SENPILL',None,'5753PEIRL'),'outside'),
                                (('SENPILL','2.3.00','5753L'),'catalogue'),(('SENPILL','2.3.00',None),'catalogue'),
                                (('SENPIROA','2.3.00','5750WPL'),'PIR sensor class'),(('SENPIRIA','2.4.00','5751L'),'PIR sensor class'),
                                (('SENPIRIB','2.3.00','5753L'),'PIR sensor class'),(('SENLL','2.3.00','5031PE'),'light-level'),
                                (('SENPILLA','2.4.00','5754ODPEIR'),'TSENPILLA'),(('SENPIRIC','2.4.00','5754ODPE'),'TSENPIRIC'),
                                (('KEY4','2.3.00','5753PEIRL'),'Only SENPILL')):
            with self.subTest(identity=identity):self.assertIn(reason,profile_refusal(*identity))

    def test_bound_plan_identity_is_reported_and_must_match_the_session(self):
        session=self.session();session.firmware='2.1.00';session.catalog_number='SLC5753PEIRL'
        result=self.sensor.configure(session,key=3,event='day',group=19)
        self.assertEqual((result['firmware'],result['catalog_number']),('2.1.00','SLC5753PEIRL'))
        self.assertEqual(result['firmware_range'],['2.0.01','2.3.9'])
        unbound=self.sensor.plan(self.spec.defaults(),key=3,event='day',group=19)
        self.assertIsNone(unbound.as_dict()['firmware'])
        bound=self.sensor.plan(self.spec.defaults(),key=3,event='day',group=19,identity=('SENPILL','2.3.00','5753PEIRL'))
        session=self.session();session.firmware='2.2.00'
        with self.assertRaisesRegex(SensorError,'another unit'):self.sensor.apply(session,bound)
        self.assertEqual(session.calls,[])
        session=self.session()
        self.assertEqual(self.sensor.apply(session,unbound)['firmware'],'2.3.00')

    def test_partial_failure_does_not_retry_or_save(self):
        session=self.session();session.failure='GroupAddress'
        plan=self.sensor.plan(session.values(),key=3,event='day',group=19)
        with self.assertRaises(SensorApplyError)as error:self.sensor.apply(session,plan)
        self.assertEqual(error.exception.attempted[-1],'GroupAddress')
        self.assertEqual(tuple(n for n,v in session.calls),error.exception.attempted)
        self.assertEqual(sum(n=='GroupAddress' for n,v in session.calls),1)


class MarginOriginalVectorTest(unittest.TestCase):
    def setUp(self):
        self.vectors = json.loads(MARGIN_VECTORS.read_text())

    def test_model_matches_every_frozen_original_vector(self):
        self.assertEqual(self.vectors['executable_sha256'],
                         '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab')
        self.assertEqual(self.vectors['control_word'], '0x1332')
        saved, loaded, trip = (self.vectors[k] for k in ('saved_margin', 'loaded_percent', 'round_trip_margin'))
        self.assertEqual((len(saved), {len(r) for r in saved}), (256, {101}))
        self.assertEqual((len(loaded), {len(r) for r in loaded}, len(trip), {len(r) for r in trip}), (256, {256}, 256, {256}))
        for target in range(256):
            self.assertEqual([saved_margin(target, p) for p in range(101)], saved[target], target)
            self.assertEqual([margin_percent(target, m) for m in range(256)], loaded[target], target)
            self.assertEqual([saved_margin(target, loaded[target][m]) for m in range(256)], trip[target], target)

    def test_x87_differs_from_exact_rounding_in_exactly_nine_dialog_pairs(self):
        from fractions import Fraction
        saved = self.vectors['saved_margin']
        differing = [(t, p, saved[t][p]) for t in range(256) for p in range(101) if saved[t][p] != round(Fraction(t * p, 100))]
        # Independent literal list: each exact product is a .5 tie, and ext(percent/100) is
        # just below or above it, so ROUND goes the other way from round-half-even.
        self.assertEqual(differing, [(50, 59, 29), (75, 42, 31), (95, 30, 29), (150, 21, 31), (150, 53, 79),
                                     (175, 30, 53), (190, 15, 29), (190, 65, 123), (195, 30, 59)])
        # A stored 255 margin round-trips to 256 for 28 targets, outside the native byte.
        overflow = [t for t in range(256) if self.vectors['round_trip_margin'][t][255] > 255]
        self.assertEqual((len(overflow), overflow[0], overflow[-1]), (28, 136, 253))

    @unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'requires the exact original Toolkit executable')
    def test_original_instructions_regenerate_the_vectors(self):
        import importlib.util
        path = ROOT / 'research/sensor_margin_original.py'
        spec = importlib.util.spec_from_file_location('sensor_margin_original', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        probe = module.MarginOriginalProbe(os.environ['CBUS_TOOLKIT_EXE'])
        self.assertEqual(probe.fragment_sha256, self.vectors['fragment_sha256'])
        self.assertEqual(probe.vectors(), {k: self.vectors[k] for k in ('saved_margin', 'loaded_percent', 'round_trip_margin')})


class SensorProfileReviewTest(unittest.TestCase):
    """The committed layout/class receipt must justify exactly the admitted table."""
    def setUp(self):
        self.review=json.loads(REVIEW.read_text())

    @staticmethod
    def above(version):
        parts=version.split('.');parts[-1]=str(int(parts[-1])+1);return '.'.join(parts)

    def test_receipt_is_sanitized_and_pinned(self):
        self.assertEqual(self.review['format'],'cbus-sensor-profile-review-v1')
        self.assertFalse(self.review['original_execution'])
        self.assertEqual(self.review['reference'],{'spec':'SENPILL_ST7.xml','workflow_fields':len(LAYOUTS),
            'layout_fields':['Type','Address','ArraySize','BitSize','BitAddress','ArraySkip','MinValue','MaxValue','Protection']})
        text=REVIEW.read_text()
        for private in ('<Param','Description','DefaultValue','CLIPSAL'):self.assertNotIn(private,text)
        self.assertTrue(all(re.fullmatch('[0-9a-f]{64}',value) for value in self.review['inputs']['unitspec_sha256'].values()))

    def test_layout_verdicts_match_the_assessment(self):
        specs=self.review['specs'];reference=specs['SENPILL_ST7.xml']
        for name in ('SENPIROA_ST7.xml','SENPIROA_ST7_2.xml','SENPIRIA_ST7.xml','SENPIRIA_ST7_2.xml','SENPIRIB_ST7.xml',
                     'SENPIRIB_ST7_2.xml','SENPIRSS_ST7.xml','SENPIRSS_ST7_2.xml','SENLL_ST7.xml'):
            with self.subTest(spec=name):
                self.assertTrue(specs[name]['full_layout_equal'])
                self.assertEqual((specs[name]['parameter_count'],specs[name]['layout_sha256']),(82,reference['layout_sha256']))
        for name,changed in (('SENPILL_1.xml',8),('SENPILL_2.xml',8),('SENPILL_3.xml',8)):
            self.assertFalse(specs[name]['workflow_fields_equal']);self.assertEqual(specs[name]['parameters_changed'],changed)
        for name in ('SENPILLA.xml','SENPIRIC.xml'):
            self.assertTrue(specs[name]['workflow_fields_equal']);self.assertFalse(specs[name]['full_layout_equal'])
            self.assertEqual((specs[name]['parameters_added'],specs[name]['parameters_removed']),(11,0))
        for name in ('SENPIR.xml','SENPIRSS.xml'):self.assertFalse(specs[name]['workflow_fields_equal'])

    def test_toolkit_classes_separate_pir_and_multisensor_handling(self):
        toolkit=self.review['toolkit']
        classes={(row['unit_type'],row['firmware_min'],row['firmware_max']):row['class'] for row in toolkit['registrations']}
        self.assertEqual(classes[('SENPILL','2.0.01','2.3.9')],'TST7SENPILL')
        self.assertEqual(classes[('SENPIROA','2.0.01','9')],'TST7SENPIROA')
        self.assertEqual(classes[('SENPIRIA','2.0.01','9')],'TST7SENPIRSS')
        self.assertEqual(classes[('SENPIRIB','2.0.01','2.3.9')],'TST7SENPIRSS')
        agents={row['unit_class']:row['agent_class'] for row in toolkit['agents']}
        self.assertEqual(agents,{'TST7SENPILL':'TCBusST7MultisensorCGateAgent','TST7SENLL':'TCBusST7LightLevelSensorCGateAgent',
                                 'TST7SENPIRSS':'TCBusST7PIRSensorCGateAgent','TST7SENPIROA':'TCBusST7PIRSensorCGateAgent'})
        save=toolkit['pir_save']
        self.assertEqual(save['before_save_calls'][:2],['CIS_TCBusST7SensorCGateAgent.TCBusST7MultisensorCGateAgent.BeforeSaveProgrammingInformation',
                                                        'CIS_TCBusST7SensorCGateAgent.TCBusST7PIRSensorCGateAgent.PrepareForcedParameters'])
        forced={row['parameter']:row['value'] for row in save['forced'] if 'index' not in row and 'value' in row}
        # The PIR save overwrites the event masks and pot A that this workflow edits.
        for name,value in (('PIRLightMovement',9),('PIRDarkMovement',10),('PIRDark',4),('PotentiometerAFunction',1),
                           ('SingleJoinEnablerGroup',255),('DualJoinEnablerGroup',255),('SceneKeySelector',0)):
            self.assertEqual(forced[name],value);self.assertIn(name,LAYOUTS)
        self.assertEqual(save['pir_unit_constants'],{'MaximumBlockCount':4,'MaximumIndicatorCount':1})
        for hit in toolkit['admitted_class_firmware_scan']['version_comparisons']:
            self.assertTrue(hit['overridden_by'].startswith('TCBusST7MultisensorUnit.'))

    def test_every_catalogue_decision_matches_the_profile_gate(self):
        admitted=set()
        for row in self.review['decisions']:
            versions=[row['firmware_max']]+([row['firmware_min']] if 'firmware_min' in row else [self.above(row['firmware_above'])])
            for version in versions:
                with self.subTest(row=row,version=version):
                    refusal=profile_refusal(row['unit_type'],version,row['catalog_number'])
                    self.assertEqual(refusal is None,row['admitted'])
            if row['admitted']:
                self.assertEqual((row['spec'],row['toolkit_class'],row['toolkit_agent']),
                                 ('SENPILL_ST7.xml','TST7SENPILL','TCBusST7MultisensorCGateAgent'))
                admitted.add((row['catalog_number'],row['firmware_min'],row['firmware_max']))
        for catalog in PROFILE['catalog_numbers']:
            spans=sorted(span[1:] for span in admitted if span[0]==catalog)
            self.assertEqual((spans[0][0],spans[-1][1]),PROFILE['firmware'])
        refused={row['unit_type'] for row in self.review['decisions'] if row['refusal']=='different-toolkit-class'}
        self.assertEqual(refused,{'SENPIROA','SENPIRIA','SENPIRIB','SENLL'})

    @unittest.skipUnless(all(os.environ.get(n) for n in ('CBUS_UNITSPEC_DIR','CBUS_TOOLKIT_EXE','CBUS_LOCAL_CGATE_VENDOR')),
                         'Set decoded specs, Toolkit EXE and C-Gate vendor to regenerate the receipt')
    def test_receipt_regenerates_from_private_inputs(self):
        from research.sensor_profile_review import review
        exe=Path(os.environ['CBUS_TOOLKIT_EXE'])
        current=review(os.environ['CBUS_UNITSPEC_DIR'],Path(os.environ['CBUS_LOCAL_CGATE_VENDOR'])/'unitspec/cbusunits.xml',
                       exe,exe.with_suffix('.map'))
        self.assertEqual(json.loads(json.dumps(current)),self.review)


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_HELP_DIR') and os.environ.get('CBUS_TOOLKIT_EXE'),'Set Toolkit help and EXE paths for source evidence')
class SensorSourceTest(unittest.TestCase):
    def test_original_help_event_tables_and_binary_parameter_bindings(self):
        root=Path(os.environ['CBUS_TOOLKIT_HELP_DIR'])
        for topic,words in (('10114.htm',['Retrigger Timer','Idle','Idle','Idle']),
                            ('10115.htm',['On key','Retrigger timer','Retrigger timer','Idle']),
                            ('10116.htm',['On Key','Off key','Retrigger timer','Off key']),
                            ('17328.htm',['On Key','Retrigger Timer','Idle','Retrigger Timer'])):
            raw=(root/topic).read_text(encoding='cp1252');text=re.sub(r'\s+',' ',unescape(re.sub('<[^>]+>',' ',raw)))
            self.assertIn('Long release '+' '.join(words),text)
        data=Path(os.environ['CBUS_TOOLKIT_EXE']).read_bytes()
        u16=lambda o:struct.unpack_from('<H',data,o)[0];u32=lambda o:struct.unpack_from('<I',data,o)[0]
        pe=u32(60);optional=pe+24;sections=optional+u16(pe+20);base=u32(optional+28)
        def at(va,size):
            rva=va-base
            for n in range(u16(pe+6)):
                o=sections+n*40;start=u32(o+12)
                if start<=rva<start+max(u32(o+8),u32(o+16)):
                    raw=u32(o+20)+rva-start;return data[raw:raw+size]
            self.fail('VA not found')
        for va,name in ((0xCF759C,'PIRLightMovement'),(0xCF75CC,'PIRDarkMovement'),(0xCF75F8,'PIRDark'),
                        (0xCF7738,'PECTargetLux'),(0xCF7760,'PECMarginLux'),
                        (0xCF7934,'PIREnablerGroup'),(0xCF7960,'PIREnablerGroupLogic')):
            self.assertEqual(at(va,len(name)*2),name.encode('utf-16le'))
        # SaveOccupancyKeys serializes independent masks into the members bound
        # above. Any Movement is OR-ed into both day and night masks.
        for va,hexbytes in ((0xCF4EEC,'8b801c020000'),(0xCF4F0D,'8b8020020000'),(0xCF4F2E,'8b80d8010000'),
                            (0xD01152,'b21d'),(0xD0117E,'b21e'),(0xD011A9,'b221'),(0xD011D4,'b222'),
                            (0x7F295F,'03c08d0480'),(0xCF573E,'e88df790ff')):
            self.assertEqual(at(va,len(bytes.fromhex(hexbytes))),bytes.fromhex(hexbytes))


def native_backend():
    """Owned loopback C-Gate when selected, else an explicitly supplied host."""
    if os.environ.get('CBUS_NATIVE_SERVICE_BACKEND')=='local':
        return 'local' if os.environ.get('CBUS_LOCAL_CGATE_VENDOR') and os.environ.get('CBUS_CGATE_JAVA') else None
    return 'host' if os.environ.get('CBUS_CGATE_TEST_HOST') else None


def raw_bytes(session,address,count):
    return bytes.fromhex(session.get_raw_data(address,count).lines[-1].split('RawData=',1)[1])


@unittest.skipUnless(native_backend() and os.environ.get('CBUS_UNITSPEC_DIR'),'Select native C-Gate and unit specs for closed-database sensor acceptance')
class SensorNativeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service=None;cls.host=os.environ.get('CBUS_CGATE_TEST_HOST');cls.port=int(os.environ.get('CBUS_CGATE_TEST_PORT','20023'))
        if native_backend()=='local':
            from research.local_cgate import LocalCGate
            cls.service=LocalCGate(os.environ['CBUS_LOCAL_CGATE_VENDOR']);cls.addClassCleanup(cls.service.close)
            # PP LOCK needs the owned loopback interface at Clipsal access.
            (cls.service.work/'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
            cls.service.start();cls.host,cls.port='127.0.0.1',cls.service.port

    def exercise_profile(self,client,network,address,firmware,catalog,sensor,report):
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        path=f'{network}/p/{address}';case={'firmware':firmware,'catalog_number':catalog,'event_key_cases':0,'raw_byte_assertions':0}
        NativeDatabase(client).create_unit(network,address,'Sensor_'+str(address),'SENPILL',firmware,catalog_number=catalog)
        programmer=Programmer(client)
        with programmer.load(network,'/db'+path)as session:
            self.assertEqual((session.unit_type,session.firmware,session.catalog_number),('SENPILL',firmware,catalog))
            session.reset_defaults();baseline=session.values()
            for key in range(1,9):
                for event,vector in VECTORS.items():
                    result=sensor.configure(session,key=key,event=event,block=key,group=20+key,timer_seconds=300+key,allow_shared_block=True)
                    self.assertEqual((result['firmware'],result['catalog_number']),(firmware,catalog))
                    values=session.values();bit=1<<(key-1)
                    expectedmask=(bool(event in ('day','any')),bool(event in ('night','any')),event=='sunset')
                    self.assertEqual(tuple(bool(v&bit)for v in raw_bytes(session,50,3)),expectedmask)
                    self.assertEqual(tuple(int(values[n].split()[key-1],0)for n in STAGES),vector)
                    self.assertEqual(raw_bytes(session,104+(key-1)*2,2),bytes((vector[0]<<4|vector[1],vector[2]<<4|vector[3])))
                    case['event_key_cases']+=1;case['raw_byte_assertions']+=5
            looped=session.values()
            self.assertEqual({n:v for n,v in looped.items() if n not in LAYOUTS},{n:v for n,v in baseline.items() if n not in LAYOUTS})
            # Native read-modify-write must preserve fields sharing EEPROM
            # bytes, including the bank-switch/expiry byte.
            neighbours={'BlockBankSwitchActive':'1 1 1 1 1 1 1 1','BlockGroupLogic':'1 1 1 1 1 1 1 1','SceneKeySelector':'1 1 1 1 1 1 1 1'}
            for name,value in neighbours.items():session.set(name,value)
            before=session.values()
            sensor.configure(session,key=3,event='night',group=31,timer_seconds=513,expiry='ramp_off',target_lux=550,
                             margin_percent=10,enable_group=23,enabled_when='off',disable_potentiometer_override=True)
            for address_,mask,expected in ((27,255,55),(28,255,6),(74,63,25),(82,255,31),(88,255,23),
                                           (98,128,0),(99,64,64),(101,24,0),(138,255,2),(146,255,1)):
                self.assertEqual(raw_bytes(session,address_,1)[0]&mask,expected);case['raw_byte_assertions']+=1
            after=session.values()
            # Every parameter outside the sensor workflow is untouched by it.
            unrelated=sorted(name for name in before if name not in LAYOUTS)
            self.assertEqual({n:after[n] for n in unrelated},{n:before[n] for n in unrelated})
            self.assertEqual(after['SceneTable'],baseline['SceneTable'])
            case['unrelated_parameters_preserved']=len(unrelated)
            expected=sensor.snapshot(after);session.save_to_source()
        client.command('PROJECT SAVE '+network.split('/')[2])
        with programmer.load(network,'/db'+path)as session:
            self.assertEqual(sensor.snapshot(session.values()),expected)
            self.assertEqual(session.values(),after)
        case['save_reload_passed']=True;report['profiles'].append(case)
        report['event_key_cases']+=case['event_key_cases'];report['raw_byte_assertions']+=case['raw_byte_assertions']

    def refuse_profile(self,client,network,address,unit_type,firmware,catalog,layout_identical,sensor,report):
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        NativeDatabase(client).create_unit(network,address,'Refused_'+str(address),unit_type,firmware,catalog_number=catalog)
        with Programmer(client).load(network,f'/db{network}/p/{address}')as session:
            before=session.values()
            if layout_identical:
                # Native C-Gate accepts the same 82-parameter layout here; the
                # refusal is the Toolkit class/registration gate, not a schema error.
                sensor._verify_session(session);self.assertEqual(set(before),set(sensor.spec.parameters))
            with self.assertRaisesRegex(SensorError,'Native session must'):
                sensor.configure(session,key=3,event='night',group=31)
            self.assertEqual(session.values(),before)
        report['refused'].append({'unit_type':unit_type,'firmware':firmware,'catalog_number':catalog,
                                  'native_layout_identical':layout_identical,'values_unchanged':True})

    def test_admitted_profiles_events_raw_masks_preservation_save_reload_and_refusals(self):
        from cbus_toolkit.cgate import CGateClient
        project='SN'+uuid4().hex[:6].upper();network=f'//{project}/254'
        names=os.environ.get('CBUS_SENSOR_NATIVE_PROFILES')
        profiles=tuple(p for p in NATIVE_PROFILES if not names or p[0] in names.split(','))
        report={'format':'cbus-sensor-acceptance-v2','backend':native_backend(),
                'profile':{'unit_type':'SENPILL','firmware_range':list(PROFILE['firmware']),
                           'catalog_numbers':list(PROFILE['catalog_numbers']),'spec':PROFILE['spec_filename']},
                'scope':'Toolkit source-grounded sensor setup through native PP and a closed database; no physical PIR/lux behavior',
                'profiles':[],'refused':[],'event_key_cases':0,'raw_byte_assertions':0,'passed':False,
                'complete_scope':profiles==NATIVE_PROFILES,'physical_hardware_verified':False}
        sensor=Multisensor(UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR']).load('SENPILL_ST7.xml'))
        with CGateClient(self.host,self.port,timeout=30)as client:
            report['greeting']=client.greeting;client.command('PROJECT NEW '+project)
            try:
                client.command('PROJECT USE '+project)
                client.command('DBCREATENET 254 Sensor_Offline Cni 127.0.0.1:29999')
                client.command('NET LOAD DB '+project);client.command('PROJECT SAVE '+project)
                for index,(firmware,catalog) in enumerate(profiles):
                    with self.subTest(firmware=firmware,catalog=catalog):
                        self.exercise_profile(client,network,230+index,firmware,catalog,sensor,report)
                for index,(unit_type,firmware,catalog,identical) in enumerate(NATIVE_REFUSED):
                    with self.subTest(unit_type=unit_type,firmware=firmware):
                        self.refuse_profile(client,network,240+index,unit_type,firmware,catalog,identical,sensor,report)
                report['passed']=(len(report['profiles'])==len(profiles) and len(report['refused'])==len(NATIVE_REFUSED))
                self.assertTrue(report['passed'])
            finally:
                client.command('PROJECT CLOSE '+project);client.command('PROJECT DELETE '+project)
                if self.service is not None:report['service']={k:self.service.report.get(k) for k in ('vendor_jar_sha256','java_version','listener_ownership_verified','listeners')}
                if os.environ.get('CBUS_SENSOR_REPORT'):Path(os.environ['CBUS_SENSOR_REPORT']).write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':unittest.main()
