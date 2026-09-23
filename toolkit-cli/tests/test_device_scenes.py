"""Independent scene wire vectors, Toolkit source checks, closed native PP."""
from dataclasses import replace
from html import unescape
import json
import os
from pathlib import Path
import re
import struct
import unittest
from uuid import uuid4

from cbus_toolkit.device_scenes import DeviceScenes, SceneEntry, DeviceSceneError, DeviceSceneApplyError, RAMP_SECONDS
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.unitspec import UnitSpec, ParameterSpec, UnitSpecStore
from test_macros import Session


def fixture():
    rows = [('SceneTable',162,80,8,0,0,[255]*80),('SceneTablePointer',152,8,8,0,0,[162,182,202,222,255,255,255,255]),
            ('SceneKeySelector',96,8,1,7,0,[0]*8),('IndicatorBlockAssignment',96,8,3,0,0,list(range(8))),
            ('JPCommand',104,8,4,4,1,[0]*8),('SRCommand',104,8,4,0,1,[0]*8),
            ('LPCommand',105,8,4,4,1,[0]*8),('LRCommand',105,8,4,0,1,[0]*8),
            ('ControlAppGroupAddress',95,1,8,0,0,[255]),('BlockAllocation',54,8,8,0,0,[1,2,4,8,16,32,64,128]),
            ('SecondApplicationBlocks',69,1,8,0,0,[0]),('GroupAddress',80,9,8,0,0,[255]*9),
            ('Application',33,2,8,0,0,[56,255]),('JoinPrimaryApplication',90,1,8,0,0,[255]),
            ('DualJoinPrimaryApplication',91,1,8,0,0,[255]),('JoinSecondaryApplication',93,1,8,0,0,[255]),
            ('DualJoinSecondaryApplication',94,1,8,0,0,[255])]
    parameters={}
    for name,address,count,bits,bit,skip,values in rows:
        fields={'Name':name,'Type':'int','Address':str(address),'ArraySize':str(count),'BitSize':str(bits),
                'BitAddress':str(bit),'ArraySkip':str(skip),'DefaultValue':' '.join(map(str,values))}
        parameters[name]=ParameterSpec(name,'int','literal-device-scenes.xml',fields)
    return UnitSpec('KEYE.xml',{'Type':'KEYE1'},('literal-device-scenes.xml',),parameters)


def after(plan):
    result=dict(plan.expected);result.update(plan.changes);return result


class DeviceSceneTest(unittest.TestCase):
    def setUp(self):self.spec=fixture();self.editor=DeviceScenes(self.spec);self.current=self.spec.defaults()

    def test_default_and_fixed_literal_tables(self):
        self.assertEqual(self.editor.inspect(self.current)['commands_used'],0)
        first=self.editor.plan(self.current,scene=1,entries=[SceneEntry(12,255),SceneEntry(24,127)])
        self.assertEqual(first.changes['SceneTable'],(12,255,24,127)+(255,)*76)
        self.assertNotIn('SceneTablePointer',first.changes)
        second=self.editor.plan(after(first),scene=2,entries=[SceneEntry(0,0),SceneEntry(254,1)])
        self.assertEqual(second.changes['SceneTable'],(12,255,24,127)+(255,)*16+(0,0,254,1)+(255,)*56)
        self.assertEqual(self.editor.inspect(after(second))['layout'],'fixed')

    def test_eight_scenes_capacity_and_fixed_compact_transition(self):
        current=self.current
        for scene in range(1,9):
            current=after(self.editor.plan(current,scene=scene,entries=[SceneEntry(scene*20+n,n*50)for n in range(5)]))
            expected=[255]*80
            for index in range(scene):
                start=index*20 if scene<=4 else index*10
                expected[start:start+10]=[v for n in range(5)for v in ((index+1)*20+n,n*50)]
            self.assertEqual(current['SceneTable'],tuple(expected))
            self.assertEqual(current['SceneTablePointer'],(162,182,202,222,255,255,255,255)if scene<=4 else tuple([162+n*10 for n in range(scene)]+[255]*(8-scene)))
        self.assertEqual(self.editor.inspect(current)['commands_used'],40)
        with self.assertRaisesRegex(DeviceSceneError,'40 scene commands'):
            self.editor.plan(current,scene=1,entries=[SceneEntry(n,0)for n in range(6)])
        for scene in range(8,4,-1):current=after(self.editor.plan(current,scene=scene,entries=[]))
        self.assertTrue(self.editor.inspect(current)['scene_learn_compatible'])
        self.assertEqual(current['SceneTablePointer'],(162,182,202,222,255,255,255,255))
        self.assertEqual(current['SceneTable'][20:30],(40,0,41,50,42,100,43,150,44,200))

    def test_scene_key_literal_nibbles_and_packed_preservation(self):
        current=dict(self.current,GroupAddress='12 24 255 255 255 255 255 255 33',SecondApplicationBlocks='255')
        for scene in range(1,9):
            for rate,selector in ((0,0),(1,1),(7,127),(15,255)):
                plan=self.editor.plan(current,scene=scene,key=1,ramp_rate=rate,action_selector=selector,trigger_group=23)
                values=after(plan)
                self.assertEqual(tuple(values[n][0]for n in ('JPCommand','SRCommand','LPCommand','LRCommand')),
                                 (14,rate,selector>>4,selector&15))
                baseline=self.editor.codec.encode_many(plan.expected).apply(MemoryImage.from_bytes(b'\x78'*256))
                raw=self.editor.codec.encode_many(plan.changes).apply(baseline)
                self.assertEqual(raw.read(104,2),bytes((0xe0|rate,selector)))
                self.assertEqual(raw.read(96,1),bytes((0xf8|scene-1,)))
                self.assertEqual(values['GroupAddress'],(255,24,255,255,255,255,255,255,33))
                self.assertEqual(values['SecondApplicationBlocks'],(254,))
                self.assertEqual(values['BlockAllocation'],(1,2,4,8,16,32,64,128))

    def test_new_binding_requires_rate_selector_but_existing_preserves(self):
        for options in ({},{'ramp_rate':4},{'action_selector':66}):
            with self.assertRaisesRegex(DeviceSceneError,'explicit'):
                self.editor.plan(self.current,scene=8,key=1,**options)
        initial=after(self.editor.plan(self.current,scene=8,key=1,ramp_rate=4,action_selector=66))
        updated=self.editor.plan(initial,scene=7,key=1)
        self.assertEqual(updated.changes,{'IndicatorBlockAssignment':(6,1,2,3,4,5,6,7)})
        self.assertEqual(self.editor.inspect(after(updated))['key_bindings'][0]['action_selector'],66)

    def test_clear_final_scene_retains_empty_remote_binding(self):
        current=after(self.editor.plan(self.current,scene=1,entries=[SceneEntry(3,22)],key=1,ramp_rate=0,action_selector=15,trigger_group=6))
        cleared=after(self.editor.plan(current,scene=1,entries=[]))
        info=self.editor.inspect(cleared)
        self.assertEqual(info['commands_used'],0);self.assertEqual(info['trigger_group'],6)
        self.assertEqual(info['key_bindings'][0]['scene'],1)
        self.assertEqual(cleared['SceneTable'],(255,)*80)

    def test_reject_gap_delete_and_duplicate_groups_without_renumbering(self):
        with self.assertRaisesRegex(DeviceSceneError,'contiguous'):
            self.editor.plan(self.current,scene=2,entries=[SceneEntry(2,3)])
        first=after(self.editor.plan(self.current,scene=1,entries=[SceneEntry(2,3)]))
        second=after(self.editor.plan(first,scene=2,entries=[SceneEntry(2,3)]))
        with self.assertRaisesRegex(DeviceSceneError,'contiguous'):self.editor.plan(second,scene=1,entries=[])
        with self.assertRaisesRegex(DeviceSceneError,'duplicate'):
            self.editor.plan(first,scene=1,entries=[SceneEntry(2,3),SceneEntry(2,4)])
        with self.assertRaisesRegex(DeviceSceneError,'10 commands'):
            self.editor.plan(first,scene=1,entries=[SceneEntry(n,3)for n in range(11)])

    def test_noncanonical_input_is_not_silently_normalized(self):
        for pointers in ([163,182,202,222,255,255,255,255],[162,162,202,222,255,255,255,255],
                         [162,255,202,222,255,255,255,255],[0,255,255,255,255,255,255,255]):
            with self.subTest(pointers=pointers),self.assertRaises(DeviceSceneError):
                self.editor.inspect(dict(self.current,SceneTablePointer=pointers))
        for table in ([255,1]+[255]*78,[255]*2+[12,34]+[255]*76,[255]*20+[12,34]+[255]*58,
                      [1,2,1,3]+[255]*76):
            with self.subTest(table=table[:4]),self.assertRaises(DeviceSceneError):
                self.editor.plan(dict(self.current,SceneTable=table),scene=1,entries=[])

    def test_block_join_and_shared_trigger_dependencies(self):
        opts={'scene':1,'key':1,'ramp_rate':0,'action_selector':0}
        with self.assertRaisesRegex(DeviceSceneError,'relocation'):
            self.editor.plan(dict(self.current,BlockAllocation='1 3 4 8 16 32 64 128'),**opts)
        for name in ('JoinPrimaryApplication','DualJoinPrimaryApplication','JoinSecondaryApplication','DualJoinSecondaryApplication'):
            with self.subTest(name=name),self.assertRaisesRegex(DeviceSceneError,'Join'):
                self.editor.plan(dict(self.current,**{name:'1'}),**opts)
        current=dict(self.current,SceneKeySelector='0 1 0 0 0 0 0 0')
        with self.assertRaisesRegex(DeviceSceneError,'shared'):
            self.editor.plan(current,trigger_group=14,**opts)
        plan=self.editor.plan(current,trigger_group=14,allow_shared_trigger_group=True,**opts)
        self.assertEqual(plan.changes['ControlAppGroupAddress'],(14,))
        self.assertEqual(plan.changes['SceneKeySelector'],(1,1,0,0,0,0,0,0))

    def test_profile_input_and_schema_limits(self):
        for group,level in ((255,0),(-1,0),(1,256),(True,1),(1,False)):
            with self.assertRaises(DeviceSceneError):SceneEntry(group,level)
        for options in ({'scene':True},{'scene':9},{'scene':1,'key':2},{'scene':1,'ramp_rate':1},
                        {'scene':1,'key':1,'ramp_rate':16,'action_selector':1},{'scene':1,'trigger_group':False},
                        {'scene':1,'allow_shared_trigger_group':1},{'scene':1,'entries':[(1,2)]}):
            with self.subTest(options=options),self.assertRaises(ValueError):self.editor.plan(self.current,**options)
        with self.assertRaisesRegex(DeviceSceneError,'Lighting'):
            self.editor.plan(dict(self.current,Application='202 255'),scene=1,entries=[SceneEntry(1,2)])
        with self.assertRaises(DeviceSceneError):DeviceScenes(replace(self.spec,filename='KEYM4.xml'))
        bad=replace(self.spec.get('SceneTable'),fields=dict(self.spec.get('SceneTable').fields,Address='164'))
        with self.assertRaises(DeviceSceneError):DeviceScenes(replace(self.spec,parameters=dict(self.spec.parameters,SceneTable=bad)))

    def session(self):
        session=Session(self.spec);session.firmware='2.5.00';session.catalog_number='5031NMML';return session

    def test_profile_stale_plan_schema_and_unrelated_parameter_preservation(self):
        session=self.session();session.current['Other']='preserved'
        plan=self.editor.plan(session.values(),scene=1,entries=[SceneEntry(1,2)])
        result=self.editor.apply(session,plan)
        self.assertTrue(result['verified']);self.assertFalse(result['saved']);self.assertFalse(result['device_verified'])
        self.assertEqual(session.current['Other'],'preserved')
        with self.assertRaisesRegex(DeviceSceneError,'changed since'):self.editor.apply(session,plan)
        for field,value in (('unit_type','KEYE2'),('firmware','2.6.00'),('catalog_number','OTHER')):
            session=self.session();setattr(session,field,value)
            with self.assertRaisesRegex(DeviceSceneError,'Native session'):self.editor.apply(session,plan)
            self.assertEqual(session.calls,[])
        session=self.session();session.spec=replace(self.spec,parameters=dict(self.spec.parameters,SceneTable=replace(self.spec.get('SceneTable'),fields=dict(self.spec.get('SceneTable').fields,Address='164'))))
        with self.assertRaisesRegex(DeviceSceneError,'layout mismatch'):self.editor.apply(session,plan)
        self.assertEqual(session.calls,[])

    def test_transport_failure_stops_before_readback_and_mismatch_is_partial(self):
        session=self.session();plan=self.editor.plan(session.values(),scene=1,entries=[SceneEntry(1,2)])
        reads=0
        original_values=session.values
        def values():
            nonlocal reads
            reads+=1
            return original_values()
        session.values=values
        def fail(name,value):raise OSError('connection lost')
        session.set=fail
        with self.assertRaises(DeviceSceneApplyError)as error:self.editor.apply(session,plan)
        self.assertEqual(reads,1);self.assertIsInstance(error.exception.cause,OSError)
        self.assertEqual(error.exception.attempted,('SceneTable',))
        session=self.session();session.set=lambda name,value:None
        with self.assertRaisesRegex(DeviceSceneApplyError,'readback differs'):self.editor.apply(session,plan)

    def test_failed_mutation_stops_without_retries_save_or_recovery_reads(self):
        session=self.session();session.failure='JPCommand'
        plan=self.editor.plan(session.values(),scene=1,entries=[SceneEntry(1,2)],key=1,ramp_rate=2,action_selector=12)
        with self.assertRaises(DeviceSceneApplyError)as error:self.editor.apply(session,plan)
        self.assertEqual(error.exception.attempted[-1],'JPCommand')
        self.assertEqual(tuple(n for n,v in session.calls),error.exception.attempted)
        self.assertEqual(error.exception.details['saved'],False)
        self.assertEqual(sum(n=='JPCommand'for n,v in session.calls),1)


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_HELP_DIR')and os.environ.get('CBUS_TOOLKIT_EXE'),'Set Toolkit EXE and help for source evidence')
class DeviceSceneSourceTest(unittest.TestCase):
    def test_original_help_and_exact_native_serializer_instructions(self):
        root=Path(os.environ['CBUS_TOOLKIT_HELP_DIR'])
        text=lambda topic:re.sub(r'\s+',' ',unescape(re.sub('<[^>]+>',' ',(root/topic).read_text(encoding='cp1252'))))
        self.assertIn('up to eight scenes',text('5018.htm'));self.assertIn('up to 10 commands',text('5018.htm'))
        self.assertIn('Empty scenes can be used as a way of triggering an existing scene remotely',text('1036.htm'))
        data=Path(os.environ['CBUS_TOOLKIT_EXE']).read_bytes()
        u16=lambda o:struct.unpack_from('<H',data,o)[0];u32=lambda o:struct.unpack_from('<I',data,o)[0]
        pe=u32(60);optional=pe+24;sections=optional+u16(pe+20);base=u32(optional+28)
        def at(va,size):
            for n in range(u16(pe+6)):
                o=sections+n*40;start=u32(o+12);rva=va-base
                if start<=rva<start+max(u32(o+8),u32(o+16)):
                    raw=u32(o+20)+rva-start;return data[raw:raw+size]
            self.fail('VA not found')
        for va,name in ((0xCCA0BC,'SceneTable'),(0xCCA0E0,'SceneTablePointer'),(0xCCA08C,'SceneKeySelector'),(0xCC9F00,'ControlAppGroupAddress')):
            self.assertEqual(at(va,len(name)*2),name.encode('utf-16le'))
        # Independent instruction literals from the original EXE, not copied
        # from our encoder: 80-byte loop; offset=count*20; group/level+2;
        # four-scene/ten-command compatibility; base A2 and pointer increments.
        for va,literal in ((0xCCBD42,'837de850'),(0xCCBDC2,'c1e0028d0480'),(0xCCBE7B,'898495a0feffff'),
                           (0xCCBEC1,'898495a4feffff'),(0xCCBEC8,'8345e802'),(0xD08AA6,'83f804'),
                           (0xD08AB8,'83f80a'),(0xCCC063,'c745d0a2000000'),(0xCCC0A0,'837df404'),
                           (0xCCC11D,'03c0'),(0xCCB937,'b901000000'),(0xCCB9BA,'83e07f'),
                           (0xCCB9ED,'e8e254b2ff'),(0xCCBA22,'e8cd54b2ff'),(0xD12A10,'33d2'),
                           (0xD12A2A,'baff000000')):
            self.assertEqual(at(va,len(bytes.fromhex(literal))),bytes.fromhex(literal))
        self.assertEqual(at(0xCCBCEC,8),'0x0E'.encode('utf-16le'))
        self.assertEqual(struct.unpack('<16I',at(0x13B702C,64)),(0,4,8,12,20,30,40,60,90,120,180,300,420,600,900,1020))
        self.assertEqual(RAMP_SECONDS,struct.unpack('<16I',at(0x13B702C,64)))


@unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST')and os.environ.get('CBUS_UNITSPEC_DIR'),'Set C-Gate and unit specs for native closed-database scene acceptance')
class DeviceSceneNativeTest(unittest.TestCase):
    def test_native_records_all_slots_rates_selectors_packed_bits_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        project='DS'+uuid4().hex[:6].upper();network=f'//{project}/254';path=network+'/p/230'
        report={'format':'cbus-device-scene-acceptance-v1','profile':{'unit_type':'KEYE1','firmware':'2.5.00','catalog_number':'5031NMML','spec':'KEYE.xml'},
                'scope':'Source-grounded EEPROM scene storage and key binding through native PP and closed /db; no physical invocation or scene learning',
                'scene_table_cases':0,'key_binding_cases':0,'raw_bytes_compared':0,'save_reload_cases':0,'passed':False}
        editor=DeviceScenes(UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR']).load('KEYE.xml'))
        with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=30)as client:
            report['greeting']=client.greeting;client.command('PROJECT NEW '+project)
            try:
                client.command('PROJECT USE '+project);client.command('DBCREATENET 254 Device_Scene_Offline Cni 127.0.0.1:29999')
                client.command('NET LOAD DB '+project);client.command('PROJECT SAVE '+project)
                NativeDatabase(client).create_unit(network,230,'Scene_Offline','KEYE1','2.5.00',catalog_number='5031NMML')
                programmer=Programmer(client)
                with programmer.load(network,'/db'+path)as session:
                    session.reset_defaults();baseline=session.values()
                    raw=lambda address,count:bytes.fromhex(session.get_raw_data(address,count).lines[-1].split('RawData=',1)[1])
                    for scene in range(1,9):
                        editor.configure(session,scene=scene,entries=[SceneEntry(scene*20+n,n*50)for n in range(5)])
                        expected=[255]*80
                        for index in range(scene):
                            start=index*20 if scene<=4 else index*10
                            expected[start:start+10]=[v for n in range(5)for v in ((index+1)*20+n,n*50)]
                        pointers=[162,182,202,222,255,255,255,255]if scene<=4 else [162+n*10 for n in range(scene)]+[255]*(8-scene)
                        self.assertEqual(raw(162,80),bytes(expected));self.assertEqual(raw(152,8),bytes(pointers))
                        report['scene_table_cases']+=1;report['raw_bytes_compared']+=88
                    expected=editor.snapshot(session.values());session.save_to_source()
                with programmer.load(network,'/db'+path)as session:
                    self.assertEqual(editor.snapshot(session.values()),expected);report['save_reload_cases']+=1
                    session.set('IndicatorFunction','3 3 3 3 3 3 3 3');session.set('PrimaryColour','1 1 1 1 1 1 1 1')
                    session.set('GroupAddress','12 24 255 255 255 255 255 255 33');session.set('SecondApplicationBlocks','255')
                    raw=lambda address,count:bytes.fromhex(session.get_raw_data(address,count).lines[-1].split('RawData=',1)[1])
                    preserved_indicator=raw(96,8)
                    for rate in range(16):
                        selector=rate*17;scene=rate%8+1
                        editor.configure(session,scene=scene,key=1,ramp_rate=rate,action_selector=selector,trigger_group=23)
                        self.assertEqual(raw(104,2),bytes((0xe0|rate,selector)))
                        self.assertEqual(raw(96,1),bytes(((preserved_indicator[0]&0x78)|0x80|scene-1,)))
                        self.assertEqual(raw(97,7),preserved_indicator[1:])
                        self.assertEqual(raw(69,1),b'\xfe');self.assertEqual(raw(80,2),b'\xff\x18')
                        self.assertEqual(raw(95,1),b'\x17');self.assertEqual(raw(54,8),bytes((1,2,4,8,16,32,64,128)))
                        report['key_binding_cases']+=1;report['raw_bytes_compared']+=22
                    # Clear only the final scenes. Packing changes while all
                    # remaining entry order/content and empty remote key8 stay.
                    for scene in range(8,4,-1):
                        editor.configure(session,scene=scene,entries=[]);report['scene_table_cases']+=1
                    expected_table=[]
                    for scene in range(1,5):expected_table.extend([v for n in range(5)for v in (scene*20+n,n*50)]+[255]*10)
                    self.assertEqual(raw(162,80),bytes(expected_table));self.assertEqual(raw(152,8),bytes((162,182,202,222,255,255,255,255)))
                    report['raw_bytes_compared']+=88
                    values=session.values()
                    for name in ('TimerHighByte','TimerLowByte','TimerExpiryCommand','LightLevelStore1','LightLevelStore2','Application'):
                        self.assertEqual(values[name],baseline[name])
                    expected=editor.snapshot(values);session.save_to_source()
                client.command('PROJECT SAVE '+project)
                with programmer.load(network,'/db'+path)as session:
                    self.assertEqual(editor.snapshot(session.values()),expected);report['save_reload_cases']+=1
                    inspected=editor.inspect(session.values());self.assertTrue(inspected['scene_learn_compatible'])
                    self.assertEqual(inspected['key_bindings'][0]['scene'],8);self.assertEqual(inspected['scenes'][7]['entries'],[])
                report['passed']=True
            finally:
                client.command('PROJECT CLOSE '+project);client.command('PROJECT DELETE '+project)
                if os.environ.get('CBUS_DEVICE_SCENE_REPORT'):Path(os.environ['CBUS_DEVICE_SCENE_REPORT']).write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':unittest.main()
