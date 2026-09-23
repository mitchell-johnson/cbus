"""Independent original MultiLevelData vectors and native PP persistence."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4

from cbus_toolkit.edlt import EdltError, EdltApplyError, EdltLighting
from cbus_toolkit.edlt_multilevel import EdltMultiLevelWidget
from cbus_toolkit.unitspec import UnitSpecStore
from tests.test_edlt import fixture, Session

BOUND = '1005868600002A54AAFF3F3E3D3C000000000000000000000000000000000000'
ONE = '1085868600002A0000FF3F3E3D3C000000000000000000000000000000000000'
TWO = '1085868600002A7F7FFF3F3E3D3C000000000000000000000000000000000000'
TWO_MAX = '1085868600002AFEFEFF3F3E3D3C000000000000000000000000000000000000'
THREE = '1085868600002A54AAFF3F3E3D3C000000000000000000000000000000000000'
THREE_MIN = '1085868600002A0102FF3F3E3D3C000000000000000000000000000000000000'
THREE_MAX = '1085868600002AFDFEFF3F3E3D3C000000000000000000000000000000000000'
STATIC = '10B5868600002A54AA3B3A3F3E3D000000000000000000000000000000000000'
ICONS = '10A5868600002A54AA013A3F3E3D000000000000000000000000000000000000'
TEXT = '1095868600002A54AA023A3F3E3D000000000000000000000000000000000000'
SAME_INDEX = '10A5868600002A54AA023A3F3E3D000000000000000000000000000000000000'
FORCED = '10A5868600002A54AA02003F3E3D000000000000000000000000000000000000'
OPAQUE = '100586860405FF54AAFF3F3E3D3C0E0F101112131415161718191A1B1C1D1E1F'
NATIVE = {
 'default': '1005868600002A54AAFF0C0D0E0F000000000000000000000000000000000000',
 'one': '1085868600002A0000FF0C0D0E0F000000000000000000000000000000000000',
 'two': '1085868600002AFEFEFF0C0D0E0F000000000000000000000000000000000000',
 'three': '1085868600002AFDFEFF0C0D0E0F000000000000000000000000000000000000',
 'custom': '10B5868600002AFDFE3F3E3D3C3B000000000000000000000000000000000000',
 'explicit-indexes': '10B5868600002AFDFE3F32333435000000000000000000000000000000000000',
 'first-text-match': '10B5868600002AFDFE3F0C0D0E0F000000000000000000000000000000000000',
 'index-boundaries': '10B5868600002AFDFE3F003F003F000000000000000000000000000000000000',
 'dynamic-text': '1095868600002AFDFE023E3D3C3B000000000000000000000000000000000000',
 'same-index': '10A5868600002AFDFE023E3D3C3B000000000000000000000000000000000000',
 'force-static': '10A5868600002AFDFE02003D3C3B000000000000000000000000000000000000',
}
CUSTOM = dict(label_text='Ceiling', off_text='Stopped', low_text='Slow', medium_text='Normal', high_text='Fast')
DEFAULT_TEXTS = ((2, 'Fan'), (12, 'Off'), (13, 'Low'), (14, 'Medium'), (15, 'High'))


def after(plan):
    return {**plan.expected, **plan.changes}


class MultiLevelWidgetTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture(); self.editor = EdltMultiLevelWidget(self.spec); self.session = Session(self.spec)

    def plan(self, current=None, **options):
        settings = dict(page=1, position=1, group=42); settings.update(options)
        return self.editor.plan(self.session.values() if current is None else current, **settings)

    def test_literal_default_speed_thresholds_and_explicit_reset(self):
        plan = self.plan(); self.assertEqual(plan.record.hex().upper(), BOUND)
        self.assertEqual(plan.levels, 3); self.assertFalse(self.plan(after(plan)).changes)
        for options, literal in ((dict(levels=1), ONE), (dict(levels=2), TWO),
                (dict(low_threshold=254), TWO_MAX), (dict(levels=3), THREE),
                (dict(low_threshold=1, high_threshold=2), THREE_MIN),
                (dict(low_threshold=253, high_threshold=254), THREE_MAX), (dict(levels=3), THREE)):
            plan = self.plan(after(plan), application='secondary', **options)
            self.assertEqual(plan.record.hex().upper(), literal)
        invalid = after(plan); invalid['Widget6WidgetByteValue7'] = (255,)
        with self.assertRaisesRegex(EdltError, 'existing MultiLevel thresholds'): self.plan(invalid)
        self.assertEqual(self.plan(invalid, levels=2).record[7:9], b'\x7f\x7f')

    def test_original_four_default_allocations_reuse_and_sequential_dedup(self):
        plan = self.plan(application='secondary', **CUSTOM)
        self.assertEqual(plan.record.hex().upper(), STATIC)
        self.assertEqual([(k, a.index) for k, a in plan.default_allocations],
            [('off',63),('low',62),('medium',61),('high',60)])
        self.assertEqual(plan.static_allocation.index, 59)
        self.assertEqual([a.index for a in plan.status_allocations.values()], [58,63,62,61])
        values = self.session.values()
        for index,text in DEFAULT_TEXTS: values[f'StaticTextString{index}'] = tuple(text.encode().ljust(64,b'\0'))
        reused = self.plan(values); self.assertEqual(reused.record.hex().upper(), NATIVE['default'])
        self.assertTrue(all(a.reused for _,a in reused.default_allocations))
        same = self.plan(values, label_text='Shared', off_text='Shared', low_text='Shared', medium_text='Shared', high_text='Shared')
        self.assertEqual(same.record[9:14], bytes([63]*5))
        blank = self.plan(label_type='blank', levels=1)
        self.assertEqual(len(blank.default_allocations), 4)
        self.assertEqual(blank.record[10:14], b'\x3f\x3e\x3d\x3c')

    def test_explicit_duplicate_indexes_and_hidden_reference_retention(self):
        current = self.session.values()
        for index,text in (*DEFAULT_TEXTS,(50,'Off'),(51,'Low'),(52,'Medium'),(53,'High')):
            current[f'StaticTextString{index}'] = tuple(text.encode().ljust(64,b'\0'))
        plan = self.plan(current, off_index=50, low_index=51, medium_index=52, high_index=53)
        self.assertEqual(plan.record[10:14], bytes((50,51,52,53)))
        match = self.plan(after(plan), off_text='Off', low_text='Low', medium_text='Medium', high_text='High')
        self.assertEqual(match.record[10:14], bytes((12,13,14,15)))
        one = self.plan(after(plan), levels=1)
        self.assertEqual(one.record[10:14], plan.record[10:14])
        references = self.editor.common.static_references(after(one))
        self.assertIn(51, references); self.assertIn(52, references)
        for options in ({'low_text':'Slow'}, {'low_index':0}, {'medium_text':'Mid'}, {'medium_index':0}):
            with self.subTest(options=options), self.assertRaisesRegex(EdltError,'hidden'): self.plan(after(one), **options)
        two = self.plan(after(one), levels=2, low_index=63)
        self.assertEqual(two.record[11:14], bytes((63,52,53)))
        bounds = self.plan(after(two), levels=3, off_index=0, low_index=63, medium_index=0, high_index=63)
        self.assertEqual(bounds.record[10:14], b'\x00\x3f\x00\x3f')

    def test_dynamic_same_index_dependency_and_forced_static_status(self):
        plan = self.plan(application='secondary', **CUSTOM)
        for options,literal in ((dict(label_type='dynamic-icon',label_index=1),ICONS),
                (dict(label_type='dynamic-text',label_index=2),TEXT),
                (dict(label_type='dynamic-icon',label_index=2),SAME_INDEX)):
            plan = self.plan(after(plan),application='secondary',**options)
            self.assertEqual(plan.record.hex().upper(),literal)
        current = after(plan)
        for options in ({'label_index':2},{'label_index':3},{'group':43},{'application':'primary'}):
            with self.subTest(options=options),self.assertRaisesRegex(EdltError,'explicit'):
                self.plan(current, **dict({'application':'secondary'}, **options))
        self.assertFalse(self.plan(current,application='secondary').changes)
        current['Widget6WidgetByteValue1'] = (0xa0,)
        forced = self.plan(current,application='secondary')
        self.assertEqual(forced.record.hex().upper(),FORCED);self.assertTrue(forced.status_forced)
        for options in ({'off_index':63},{'off_text':'Ignored'}):
            with self.assertRaisesRegex(EdltError,'Normalize'): self.plan(current,application='secondary',**options)
        repaired = self.plan(after(forced),application='secondary',off_index=63)
        self.assertEqual(repaired.record[10],63);self.assertFalse(repaired.status_forced)

    def test_opaque_page_restore_and_unrelated_values(self):
        current = self.session.values()
        for index in range(1,32):current[f'Widget6WidgetByteValue{index}']=(index,)
        current['Widget6WidgetByteValue1']=(255,)
        plan=self.plan(current);expected=bytearray.fromhex(OPAQUE);expected[6]=42
        self.assertEqual(plan.record,bytes(expected))
        for index in (4,5,*range(14,32)):self.assertNotIn(f'Widget6WidgetByteValue{index}',plan.changes)
        light=EdltLighting(self.spec).plan(after(plan),page=1,position=2,group=43,mode='off-on',restore_level=137)
        current=after(light);copied=self.plan(current,group=43,application='secondary')
        self.assertEqual((copied.restore_level,copied.restore_source_widget),(137,7))
        same=after(copied);same['Widget6RestoreLevel']=(88,)
        self.assertEqual(self.plan(same,group=43).restore_level,88)
        last=self.plan(current,page=4,position=4,page_mode='multiple',group=43)
        self.assertEqual(last.widget,21);self.assertEqual(self.plan(position=5).widget,10)
        for name,value in current.items():
            if name.startswith('Scene') and name!='ScenesCheckSum' or name.startswith('Widget7') or name=='EnableFanControlLevelWrap':
                self.assertEqual(after(last)[name],value)

    def test_full_table_and_profile_layout_range_guards(self):
        for options in ({'levels':0},{'levels':4},{'levels':True},{'low_threshold':0},{'high_threshold':255},
                {'low_threshold':True},{'low_threshold':171},{'high_threshold':84},{'levels':1,'low_threshold':1},
                {'levels':2,'high_threshold':1},{'off_text':'X','off_index':1},{'low_index':True},{'medium_index':64},
                {'high_index':-1},{'group':255},{'application':203},{'page':2},{'position':6},
                {'label_type':[]},{'label_type':'dynamic-icon','label_index':4},{'label_text':'X','label_index':1},
                {'label_text':'a\0b'},{'off_text':' '},{'low_text':'ā'*32},{'medium_text':3},{'high_text':'a\0b'}):
            with self.subTest(options=options),self.assertRaises(EdltError):self.plan(**options)
        for index,kind in ((1,16),(6,5),(7,16)):
            current=self.session.values();current[f'Widget{index}WidgetType']=(kind,)
            with self.assertRaises(EdltError):self.plan(current)
        current=after(self.plan());idx=0
        for widget in range(7,22):
            current[f'Widget{widget}WidgetType']=(16,);current[f'Widget{widget}WidgetByteValue1']=(0x35,)
            for offset in range(9,14):
                current[f'Widget{widget}WidgetByteValue{offset}']=(min(idx,63),);idx+=1
        with self.assertRaises(EdltError):self.plan(current,off_text='No room')
        for settings in ({'catalog_number':'5055EDLB'},{'firmware':'6.0.00'}):
            with self.assertRaises(EdltError):EdltMultiLevelWidget(self.spec,**settings)
        current=self.session.values();current['SecondaryApplication']=(255,)
        with self.assertRaises(EdltError):self.plan(current,application='secondary')
        self.assertFalse(self.session.calls)

    def test_original_application_choices_and_boundaries(self):
        for application in (48, 95, 96, 127, 136):
            for side in ('primary', 'secondary'):
                current = self.session.values()
                current['PrimaryApplication' if side == 'primary' else 'SecondaryApplication'] = (application,)
                plan = self.plan(current, application=side)
                self.assertEqual(plan.application, application)
                self.assertEqual(after(plan)['Application'], (plan.expected['PrimaryApplication'][0], plan.expected['SecondaryApplication'][0]))
                self.assertEqual(plan.record[1] >> 7, side == 'secondary')
        for application in (0, 47, 128, 135, 137, 255):
            current = self.session.values(); current['PrimaryApplication'] = (application,)
            with self.subTest(application=application), self.assertRaisesRegex(EdltError, '48..127 or 136'):
                self.plan(current)

    def test_stale_identity_canonical_guards_and_unsaved_apply(self):
        plan=self.plan()
        for forged in (None,replace(plan,widget=True),replace(plan,levels=False),replace(plan,record=b'bad'),
                replace(plan,status_forced=0),replace(plan,default_allocations=()),replace(plan,status_allocations={}),
                replace(plan,changes={**plan.changes,'SceneCount':(8,)})):
            with self.assertRaises(EdltError):self.editor.apply(self.session,forged)
        self.session.current['SceneCount']=(8,)
        with self.assertRaisesRegex(EdltError,'changed'):self.editor.apply(self.session,plan)
        self.session.current['SceneCount']=(0,)
        result=self.editor.apply(self.session,plan);self.assertTrue(result['verified']);self.assertFalse(result['saved'])
        self.session.identity['UnitType']='KEY4';self.session.values=lambda:self.fail('Identity must precede PP read')
        with self.assertRaisesRegex(EdltError,'identity'):self.editor.configure(self.session)

    def test_failure_rollback_and_no_recovery_after_disconnection(self):
        plan=self.plan(**CUSTOM);original=self.editor.snapshot(self.session.values());self.session.failure='Widget6WidgetByteValue12'
        with self.assertRaises(EdltApplyError) as caught:self.editor.apply(self.session,plan)
        self.assertTrue(caught.exception.details['rollback_verified']);self.assertFalse(caught.exception.details['saved'])
        self.assertEqual(self.editor.snapshot(self.session.values()),original)
        self.session.calls.clear();initial=self.session.set
        def fail(name,value):
            initial(name,value);self.session.connected=False;raise TimeoutError('Injected disconnect')
        self.session.set=fail
        with self.assertRaises(EdltApplyError) as caught:self.editor.apply(self.session,plan)
        self.assertEqual(len(self.session.calls),1);self.assertIn('Connection lost',caught.exception.rollback_errors[0])


@unittest.skipUnless(all(os.environ.get(key) for key in ('CBUS_CGATE_TEST_HOST','CBUS_UNITSPEC_DIR','CBUS_TOOLKIT_EXE')),
                     'Set C-Gate host, specifications and Toolkit EXE for native MultiLevel widget acceptance')
class NativeMultiLevelWidgetTests(unittest.TestCase):
    def test_original_model_native_raw_shared_refs_crc_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.programming import Programmer
        from research.original_oracle import OriginalModelOracle, selected_backend
        root=Path(__file__).resolve().parents[1];app=Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        specs=Path(os.environ['CBUS_UNITSPEC_DIR']).resolve();spec=UnitSpecStore(specs).load('KEYGL5.xml')
        editor=EdltMultiLevelWidget(spec);project='EML'+uuid4().hex[:5].upper();network=f'//{project}/254';unit=network+'/p/20'
        report={'project':project,'scope':'5055EDL5.5 MultiLevel1/2/3 levels database PP; no physical device','passed':False}
        backend = selected_backend(); report['original_backend'] = backend
        with tempfile.TemporaryDirectory() as folder:
            for name in ('NativeEdltMultiLevelProbe.cs','NativeEdltProbe.cs'):
                Path(folder,name).write_bytes((root/'research'/name).read_bytes())
            def mono(command):
                result=subprocess.run(['docker','run','--rm','-v',str(app)+':/input:ro','-v',folder+':/work','-w','/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5','sh','-c',command],capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr);return result.stdout
            oracle = OriginalModelOracle(root / 'research/NativeEdltMultiLevelProbe.cs', app, backend='windows') if backend == 'windows' else None
            crc_oracle = OriginalModelOracle(root / 'research/NativeEdltProbe.cs', app, backend='windows') if backend == 'windows' else None
            if oracle is not None:
                self.addCleanup(oracle.close); self.addCleanup(crc_oracle.close)
                model = oracle.run()
            else:
                model=mono('mcs -r:/input/CBusLogicModel.dll -r:System.Windows.Forms -r:System.Drawing NativeEdltMultiLevelProbe.cs && MONO_PATH=/input mono NativeEdltMultiLevelProbe.exe')
            for literal in (BOUND,ONE,TWO,TWO_MAX,THREE,THREE_MIN,THREE_MAX,STATIC,ICONS,TEXT,SAME_INDEX,FORCED,OPAQUE,*NATIVE.values()):
                self.assertIn(':'+literal+':0',model)
            self.assertIn('off-edit-before-forcing:0', model.splitlines())
            for application in (48,95,96,127,136):
                self.assertIn(f'selected-app:{application}:{application}', model.splitlines())
            self.assertIn('group-refresh:10A5868600002B54AA02003F3E3D000000000000000000000000000000000000:137',model.splitlines())
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=30) as client:
                client.command('PROJECT NEW '+project)
                try:
                    for command in ('PROJECT USE '+project,f'DBSET //{project}/Project/Description cbus-toolkit-isolated-edlt-multilevel-v1',
                            'DBCREATENET 254 Offline Cni 127.0.0.1:1','PROJECT SAVE '+project,f'DBADDSAFE {network} Unit 20 EDLT'):
                        client.command(command)
                    for key,value in (('UnitType','KEYGL5'),('UnitName','EDLT'),('FirmwareVersion','5.5.00'),('CatalogNumber','5055EDL')):
                        client.command(f'DBSET {unit}/{key} {value}')
                    client.command('NET LOAD DB '+project);programmer=Programmer(client)
                    with programmer.load(network,'/db'+unit) as session:
                        session.reset_defaults();session.set('SecondaryApplication','57');original=editor.snapshot(session.values())
                        for index,text in DEFAULT_TEXTS:self.assertEqual(bytes(original[f'StaticTextString{index}']).rstrip(b'\0').decode(),text)
                        first=editor.plan(original,page=1,position=1,group=42)
                        self.assertEqual(first.record.hex().upper(),NATIVE['default']);self.assertTrue(all(a.reused for _,a in first.default_allocations))
                        editor.apply(session,first)
                        sequence=(('one',dict(levels=1)),('two',dict(levels=2,low_threshold=254)),
                            ('three',dict(levels=3,low_threshold=253,high_threshold=254)),('custom',CUSTOM),
                            ('explicit-indexes',dict(off_index=50,low_index=51,medium_index=52,high_index=53)),
                            ('first-text-match',dict(off_text='Off',low_text='Low',medium_text='Medium',high_text='High')),
                            ('index-boundaries',dict(off_index=0,low_index=63,medium_index=0,high_index=63)),
                            ('dynamic-text',dict(off_text='Stopped',low_text='Slow',medium_text='Normal',high_text='Fast',label_type='dynamic-text',label_index=2)),
                            ('same-index',dict(label_type='dynamic-icon',label_index=2)),('force-static',{}))
                        for name,options in sequence:
                            if name=='explicit-indexes':
                                for index,text in ((50,'Off'),(51,'Low'),(52,'Medium'),(53,'High')):
                                    session.set(f'StaticTextString{index}',' '.join(str(v) for v in text.encode().ljust(64,b'\0')))
                            if name=='same-index':
                                before=editor.snapshot(session.values())
                                with self.assertRaisesRegex(EdltError,'explicit'):editor.configure(session,page=1,position=1,group=42,application='secondary',label_index=2)
                                self.assertEqual(editor.snapshot(session.values()),before)
                            if name=='force-static':
                                session.set('Widget6WidgetByteValue1','160');before=editor.snapshot(session.values())
                                with self.assertRaisesRegex(EdltError,'Normalize'):
                                    editor.configure(session,page=1,position=1,group=42,application='secondary',off_index=63)
                                self.assertEqual(editor.snapshot(session.values()),before)
                            plan=editor.plan(session.values(),page=1,position=1,group=42,application='secondary',**options)
                            self.assertEqual(plan.record.hex().upper(),NATIVE[name]);editor.apply(session,plan)
                            self.assertEqual(session.get_raw_data(0x2c0,32).lines[-1].split('RawData=')[1],NATIVE[name].lower())
                        for index,text in ((63,'Ceiling'),(62,'Stopped'),(61,'Slow'),(60,'Normal'),(59,'Fast')):
                            self.assertEqual(session.get_raw_data(0x1100+64*index,64).lines[-1].split('RawData=')[1],text.encode().ljust(64,b'\0').hex())
                        light=EdltLighting(spec);light.apply(session,light.plan(session.values(),page=1,position=2,group=43,mode='off-on',restore_level=137))
                        prior=editor.snapshot(session.values());copied=editor.plan(prior,page=1,position=1,group=43,application='secondary',label_type='dynamic-icon')
                        self.assertEqual((copied.restore_level,copied.restore_source_widget),(137,7));editor.apply(session,copied)
                        self.assertEqual(session.get_raw_data(0x1a0,1).lines[-1].split('RawData=')[1],'89')
                        last=editor.plan(session.values(),page=4,position=4,page_mode='multiple',group=43,
                            label_text='Shared',off_text='Shared',low_text='Shared',medium_text='Shared',high_text='Shared')
                        self.assertEqual(len(set(last.record[9:14])),1);editor.apply(session,last)
                        self.assertEqual(session.get_raw_data(0x4a0,32).lines[-1].split('RawData=')[1],last.record.hex())
                        final=editor.snapshot(session.values())
                        for name,value in original.items():
                            if name.startswith('Scene') and name!='ScenesCheckSum' or name=='EnableFanControlLevelWrap':self.assertEqual(final[name],value)
                            if name.startswith('Widget7'):self.assertEqual(final[name],prior[name])
                        Path(folder,'KEYGL5.xml').write_bytes((specs/'KEYGL5.xml').read_bytes())
                        Path(folder,'values.tsv').write_text(''.join(name+'\t'+(value if isinstance(value,str) else ' '.join(hex(n) for n in value))+'\n' for name,value in final.items()))
                        if crc_oracle is not None:
                            out = crc_oracle.run(('KEYGL5.xml', 'values.tsv'),
                                files={name: Path(folder, name).read_bytes() for name in ('KEYGL5.xml', 'values.tsv')})
                        else:
                            out=mono('mcs -r:/input/CBusLogicModel.dll -r:System.Windows.Forms -r:System.Xml.Linq NativeEdltProbe.cs && MONO_PATH=/input mono NativeEdltProbe.exe KEYGL5.xml values.tsv')
                        crcs={parts[1]:tuple(int(n,16) for n in parts[2].split()) for line in out.splitlines() if (parts:=line.split(':'))[0]=='pp-crc'}
                        self.assertEqual(crcs,editor.crcs(final));session.save_to_source()
                    for command in ('PROJECT SAVE ','PROJECT CLOSE ','PROJECT LOAD ','NET LOAD DB '):client.command(command+project)
                    with programmer.load(network,'/db'+unit) as session:
                        self.assertEqual(editor.snapshot(session.values()),final)
                        with self.assertRaises(EdltError):editor.configure(session,page=4,position=4,page_mode='multiple',group=43,levels=1,low_index=1)
                        self.assertEqual(editor.snapshot(session.values()),final)
                    application_records = {}
                    for application in (48,95,96,127,136):
                        with programmer.load(network,'/db'+unit) as session:
                            session.set('PrimaryApplication',str(application))
                            selected=editor.plan(session.values(),page=1,position=1,page_mode='multiple',group=43,
                                application='primary',label_type='dynamic-text',label_index=2)
                            editor.apply(session,selected)
                            self.assertEqual(selected.application,application)
                            self.assertEqual(session.get_raw_data(0x2c0,32).lines[-1].split('RawData=')[1],selected.record.hex())
                            app_final=editor.snapshot(session.values())
                            self.assertEqual(app_final['Application'],(application,57))
                            Path(folder,'values.tsv').write_text(''.join(name+'\t'+(value if isinstance(value,str) else ' '.join(hex(n) for n in value))+'\n' for name,value in app_final.items()))
                            if crc_oracle is not None:
                                crc_out = crc_oracle.run(('KEYGL5.xml', 'values.tsv'),
                                    files={name: Path(folder, name).read_bytes() for name in ('KEYGL5.xml', 'values.tsv')})
                            else:
                                crc_out=mono('MONO_PATH=/input mono NativeEdltProbe.exe KEYGL5.xml values.tsv')
                            original_crcs={parts[1]:tuple(int(n,16) for n in parts[2].split()) for line in crc_out.splitlines() if (parts:=line.split(':'))[0]=='pp-crc'}
                            self.assertEqual(original_crcs,editor.crcs(app_final))
                            session.save_to_source()
                        for command in ('PROJECT SAVE ','PROJECT CLOSE ','PROJECT LOAD ','NET LOAD DB '):client.command(command+project)
                        with programmer.load(network,'/db'+unit) as session:
                            self.assertEqual(editor.snapshot(session.values()),app_final)
                        application_records[str(application)]={'record':selected.record.hex(),'crcs':original_crcs,'saved_reloaded':True}
                    report['applications']=application_records
                    self.assertTrue(any('state=new' in line for line in client.command('GET '+network+' state').lines))
                    report.update(passed=True,dll_stdout=model,crcs=crcs,first=first.as_dict(),last=last.as_dict(),records=NATIVE,
                                  dll_sha256=hashlib.sha256((app/'CBusLogicModel.dll').read_bytes()).hexdigest())
                finally:
                    client.command('PROJECT CLOSE '+project);client.command('PROJECT DELETE '+project)
                    if os.environ.get('CBUS_EDLT_MULTILEVEL_REPORT'):Path(os.environ['CBUS_EDLT_MULTILEVEL_REPORT']).write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':unittest.main()
