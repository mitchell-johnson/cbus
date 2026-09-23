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

from cbus_toolkit.sensors import Multisensor, SensorError, SensorApplyError
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore
from test_macros import Session


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

    def test_threshold_exact_steps_margin_round_even_and_pot_dependency(self):
        with self.assertRaisesRegex(SensorError,'potentiometer'):
            self.sensor.plan(self.spec.defaults(),target_lux=450,margin_percent=10)
        for lux,percent,target,margin in ((450,10,45,4),(550,10,55,6),(2550,100,255,255),(0,0,0,0)):
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
        for field,value in (('firmware','2.4.00'),('catalog_number','SLC5753PEIRL'),('unit_type','SENPIRIB')):
            session=self.session();setattr(session,field,value)
            with self.assertRaisesRegex(SensorError,'Native session'):self.sensor.apply(session,plan)
            self.assertEqual(session.calls,[])

    def test_partial_failure_does_not_retry_or_save(self):
        session=self.session();session.failure='GroupAddress'
        plan=self.sensor.plan(session.values(),key=3,event='day',group=19)
        with self.assertRaises(SensorApplyError)as error:self.sensor.apply(session,plan)
        self.assertEqual(error.exception.attempted[-1],'GroupAddress')
        self.assertEqual(tuple(n for n,v in session.calls),error.exception.attempted)
        self.assertEqual(sum(n=='GroupAddress' for n,v in session.calls),1)


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


@unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),'Set C-Gate and unit specs for closed-database sensor acceptance')
class SensorNativeTest(unittest.TestCase):
    def test_all_events_raw_masks_timer_threshold_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        project='SN'+uuid4().hex[:6].upper();network=f'//{project}/254';path=network+'/p/230'
        report={'format':'cbus-sensor-acceptance-v1','profile':{'unit_type':'SENPILL','firmware':'2.3.00','catalog_number':'5753PEIRL','spec':'SENPILL_ST7.xml'},
                'scope':'Toolkit source-grounded sensor setup through native PP and a closed database; no physical PIR/lux behavior',
                'event_key_cases':0,'raw_byte_assertions':0,'passed':False}
        sensor=Multisensor(UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR']).load('SENPILL_ST7.xml'))
        with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=30)as client:
            report['greeting']=client.greeting;client.command('PROJECT NEW '+project)
            try:
                client.command('PROJECT USE '+project)
                client.command('DBCREATENET 254 Sensor_Offline Cni 127.0.0.1:29999')
                client.command('NET LOAD DB '+project);client.command('PROJECT SAVE '+project)
                NativeDatabase(client).create_unit(network,230,'Sensor_Offline','SENPILL','2.3.00',catalog_number='5753PEIRL')
                programmer=Programmer(client)
                with programmer.load(network,'/db'+path)as session:
                    session.reset_defaults();baseline=session.values()
                    for key in range(1,9):
                        for event,vector in VECTORS.items():
                            sensor.configure(session,key=key,event=event,block=key,group=20+key,timer_seconds=300+key,allow_shared_block=True)
                            values=session.values();bit=1<<(key-1)
                            expectedmask=(bool(event in ('day','any')),bool(event in ('night','any')),event=='sunset')
                            raw=bytes.fromhex(session.get_raw_data(50,3).lines[-1].split('RawData=',1)[1])
                            self.assertEqual(tuple(bool(v&bit)for v in raw),expectedmask)
                            self.assertEqual(tuple(int(values[n].split()[key-1],0)for n in STAGES),vector)
                            raw=bytes.fromhex(session.get_raw_data(104+(key-1)*2,2).lines[-1].split('RawData=',1)[1])
                            self.assertEqual(raw,bytes((vector[0]<<4|vector[1],vector[2]<<4|vector[3])))
                            report['event_key_cases']+=1;report['raw_byte_assertions']+=5
                    # Native read-modify-write must preserve fields sharing
                    # EEPROM bytes, including the bank-switch/expiry byte.
                    session.set('BlockBankSwitchActive','1 1 1 1 1 1 1 1')
                    session.set('BlockGroupLogic','1 1 1 1 1 1 1 1')
                    session.set('SceneKeySelector','1 1 1 1 1 1 1 1')
                    sensor.configure(session,key=3,event='night',group=31,timer_seconds=513,expiry='ramp_off',target_lux=550,
                                     margin_percent=10,enable_group=23,enabled_when='off',disable_potentiometer_override=True)
                    for address,mask,expected in ((27,255,55),(28,255,6),(74,63,25),(82,255,31),(88,255,23),
                                                  (98,128,0),(99,64,64),(101,24,0),(138,255,2),(146,255,1)):
                        actual=int(session.get_raw_data(address,1).lines[-1].split('RawData=',1)[1],16)
                        self.assertEqual(actual&mask,expected);report['raw_byte_assertions']+=1
                    self.assertEqual(session.values()['SceneTable'],baseline['SceneTable'])
                    expected=sensor.snapshot(session.values());session.save_to_source()
                client.command('PROJECT SAVE '+project)
                with programmer.load(network,'/db'+path)as session:self.assertEqual(sensor.snapshot(session.values()),expected)
                report['save_reload_passed']=True;report['passed']=True
            finally:
                client.command('PROJECT CLOSE '+project);client.command('PROJECT DELETE '+project)
                if os.environ.get('CBUS_SENSOR_REPORT'):Path(os.environ['CBUS_SENSOR_REPORT']).write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':unittest.main()
