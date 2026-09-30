"""Neo-core key semantics from literal layout and vendor help/binary evidence."""
from dataclasses import replace
import json
import os
from pathlib import Path
import struct
import unittest
from uuid import uuid4

from cbus_toolkit.extended_macros import ExtendedKeys, LAYOUTS, PROFILES, REFUSED_PROFILES
from cbus_toolkit.macros import MacroError, MacroApplyError, PRESETS, STAGES, TRIGGER_PRESETS
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
                current = self.spec.defaults()
                if preset in TRIGGER_PRESETS:
                    current['Application'] = '202 57'
                plan = self.keys.plan(current, key=3, preset=preset, **classic_tests.options_for(preset))
                updated = dict(plan.expected); updated.update(plan.changes)
                self.assertEqual(tuple(updated[name][2] for name in STAGES), vector)
                packed = self.keys.codec.encode_many({name:updated[name] for name in STAGES}).apply(MemoryImage.from_bytes(b'\xa5'*256))
                self.assertEqual(packed.read(108,2),bytes((vector[0]<<4|vector[1],vector[2]<<4|vector[3])))
                self.assertEqual(packed.read(106,2),b'\x00\x00')

    def test_custom_micro_functions_refuse_scene_keys_and_keep_other_stages(self):
        current = self.spec.defaults()
        plan = self.keys.plan_micro_functions(current, key=4, stages={'sr': 'store1', 'lp': 7})
        self.assertEqual(set(plan.changes), {'SRCommand', 'LPCommand'})
        self.assertEqual(plan.changes['SRCommand'][3], 1)
        self.assertEqual(plan.as_dict()['preset']['codes'], {'JPCommand': 0, 'SRCommand': 1, 'LPCommand': 7, 'LRCommand': 0})
        scene = dict(current, SceneKeySelector='0 0 0 1 0 0 0 0')
        with self.assertRaisesRegex(MacroError, 'scene keys read-only'):
            self.keys.plan_micro_functions(scene, key=4, stages={'jp': 1})
        with self.assertRaises(MacroError):
            self.keys.plan_micro_functions(current, key=5, stages={'jp': 1})

    def test_trigger_presets_follow_the_key_block_application(self):
        current = self.spec.defaults()
        current['Application'] = '56 202'
        for preset in sorted(TRIGGER_PRESETS):
            with self.subTest(preset=preset):
                with self.assertRaisesRegex(MacroError, r'Trigger Control \(202\)'):
                    self.keys.plan(current, key=2, preset=preset)
                plan = self.keys.plan(current, key=2, preset=preset, application='secondary', group=5)
                self.assertEqual(plan.changes['SecondApplicationBlocks'], (2,))
                self.assertEqual(plan.changes['GroupAddress'][1], 5)
        shared = dict(current, BlockAllocation='3 0 4 8 16 32 64 128')
        with self.assertRaisesRegex(MacroError, 'Specify block'):
            self.keys.plan(shared, key=2, preset='trigger1')
        with self.assertRaisesRegex(MacroError, 'Lighting Type'):
            self.keys.plan(current, key=2, preset='on', application='secondary', group=5)

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
        self.assertEqual(len(PROFILES),31)
        for filename,(unit_type,count,_family) in PROFILES.items():
            with self.subTest(spec=filename):
                keys=ExtendedKeys(fixture(filename,unit_type))
                keys.plan(keys.spec.defaults(),key=count,preset='bellpress')
                with self.assertRaises(MacroError):keys.plan(keys.spec.defaults(),key=count+1,preset='on')
        refused=(('KEYM6.xml','KEYM6'),('KEYCIR1.xml','KEYCIR1'),('KEYV1SP.xml','KEYV1SP'),('KEYGL5.xml','KEYGL5'),
                 ('KEYM4_A.xml','KEYM4'),('KEYB6_A.xml','KEYB6'),('KEYB6.xml','KEYM6'),('KEYB6A.xml','KEYB6A'))
        for filename,unit_type in refused:
            with self.subTest(refused=filename),self.assertRaises(MacroError):ExtendedKeys(fixture(filename,unit_type))
        for filename,reason in REFUSED_PROFILES.items():
            with self.assertRaisesRegex(MacroError,'not supported'):ExtendedKeys(fixture(filename,filename[:-4]))
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


@unittest.skipUnless(classic_tests.NATIVE, classic_tests.NATIVE_REASON)
class ExtendedNativeTest(unittest.TestCase):
    def test_all_profiles_all_presets_raw_bytes_preservation_and_project_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        selected=os.environ.get('CBUS_NEO_PROFILES')
        rows=[(filename,)+PROFILES[filename][:2] for filename in PROFILES if not selected or filename in selected.split(',')]
        report={'format':'cbus-extended-macros-acceptance-v2','scope':'Toolkit help/binary-grounded Neo-core presets through native PP;closed database only;no physical button behavior','profiles':[],'passed':False}
        finals={}
        with classic_tests.native_endpoint() as (host,port),CGateClient(host,port,timeout=30) as client,\
                classic_tests.closed_network_project(client,'EK') as project:
            report['greeting']=client.greeting
            network=f'//{project}/254'
            programmer=Programmer(client);store=UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR'])
            for index,(filename,unit_type,key) in enumerate(rows):
                keys=ExtendedKeys(store.load(filename));path=f'{network}/p/{150+index}'
                firmware,catalog=classic_tests.family_catalog('neo',filename)
                NativeDatabase(client).create_unit(network,150+index,'Extended_'+str(index),unit_type,firmware,catalog_number=catalog)
                with programmer.load(network,'/db'+path) as session:
                    session.reset_defaults()
                    session.set('Application','56 57')
                    # Start as a scene to prove ordinary presets remove the
                    # mode bit without overwriting the independent scene table.
                    selectors=[0]*8;selectors[key-1]=1
                    session.set('SceneKeySelector',' '.join(map(str,selectors)))
                    baseline=session.values()
                    for preset,vector in classic_tests.VECTORS.items():
                        with self.subTest(unit_type=unit_type,preset=preset):
                            opts=classic_tests.options_for(preset)
                            application=classic_tests.trigger_ready(self,keys,session,preset,key,group=17,**opts)
                            self.assertTrue(keys.configure(session,key=key,preset=preset,group=17,**opts)['verified'])
                            actual=session.values()
                            self.assertEqual(tuple(int(actual[name].split()[key-1],0) for name in STAGES),vector)
                            raw=session.get_raw_data(104+(key-1)*2,2).lines[-1].split('RawData=',1)[1]
                            self.assertEqual(raw,bytes((vector[0]<<4|vector[1],vector[2]<<4|vector[3])).hex())
                            # SceneTable and every other non-preset parameter stay unchanged.
                            self.assertEqual(classic_tests.unrelated(actual,LAYOUTS),classic_tests.unrelated(baseline,LAYOUTS))
                            if application is not None:
                                session.set('Application',application)
                    keys.configure(session,key=key,preset='timer',group=31,application='secondary',timer_seconds=300,expiry='ramp_off',
                                   recall1=64,recall2=128,indicator_block=8)
                    self.assertEqual(int(session.get_raw_data(69,1).lines[-1].split('RawData=',1)[1],16),1<<(key-1))
                    self.assertEqual(int(session.get_raw_data(96+key-1,1).lines[-1].split('RawData=',1)[1],16)&135,7)
                    for address,value in ((80+key-1,31),(120+key-1,64),(128+key-1,128),(136+key-1,1),(144+key-1,44)):
                        self.assertEqual(int(session.get_raw_data(address,1).lines[-1].split('RawData=',1)[1],16),value)
                    self.assertEqual(int(session.get_raw_data(72+key-1,1).lines[-1].split('RawData=',1)[1],16)&15,9)
                    finals[path]=session.values()
                    self.assertEqual(classic_tests.unrelated(finals[path],LAYOUTS),classic_tests.unrelated(baseline,LAYOUTS))
                    session.save_to_source()
                report['profiles'].append({'unit_type':unit_type,'catalog_number':catalog,'firmware':firmware,'spec_filename':filename,
                                           'key':key,'presets_passed':18,'raw_stage_bytes_checked':36})
            client.command('PROJECT SAVE '+project)
            client.command('PROJECT CLOSE '+project)
            client.command('PROJECT LOAD '+project)
            client.command('PROJECT USE '+project)
            for path,expected in finals.items():
                with self.subTest(reload=path),programmer.load(network,'/db'+path) as session:
                    self.assertEqual(session.values(),expected)
            report['project_close_reload_passed']=True
            report['passed']=True
        if os.environ.get('CBUS_EXTENDED_MACROS_REPORT'):
            Path(os.environ['CBUS_EXTENDED_MACROS_REPORT']).write_text(json.dumps(report,indent=2)+'\n')

    def test_refused_profiles_and_cross_type_plans_before_writes(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        store=UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR'])
        for filename in (*REFUSED_PROFILES,'KEYM4_A.xml'):
            with self.subTest(spec=filename),self.assertRaises(MacroError):ExtendedKeys(store.load(filename))
        with classic_tests.native_endpoint() as (host,port),CGateClient(host,port,timeout=30) as client,\
                classic_tests.closed_network_project(client,'ER') as project:
            network=f'//{project}/254'
            firmware,catalog=classic_tests.family_catalog('neo','KEYM2.xml')
            NativeDatabase(client).create_unit(network,240,'Refuse','KEYM2',firmware,catalog_number=catalog)
            with Programmer(client).load(network,f'/db{network}/p/240') as session:
                before=session.values()
                keym4=ExtendedKeys(store.load('KEYM4.xml'))
                with self.assertRaisesRegex(MacroError,'unit type differs'):
                    keym4.apply(session,keym4.plan(before,key=1,preset='on'))
                self.assertEqual(session.values(),before)


if __name__=='__main__':unittest.main()
