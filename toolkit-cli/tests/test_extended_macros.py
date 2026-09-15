"""Neo-core key semantics from literal layout and vendor help/binary evidence."""
from dataclasses import replace
import json
import os
from pathlib import Path
import struct
import unittest
from uuid import uuid4

from cbus_toolkit.extended_macros import ExtendedKeys, PROFILES
from cbus_toolkit.macros import MacroError, MacroApplyError, PRESETS, STAGES
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore
import test_macros as classic_tests


def fixture(filename='KEYM4.xml', unit_type='KEYM4'):
    rows = (
        ('JPCommand', 104, 8, 4, 4, 1, [0]*8), ('SRCommand', 104, 8, 4, 0, 1, [0]*8),
        ('LPCommand', 105, 8, 4, 4, 1, [0]*8), ('LRCommand', 105, 8, 4, 0, 1, [0]*8),
        ('BlockAllocation', 54, 8, 8, 0, 0, [1,2,4,8,16,32,64,128]),
        ('GroupAddress', 80, 9, 8, 0, 0, [255]*9), ('Application',33,2,8,0,0,[56,57]),
        ('SecondApplicationBlocks',69,1,8,0,0,[0]),
        ('TimerHighByte',136,8,8,0,0,[0]*8), ('TimerLowByte',144,8,8,0,0,[0]*8),
        ('TimerExpiryCommand',72,8,4,0,0,[15]*8),
        ('LightLevelStore1',120,8,8,0,0,[255]*8), ('LightLevelStore2',128,8,8,0,0,[255]*8),
        ('SceneKeySelector',96,8,1,7,0,[0]*8), ('IndicatorBlockAssignment',96,8,3,0,0,list(range(8))))
    parameters = {}
    for name,address,count,bits,bit,skip,values in rows:
        fields = {'Name':name,'Type':'int','Address':str(address),'ArraySize':str(count),
                  'BitSize':str(bits),'BitAddress':str(bit),'ArraySkip':str(skip),
                  'DefaultValue':' '.join(map(str,values))}
        parameters[name] = ParameterSpec(name,'int','literal-fixture.xml',fields)
    return UnitSpec(filename,{'Type':unit_type},('literal-fixture.xml',),parameters)


class ExtendedMacroTest(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.keys = ExtendedKeys(self.spec)

    def test_all_eighteen_literal_stage_vectors_and_packed_bytes(self):
        for preset, vector in classic_tests.VECTORS.items():
            with self.subTest(preset=preset):
                plan = self.keys.plan(self.spec.defaults(), key=3, preset=preset, **({'timer_seconds':300} if preset=='timer' else {}))
                updated = dict(plan.expected); updated.update(plan.changes)
                self.assertEqual(tuple(updated[name][2] for name in STAGES), vector)
                packed = self.keys.codec.encode_many({name:updated[name] for name in STAGES}).apply(MemoryImage.from_bytes(b'\xa5'*256))
                self.assertEqual(packed.read(108,2),bytes((vector[0]<<4|vector[1],vector[2]<<4|vector[3])))
                self.assertEqual(packed.read(106,2),b'\x00\x00')

    def test_standard_macro_clears_only_selected_scene_selector_bit(self):
        current = self.spec.defaults(); current['SceneKeySelector']='1 1 1 1 1 1 1 1'
        plan = self.keys.plan(current,key=2,preset='dimmer')
        self.assertEqual(plan.changes['SceneKeySelector'],(1,0,1,1,1,1,1,1))
        patch = self.keys.codec.encode_many(plan.changes)
        memory = patch.apply(MemoryImage.from_bytes(b'\xff'*256))
        self.assertEqual(memory.read(97,1),b'\x7f')
        self.assertEqual(memory.read(96,1),b'\xff')

    def test_group_timer_recall_application_and_independent_indicator(self):
        plan = self.keys.plan(self.spec.defaults(),key=3,preset='timer',group=17,timer_seconds=300,
                              application='secondary',recall1=64,recall2=128,indicator_block=8)
        self.assertEqual(plan.changes['GroupAddress'],(255,255,17,255,255,255,255,255,255))
        self.assertEqual(plan.changes['SecondApplicationBlocks'],(4,))
        self.assertEqual(plan.changes['TimerHighByte'][2],1)
        self.assertEqual(plan.changes['TimerLowByte'][2],44)
        self.assertEqual(plan.changes['LightLevelStore1'][2],64)
        self.assertEqual(plan.changes['LightLevelStore2'][2],128)
        self.assertEqual(plan.changes['IndicatorBlockAssignment'][2],7)
        self.assertNotIn('Application',plan.changes)
        self.assertFalse(plan.as_dict()['saved'])

    def test_all_eight_blocks_and_secondary_mask_preservation(self):
        values = self.spec.defaults();values['SecondApplicationBlocks']='85';values['BlockAllocation']='1 2 4 8 16 32 64 0'
        plan = self.keys.plan(values,key=1,preset='on',block=8,group=9,application='secondary',timer_seconds=65535)
        self.assertEqual(plan.changes['SecondApplicationBlocks'],(213,))
        self.assertEqual(plan.changes['BlockAllocation'][0],128)
        self.assertEqual(plan.changes['GroupAddress'][7],9)
        self.assertEqual(plan.changes['GroupAddress'][8],255)
        self.assertEqual(plan.changes['TimerHighByte'][7],255)
        self.assertEqual(plan.changes['TimerLowByte'][7],255)

    def test_existing_secondary_selection_controls_group_validation(self):
        values=self.spec.defaults();values['SecondApplicationBlocks']='1';values['Application']='56 255'
        with self.assertRaisesRegex(MacroError,'Lighting Type'):
            self.keys.plan(values,key=1,preset='on',group=5)
        plan=self.keys.plan(values,key=1,preset='on',group=5,application='primary')
        self.assertEqual(plan.changes['SecondApplicationBlocks'],(0,))

    def test_shared_virtual_keys_are_reported_and_require_explicit_edit(self):
        values=self.spec.defaults()
        with self.assertRaisesRegex(MacroError,'also assigned'):
            self.keys.plan(values,key=1,preset='on',block=8,group=5)
        plan=self.keys.plan(values,key=1,preset='on',block=8,group=5,allow_shared_block=True)
        self.assertEqual(plan.shared_keys,(8,))

    def test_profile_layout_and_physical_key_bounds(self):
        for filename,unit_type,count in (('KEYE.xml','KEYE1',1),('KEYM4.xml','KEYM4',4),('KEYA3.xml','KEYA3',3),('KEYB4.xml','KEYB4',4)):
            keys=ExtendedKeys(fixture(filename,unit_type))
            keys.plan(keys.spec.defaults(),key=count,preset='bellpress')
            with self.assertRaises(MacroError):keys.plan(keys.spec.defaults(),key=count+1,preset='on')
        for filename,unit_type in (('KEYB6.xml','KEYB6'),('KEYGL5.xml','KEYGL5'),('KEYM4_A.xml','KEYM4')):
            with self.assertRaises(MacroError):ExtendedKeys(fixture(filename,unit_type))
        bad=replace(self.spec.get('JPCommand'),fields=dict(self.spec.get('JPCommand').fields,Address='50'))
        with self.assertRaises(MacroError):ExtendedKeys(replace(self.spec,parameters=dict(self.spec.parameters,JPCommand=bad)))

    def test_disabled_timer_and_invalid_values(self):
        with self.assertRaisesRegex(MacroError,'disabled'):
            self.keys.plan(self.spec.defaults(),key=1,preset='timer')
        self.keys.plan(self.spec.defaults(),key=1,preset='timer',timer_seconds=0)
        for options in ({'key':True},{'preset':'scene'},{'group':255},{'block':9},{'application':'third'},
                        {'timer_seconds':65536},{'timer_seconds':1,'expiry':'toggle'},{'recall1':256},{'indicator_block':0}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                self.keys.plan(self.spec.defaults(),**dict({'key':1,'preset':'on'},**options))

    def test_apply_stale_plan_and_unrelated_fields(self):
        session=classic_tests.Session(self.spec)
        session.current['Unrelated']='preserve'
        plan=self.keys.plan(session.values(),key=2,preset='bellpress',group=7)
        result=self.keys.apply(session,plan)
        self.assertTrue(result['verified']);self.assertFalse(result['device_verified'])
        self.assertEqual(session.current['Unrelated'],'preserve')
        self.assertEqual(session.current['JPCommand'],'0 13 0 0 0 0 0 0')
        with self.assertRaisesRegex(MacroError,'changed since'):
            self.keys.apply(session,plan)

    def test_failed_apply_restores_attempted_parameters(self):
        session=classic_tests.Session(self.spec);session.failure='LRCommand'
        before=self.keys._snapshot(session.values())
        plan=self.keys.plan(session.values(),key=2,preset='bellpress')
        with self.assertRaises(MacroApplyError) as caught:self.keys.apply(session,plan)
        self.assertEqual(caught.exception.rollback_errors,())
        self.assertEqual(self.keys._snapshot(session.values()),before)


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'),'Set CBUS_TOOLKIT_EXE for original Neo factory code checks')
class ExtendedBinaryTest(unittest.TestCase):
    def test_neo_saves_shared_function_codes_and_clears_scene_selector(self):
        data=Path(os.environ['CBUS_TOOLKIT_EXE']).read_bytes()
        u16=lambda o:struct.unpack_from('<H',data,o)[0]
        u32=lambda o:struct.unpack_from('<I',data,o)[0]
        pe=u32(60);optional=pe+24;sections=optional+u16(pe+20);base=u32(optional+28)
        def at(va,size):
            rva=va-base
            for n in range(u16(pe+6)):
                o=sections+n*40;start=u32(o+12)
                if start<=rva<start+max(u32(o+8),u32(o+16)):
                    raw=u32(o+20)+rva-start;return data[raw:raw+size]
            self.fail('VA not found')
        # Constructor's 0x180 member is named SceneKeySelector. Standard branch
        # writes zero to that member, then takes stages0,1,2,3 from the common
        # TInputKey.GetMicroFunctionAsHexString function.
        self.assertEqual(at(0xCCA08C,32),'SceneKeySelector'.encode('utf-16le'))
        self.assertEqual(at(0xCCBB8C,8),bytes.fromhex('8b808001000033c9'))
        for va,raw in ((0xCCBC23,'33d2'),(0xCCBC46,'b201'),(0xCCBC69,'b202'),(0xCCBC8C,'b203')):
            self.assertEqual(at(va,len(bytes.fromhex(raw))),bytes.fromhex(raw))
        self.assertEqual(at(0xD08760,6),'NEO'.encode('utf-16le'))
        self.assertEqual(at(0xCED72A,13),bytes.fromhex('8b4dfcb801000000d3e00145f8'))


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_HELP_DIR'),'Set CBUS_TOOLKIT_HELP_DIR for Neo preset help tables')
class ExtendedHelpTest(unittest.TestCase):
    def test_neo_family_help_links_the_standard_presets_and_four_events(self):
        root=Path(os.environ['CBUS_TOOLKIT_HELP_DIR'])
        for topic in ('4878.htm','4891.htm','4863.htm'):
            text=(root/topic).read_text(encoding='cp1252')
            self.assertIn('Standard wired macro functions',text)
        check=classic_tests.VendorHelpTests('test_all_presets_against_original_help_event_tables')
        check.test_all_presets_against_original_help_event_tables()


@unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST') and os.environ.get('CBUS_UNITSPEC_DIR'),'Set C-Gate and unit specs for closed-database Neo preset acceptance')
class ExtendedNativeTest(unittest.TestCase):
    def test_four_profiles_all_presets_raw_bytes_and_database_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        project='EK'+uuid4().hex[:6].upper();network=f'//{project}/254'
        rows=(('KEYE.xml','KEYE1','5031NMML',1),('KEYM4.xml','KEYM4','5054NL',4),('KEYA3.xml','KEYA3','R5063NL',3),('KEYB4.xml','KEYB4','5084NL',4))
        report={'format':'cbus-extended-macros-acceptance-v1','scope':'Toolkit help/binary-grounded Neo-core presets through native PP;closed database only;no physical button behavior','profiles':[],'passed':False}
        with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=30) as client:
            report['greeting']=client.greeting
            client.command('PROJECT NEW '+project)
            try:
                client.command('PROJECT USE '+project)
                client.command('DBCREATENET 254 Extended_Offline Cni 127.0.0.1:29999')
                client.command('NET LOAD DB '+project)
                client.command('PROJECT SAVE '+project)
                programmer=Programmer(client);store=UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR'])
                for index,(filename,unit_type,catalog,key) in enumerate(rows):
                    keys=ExtendedKeys(store.load(filename));path=f'{network}/p/{220+index}'
                    NativeDatabase(client).create_unit(network,220+index,'Extended_'+str(index),unit_type,'2.5.00',catalog_number=catalog)
                    with programmer.load(network,'/db'+path) as session:
                        session.reset_defaults()
                        baseline=session.values()
                        session.set('Application','56 57')
                        # Start as a scene to prove ordinary presets remove the
                        # mode bit without overwriting the independent scene table.
                        selectors=[0]*8;selectors[key-1]=1
                        session.set('SceneKeySelector',' '.join(map(str,selectors)))
                        for preset,vector in classic_tests.VECTORS.items():
                            with self.subTest(unit_type=unit_type,preset=preset):
                                opts={'timer_seconds':300} if preset=='timer' else {}
                                self.assertTrue(keys.configure(session,key=key,preset=preset,group=17,**opts)['verified'])
                                actual=session.values()
                                self.assertEqual(tuple(int(actual[name].split()[key-1],0) for name in STAGES),vector)
                                raw=session.get_raw_data(104+(key-1)*2,2).lines[-1].split('RawData=',1)[1]
                                self.assertEqual(raw,bytes((vector[0]<<4|vector[1],vector[2]<<4|vector[3])).hex())
                                self.assertEqual(actual['SceneTable'],baseline['SceneTable'])
                        keys.configure(session,key=key,preset='timer',group=31,application='secondary',timer_seconds=300,expiry='ramp_off',
                                       recall1=64,recall2=128,indicator_block=8)
                        before=keys._snapshot(session.values())
                        self.assertEqual(int(session.get_raw_data(69,1).lines[-1].split('RawData=',1)[1],16),1<<(key-1))
                        self.assertEqual(int(session.get_raw_data(96+key-1,1).lines[-1].split('RawData=',1)[1],16)&135,7)
                        for address,value in ((80+key-1,31),(120+key-1,64),(128+key-1,128),(136+key-1,1),(144+key-1,44)):
                            self.assertEqual(int(session.get_raw_data(address,1).lines[-1].split('RawData=',1)[1],16),value)
                        self.assertEqual(int(session.get_raw_data(72+key-1,1).lines[-1].split('RawData=',1)[1],16)&15,9)
                        session.save_to_source()
                    client.command('PROJECT SAVE '+project)
                    with programmer.load(network,'/db'+path) as session:
                        self.assertEqual(keys._snapshot(session.values()),before)
                    report['profiles'].append({'unit_type':unit_type,'catalog_number':catalog,'firmware':'2.5.00','spec_filename':filename,
                                               'presets_passed':18,'raw_stage_bytes_checked':36,'database_reload_passed':True})
                report['passed']=True
            finally:
                client.command('PROJECT CLOSE '+project)
                client.command('PROJECT DELETE '+project)
                if os.environ.get('CBUS_EXTENDED_MACROS_REPORT'):
                    Path(os.environ['CBUS_EXTENDED_MACROS_REPORT']).write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':unittest.main()
