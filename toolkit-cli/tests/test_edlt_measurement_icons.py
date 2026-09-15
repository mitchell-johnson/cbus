"""Measurement built-in icons: independent selector, original setter and native PP."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

from cbus_toolkit.edlt import EdltError, _field
from cbus_toolkit.edlt_measurement import EdltMeasurementWidget, BUILTIN_ICON_INDICES
from cbus_toolkit.unitspec import UnitSpecStore
from tests.test_edlt import Session
from tests.test_edlt_measurement import DEFAULT, after, fixture

ICONS = (*range(39), *range(128, 142), 252, 253, 254)
BLANK = '0C000002010000000000FFFF0040000000000000000000000000000000000000'
CUSTOM = '0C2A03017D00FEFFE7FF123F2640000000000000000000000000000000000000'
LAST = '0C000002010000000000FFFFFE40000000000000000000000000000000000000'


class MeasurementIconTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture(); self.editor = EdltMeasurementWidget(self.spec); self.session = Session(self.spec)

    def plan(self, current=None, **options):
        settings = dict(page=1, position=1, device_id=0, channel=0); settings.update(options)
        return self.editor.plan(self.session.values() if current is None else current, **settings)

    def test_exact_selector_set_and_literal_byte_twelve(self):
        self.assertEqual(set(BUILTIN_ICON_INDICES), set(ICONS)); self.assertEqual(len(ICONS), 56)
        original = self.editor.snapshot(self.session.values())
        for icon in range(256):
            with self.subTest(icon=icon):
                if icon in ICONS:
                    plan = self.plan(icon_index=icon)
                    self.assertEqual(plan.record[:12], bytes.fromhex(DEFAULT)[:12])
                    self.assertEqual(plan.record[12], icon)
                    self.assertEqual(plan.record[13:], bytes.fromhex(DEFAULT)[13:])
                    self.assertEqual(plan.icon_index, icon); self.assertTrue(plan.icon_editable)
                    self.assertEqual(plan.as_dict()['icon_index'], icon)
                else:
                    with self.assertRaises(EdltError): self.plan(icon_index=icon)
        self.assertEqual(self.plan(icon_index=0).record.hex().upper(), BLANK)
        self.assertEqual(self.plan(page_mode='multiple', page=4, position=4, icon_index=254).record.hex().upper(), LAST)
        self.assertEqual(self.editor.snapshot(self.session.values()), original); self.assertFalse(self.session.calls)

    def test_hidden_and_omitted_opaque_icons_preserve_without_writes(self):
        for page, position in ((0,1),(0,5),(1,1)):
            for big in (0,1):
                for raw in (39,200,255):
                    current = after(self.plan(page=page, position=position))
                    widget = position if page == 0 else 6
                    current[_field(widget,12)] = (raw,); current['UseBigIcon'] = (big,)
                    plan = self.plan(current, page=page, position=position)
                    self.assertEqual(plan.icon_index, raw); self.assertEqual(plan.record[12], raw)
                    self.assertEqual(plan.icon_editable, page != 0 and big == 1)
                    self.assertNotIn(_field(widget,12), plan.changes); self.assertNotIn('UseBigIcon', plan.changes)
                    if not plan.icon_editable:
                        self.session.current = current
                        with self.assertRaisesRegex(EdltError, 'functional.*UseBigIcon'):
                            self.editor.configure(self.session, page=page, position=position, device_id=0, channel=0, icon_index=135)
                        self.assertEqual(self.editor.snapshot(self.session.values()), current)
                        self.assertFalse(self.session.calls)

    def test_layout_types_forgery_and_visibility_staleness(self):
        for icon in (True,False,-1,256,1.0,'38'):
            with self.assertRaises(EdltError): self.plan(icon_index=icon)
        param = self.spec.parameters['UseBigIcon']
        for change in ({'Address':'0x119'},{'BitAddress':'3'},{'ArraySkip':'1'},{'ArraySize':'2'}):
            parameters = dict(self.spec.parameters)
            parameters['UseBigIcon'] = replace(param,fields={**param.fields,**change})
            with self.assertRaisesRegex(EdltError,'layout'): EdltMeasurementWidget(replace(self.spec,parameters=parameters))
        parameters = dict(self.spec.parameters); del parameters['UseBigIcon']
        with self.assertRaisesRegex(EdltError,'layout'): EdltMeasurementWidget(replace(self.spec,parameters=parameters))
        plan = self.plan(icon_index=38)
        for forged in (replace(plan,icon_index=True),replace(plan,icon_index=37),replace(plan,icon_editable=1),replace(plan,icon_editable=False)):
            with self.assertRaises(EdltError): self.editor.apply(self.session,forged)
        self.session.current['UseBigIcon'] = (0,)
        with self.assertRaisesRegex(EdltError,'changed'): self.editor.apply(self.session,plan)
        self.assertFalse(self.session.calls)


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'Set original Toolkit for Measurement icon execution')
class OriginalMeasurementIconTests(unittest.TestCase):
    def test_original_graphics_selector(self):
        root = Path(__file__).resolve().parents[1]; app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'icons.json'
            result = subprocess.run([sys.executable,str(root/'research/NativeEdltGraphicsProbe.py'),str(app/'EDLT_graphics.dll'),str(path)],
                                    capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr); evidence = json.loads(path.read_text())
        self.assertEqual(evidence['dll_sha256'],'e319379709c47f97dca477c4f631880f231c060530cb2ec45a3f731b1a5d1991')
        self.assertEqual(evidence['import_calls'],{'memset':1}); self.assertEqual(len(evidence['rows']),255)
        self.assertEqual(evidence['icon_indices'],list(ICONS[1:]))

    def test_original_setter_all_bytes_and_hidden_same_type(self):
        root = Path(__file__).resolve().parents[1]; app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        from research.original_oracle import OriginalModelOracle, selected_backend
        if selected_backend() == 'windows':
            with OriginalModelOracle(root/'research/NativeEdltMeasurementIconProbe.cs', app, backend='windows', references=('eDLT.dll',)) as oracle:
                original_output = oracle.run()
        else:
            with tempfile.TemporaryDirectory() as directory:
                Path(directory,'NativeEdltMeasurementIconProbe.cs').write_bytes((root/'research/NativeEdltMeasurementIconProbe.cs').read_bytes())
                result = subprocess.run(['docker','run','--rm','-v',str(app)+':/input:ro','-v',directory+':/work','-w','/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5','sh','-c',
                    'mcs -r:/input/CBusLogicModel.dll -r:/input/eDLT.dll -r:System.Windows.Forms -r:System.Drawing -r:System.Xml.Linq NativeEdltMeasurementIconProbe.cs && MONO_PATH=/input mono NativeEdltMeasurementIconProbe.exe'],
                    capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            original_output = result.stdout
        lines = original_output.splitlines(); self.assertEqual(len(lines),1290)
        for widget in (1,5,6,10,21):
            restore = 'none' if widget < 6 else '0'
            self.assertIn(f'default-{widget}:{DEFAULT}:{restore}',lines)
            for icon in range(256):
                literal = DEFAULT[:24]+f'{icon:02X}'+DEFAULT[26:]
                self.assertIn(f'icon-{widget}-{icon}:{literal}:{restore}',lines)
            literal = DEFAULT[:24]+'C8'+DEFAULT[26:]
            self.assertIn(f'hidden-same-type-{widget}:{literal}:{restore}',lines)


@unittest.skipUnless(all(os.environ.get(key) for key in ('CBUS_CGATE_TEST_HOST','CBUS_UNITSPEC_DIR','CBUS_TOOLKIT_EXE')),
                     'Set native C-Gate, specifications and Toolkit for Measurement icon PP acceptance')
class NativeMeasurementIconTests(unittest.TestCase):
    def test_literal_original_full_pp_five_crcs_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.programming import Programmer
        root = Path(__file__).resolve().parents[1]; app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        specs = Path(os.environ['CBUS_UNITSPEC_DIR']).resolve(); editor = EdltMeasurementWidget(UnitSpecStore(specs).load('KEYGL5.xml'))
        project = 'EMI'+uuid4().hex[:5].upper(); network = '//'+project+'/254'; source = '/db'+network+'/p/20'
        report = {'passed':False,'physical_device_verified':False,'cases':[]}
        from research.original_oracle import OriginalModelOracle, selected_backend
        backend = selected_backend(); report['original_backend'] = backend
        with tempfile.TemporaryDirectory() as directory:
            for name, path in (('NativeEdltMeasurementIconProbe.cs',root/'research/NativeEdltMeasurementIconProbe.cs'),('KEYGL5.xml',specs/'KEYGL5.xml')):
                Path(directory,name).write_bytes(path.read_bytes())
            def mono(command):
                result = subprocess.run(['docker','run','--rm','-v',str(app)+':/input:ro','-v',directory+':/work','-w','/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5','sh','-c',command],
                    capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr); return result.stdout
            oracle = OriginalModelOracle(root / 'research/NativeEdltMeasurementIconProbe.cs', app, backend='windows', references=('eDLT.dll',)) if backend == 'windows' else None
            if oracle is not None: self.addCleanup(oracle.close)
            else:mono('mcs -r:/input/CBusLogicModel.dll -r:/input/eDLT.dll -r:System.Windows.Forms -r:System.Drawing -r:System.Xml.Linq NativeEdltMeasurementIconProbe.cs')
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=30) as client:
                projects = NativeProjects(client); database = NativeDatabase(client); programmer = Programmer(client)
                projects.operation('new',project)
                try:
                    database.create_network(project,254,'Measurement_Icons','Cni','127.0.0.1:1')
                    database.create_unit(network,20,'EDLT','KEYGL5','5.5.00',catalog_number='5055EDL'); projects.operation('save',project)
                    cases = ((6,1,0,BLANK), (6,1,38,CUSTOM), (10,1,141,DEFAULT[:24]+'8D'+DEFAULT[26:]),
                             (21,1,254,LAST), (6,0,None,DEFAULT[:24]+'FF'+DEFAULT[26:]),
                             (1,1,None,DEFAULT[:24]+'27'+DEFAULT[26:]), (5,0,None,DEFAULT[:24]+'FF'+DEFAULT[26:]))
                    for widget,big,icon,literal in cases:
                        with programmer.load(network,source) as session:
                            session.reset_defaults(); session.set('ConfigVersionMajor','1'); session.set('ConfigVersionMinor','0')
                            for scene in range(1,9): session.set(f'Scene{scene}StartAddress','255')
                            session.set('UseBigIcon',str(big))
                            page,position = (0,widget) if widget<6 else (4,4) if widget==21 else (1,widget-5)
                            settings = dict(page=page,position=position,device_id=0,channel=0)
                            if widget==21: settings['page_mode']='multiple'; session.set('NavWidgetType','1')
                            if icon is None:
                                editor.apply(session,editor.plan(session.values(),**settings))
                                session.set(_field(widget,12),'39' if widget==1 else '255')
                            else: settings['icon_index']=icon
                            if icon==38: settings.update(device_id=42,channel=3,decimal_places=1,gain_mantissa=125,gain_exponent=-2,
                                                       offset_mantissa=-25,offset_exponent=-1,prefix_text='Temperature',suffix_text='C',label_index=64)
                            before = editor.snapshot(session.values()); plan = editor.plan(before,**settings)
                            self.assertEqual(plan.record.hex().upper(),literal)
                            Path(directory,'values.tsv').write_text(''.join(k+'\t'+(v if isinstance(v,str) else ' '.join(hex(n) for n in v))+'\n' for k,v in before.items()))
                            args = [widget,plan.device_id,plan.channel,plan.decimal_places,plan.gain_mantissa,plan.gain_exponent,
                                    plan.offset_mantissa,plan.offset_exponent,settings.get('prefix_text','-'),settings.get('suffix_text','-'),
                                    '@64' if icon==38 else '-',icon if icon is not None else '-']
                            if oracle is not None:
                                output = oracle.run(('KEYGL5.xml', 'values.tsv', *map(str, args)), files={name: Path(directory, name).read_bytes() for name in ('KEYGL5.xml', 'values.tsv')})
                            else:output = mono('MONO_PATH=/input mono NativeEdltMeasurementIconProbe.exe KEYGL5.xml values.tsv '+shlex.join(map(str,args)))
                            parsed = dict(line[3:].split('\t',1) for line in output.splitlines() if line.startswith('pp:'))
                            for line in output.splitlines():
                                if line.startswith('memory-static:'):
                                    index,value = line[14:].split('\t',1); parsed['StaticTextString'+index]=value
                            expected = editor.snapshot(parsed); self.assertEqual(after(plan),expected)
                            self.assertEqual({name:expected[name] for name in editor.crcs(expected)},editor.crcs(expected))
                            editor.apply(session,plan)
                            self.assertEqual(session.get_raw_data(0x220+(widget-1)*32,32).lines[-1].split('RawData=')[1],literal.lower())
                            self.assertEqual(expected['UseBigIcon'],before['UseBigIcon'])
                            for name in before:
                                if name.startswith('Scene') and name!='ScenesCheckSum': self.assertEqual(expected[name],before[name])
                            for invalid in (39,255):
                                with self.assertRaises(EdltError): editor.configure(session,**{**settings,'icon_index':invalid})
                            if not plan.icon_editable:
                                with self.assertRaisesRegex(EdltError,'functional.*UseBigIcon'): editor.configure(session,**{**settings,'icon_index':135})
                            self.assertEqual(editor.snapshot(session.values()),expected)
                            session.save_to_source()
                        for action in ('save','close','load'): projects.operation(action,project)
                        with programmer.load(network,source) as session: self.assertEqual(editor.snapshot(session.values()),expected)
                        report['cases'].append(dict(widget=widget,use_big_icon=big,requested_icon=icon,literal=literal,
                                                   crcs=editor.crcs(expected),parameters_compared=len(expected),saved_reloaded=True))
                    self.assertTrue(any('state=new' in line for line in client.command('GET '+network+' state').lines))
                    report.update(passed=True,network_state='new',network_opened=False,
                                  dll_sha256=hashlib.sha256((app/'CBusLogicModel.dll').read_bytes()).hexdigest())
                finally:
                    projects.operation('close',project); projects.operation('delete',project)
                    if os.environ.get('CBUS_EDLT_MEASUREMENT_ICONS_REPORT'):
                        Path(os.environ['CBUS_EDLT_MEASUREMENT_ICONS_REPORT']).write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__': unittest.main()
