"""Measurement standby locations through original model and native PP bytes."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from uuid import uuid4

from cbus_toolkit.edlt import EdltError, _field
from cbus_toolkit.edlt_measurement import EdltMeasurementWidget
from cbus_toolkit.unitspec import UnitSpecStore
from tests.test_edlt import Session
from tests.test_edlt_measurement import DEFAULT, SCALED, after, fixture

NATIVE_TEXT = '0C2A03017D00FEFFE7FF123F8740000000000000000000000000000000000000'
EXTREMES = '0CFEFE050080807FFF7FFFFF8740000000000000000000000000000000000000'


def record(current, widget):
    return bytes(current[_field(widget, i)][0] for i in range(32))


class MeasurementStandbyTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture(); self.editor = EdltMeasurementWidget(self.spec); self.session = Session(self.spec)

    def plan(self, current=None, **options):
        settings = dict(page=0, position=1, device_id=0, channel=0); settings.update(options)
        return self.editor.plan(self.session.values() if current is None else current, **settings)

    def test_all_original_standby_positions_and_missing_restore_fields(self):
        original = self.editor.snapshot(self.session.values())
        for mode in ('single', 'multiple'):
            for position in range(1, 6):
                plan = self.plan(position=position, page_mode=mode)
                self.assertEqual(plan.record.hex().upper(), DEFAULT)
                self.assertEqual(plan.widget, position); self.assertEqual(plan.page, 0)
                self.assertIsNone(plan.restore_level); self.assertIsNone(plan.as_dict()['restore_level'])
                self.assertFalse(any(f'Widget{n}RestoreLevel' in after(plan) for n in range(1, 6)))
                self.assertEqual(after(plan)['NavWidgetType'], (int(mode == 'multiple'),))
                self.assertEqual(plan.record[13], 64)
                self.assertFalse(self.plan(after(plan), position=position).changes)
        self.assertEqual(self.editor.snapshot(self.session.values()), original)

    def test_covered_slots_types_and_forged_restore_guard(self):
        source = self.editor.snapshot(self.session.values())
        for position in range(2, 6):
            current = dict(source); current[_field(position-1)] = (11,); current[_field(position)] = (0,)
            with self.assertRaisesRegex(EdltError, 'covered'): self.plan(current, position=position)
        for kind in (10, 11, 13):
            current = dict(source); current[_field(1)] = (kind,)
            with self.assertRaisesRegex(EdltError, 'another type'): self.plan(current)
        for widget, kind in ((1, 2), (5, 11), (6, 11)):
            current = dict(source); current[_field(widget)] = (kind,)
            with self.assertRaises(EdltError): self.plan(current)
        for options in (dict(position=0), dict(position=6), dict(page=-1), dict(page=5)):
            with self.assertRaises(EdltError): self.plan(**options)
        plan = self.plan()
        with self.assertRaisesRegex(EdltError, 'RestoreLevel'): self.editor.apply(self.session, replace(plan, restore_level=0))
        self.assertFalse(self.session.calls)
        result = self.editor.apply(self.session, plan); self.assertTrue(result['verified'])

    def test_signed_pairs_opaque_and_functional_neighbor_preserved(self):
        first = self.editor.plan(self.session.values(), page_mode='multiple', page=4, position=4, device_id=254, channel=3)
        original = after(first); original['Widget21RestoreLevel'] = (137,)
        for i in range(14, 32): original[_field(5, i)] = (i,)
        original.update(self.editor.crcs(original))
        plan = self.plan(original, position=5, device_id=42, channel=3, decimal_places=1,
                         gain_mantissa=125, gain_exponent=-2, offset_mantissa=-25, offset_exponent=-1)
        self.assertEqual(plan.record[:14], bytes.fromhex(SCALED)[:14])
        self.assertEqual(plan.record[14:], bytes(range(14, 32)))
        self.assertEqual(record(after(plan), 21), record(original, 21))
        self.assertEqual(after(plan)['Widget21RestoreLevel'], (137,))
        self.assertEqual(after(plan)['NavWidgetType'], (1,))
        self.assertFalse(any(name.startswith('Widget21') for name in plan.changes))
        current = after(plan); current[_field(5, 4)] = (0,); current[_field(5, 5)] = (0,)
        normalized = self.plan(current, position=5, device_id=42, channel=3)
        self.assertTrue(normalized.gain_normalized); self.assertEqual(normalized.record[4:7], bytes((1, 0, 254)))
        self.assertIsNone(normalized.restore_level)
        self.assertEqual(self.plan(device_id=254, channel=254, decimal_places=5, gain_mantissa=-32768,
            gain_exponent=-128, offset_mantissa=32767, offset_exponent=127).record.hex().upper(), EXTREMES)


@unittest.skipUnless(all(os.environ.get(key) for key in ('CBUS_CGATE_TEST_HOST','CBUS_UNITSPEC_DIR','CBUS_TOOLKIT_EXE')),
                     'Set native C-Gate, unit specifications and Toolkit EXE for standby acceptance')
class NativeMeasurementStandbyTests(unittest.TestCase):
    def test_original_signed_pairs_raw_bytes_crcs_and_full_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.programming import Programmer
        root = Path(__file__).resolve().parents[1]; app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        specs = Path(os.environ['CBUS_UNITSPEC_DIR']).resolve(); editor = EdltMeasurementWidget(UnitSpecStore(specs).load('KEYGL5.xml'))
        project = 'EST'+uuid4().hex[:5].upper(); network = '//'+project+'/254'; unit = network+'/p/20'
        report = {'passed': False, 'project': project, 'physical_device_verified': False, 'cases': []}
        from research.original_oracle import OriginalModelOracle, selected_backend
        backend = selected_backend(); report['original_backend'] = backend
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'NativeEdltMeasurementStandbyProbe.cs').write_bytes((root/'research/NativeEdltMeasurementStandbyProbe.cs').read_bytes())
            Path(directory, 'KEYGL5.xml').write_bytes((specs/'KEYGL5.xml').read_bytes())
            def mono(command):
                result = subprocess.run(['docker','run','--rm','-v',str(app)+':/input:ro','-v',directory+':/work','-w','/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5','sh','-c',command],
                    capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr); return result.stdout
            oracle = OriginalModelOracle(root / 'research/NativeEdltMeasurementStandbyProbe.cs', app, backend='windows', references=('eDLT.dll',)) if backend == 'windows' else None
            if oracle is not None:
                self.addCleanup(oracle.close); original = oracle.run()
            else:
                original = mono('mcs -r:/input/CBusLogicModel.dll -r:/input/eDLT.dll -r:System.Windows.Forms -r:System.Drawing -r:System.Xml.Linq NativeEdltMeasurementStandbyProbe.cs && MONO_PATH=/input mono NativeEdltMeasurementStandbyProbe.exe')
            for widget in range(1, 6):
                self.assertIn(f'ui-available-{widget}:True', original)
                self.assertIn(f'default-{widget}:{DEFAULT}:none', original)
                self.assertIn(f'scaled-{widget}:{SCALED}:none', original)
                self.assertIn(f'has-restore-{widget}:False', original)
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=30) as client:
                projects = NativeProjects(client); db = NativeDatabase(client); programmer = Programmer(client)
                projects.operation('new',project)
                try:
                    db.create_network(project,254,'Measurement_Standby','Cni','127.0.0.1:1'); projects.operation('save',project)
                    db.create_unit(network,20,'EDLT','KEYGL5','5.5.00',catalog_number='5055EDL'); projects.operation('save',project)
                    cases = ((1,dict(device_id=0,channel=0),DEFAULT),
                             (5,dict(device_id=42,channel=3,decimal_places=1,gain_mantissa=125,gain_exponent=-2,
                                     offset_mantissa=-25,offset_exponent=-1,prefix_text='Temperature',suffix_text='C',label_index=64),NATIVE_TEXT),
                             (3,dict(device_id=254,channel=254,decimal_places=5,gain_mantissa=-32768,gain_exponent=-128,
                                     offset_mantissa=32767,offset_exponent=127),EXTREMES))
                    for widget, settings, literal in cases:
                        with programmer.load(network,'/db'+unit) as session:
                            session.reset_defaults(); session.set('ConfigVersionMajor','1'); session.set('ConfigVersionMinor','0')
                            for slot in range(1,9): session.set(f'Scene{slot}StartAddress','255')
                            if widget == 5:
                                functional = editor.plan(session.values(),page_mode='multiple',page=4,position=4,device_id=1,channel=1)
                                editor.apply(session,functional); session.set('Widget21RestoreLevel','137')
                            source = editor.snapshot(session.values())
                            plan = editor.plan(source,page=0,position=widget,**settings)
                            self.assertEqual(plan.record.hex().upper(),literal); self.assertIsNone(plan.restore_level)
                            Path(directory,'values.tsv').write_text(''.join(k+'\t'+(v if isinstance(v,str) else ' '.join(hex(n) for n in v))+'\n' for k,v in source.items()))
                            label = '@'+str(settings['label_index']) if 'label_index' in settings else settings.get('label_text','-')
                            args = [widget,plan.device_id,plan.channel,plan.decimal_places,plan.gain_mantissa,plan.gain_exponent,
                                    plan.offset_mantissa,plan.offset_exponent,settings.get('prefix_text','-'),settings.get('suffix_text','-'),label]
                            if oracle is not None:
                                output = oracle.run(('KEYGL5.xml', 'values.tsv', *map(str,args)), files={name: Path(directory,name).read_bytes() for name in ('KEYGL5.xml','values.tsv')})
                            else:
                                output = mono('MONO_PATH=/input mono NativeEdltMeasurementStandbyProbe.exe KEYGL5.xml values.tsv '+shlex.join(map(str,args)))
                            parsed = {line[3:].split('\t',1)[0]:line.split('\t',1)[1] for line in output.splitlines() if line.startswith('pp:')}
                            for line in output.splitlines():
                                if line.startswith('memory-static:'):
                                    index,value = line[14:].split('\t',1); parsed['StaticTextString'+index] = value
                            expected = editor.snapshot(parsed)
                            self.assertEqual({k:(v,expected[k]) for k,v in after(plan).items() if v!=expected[k]}, {})
                            self.assertEqual({k:expected[k] for k in editor.crcs(expected)},editor.crcs(expected))
                            editor.apply(session,plan)
                            self.assertEqual(session.get_raw_data(0x220+(widget-1)*32,32).lines[-1].split('RawData=')[1],literal.lower())
                            values = session.values()
                            self.assertFalse(any(f'Widget{n}RestoreLevel' in values for n in range(1,6)))
                            if widget == 5:
                                self.assertEqual(record(expected,21),record(source,21)); self.assertEqual(expected['Widget21RestoreLevel'],(137,))
                                for index in (18,63): self.assertEqual(session.get_raw_data(0x1100+64*index,64).lines[-1].split('RawData=')[1],bytes(expected[f'StaticTextString{index}']).hex())
                            session.save_to_source()
                        for action in ('save','close','load'): projects.operation(action,project)
                        client.command('NET LOAD DB '+project)
                        with programmer.load(network,'/db'+unit) as session: self.assertEqual(editor.snapshot(session.values()),expected)
                        report['cases'].append({'widget':widget,'literal':literal,'crcs':editor.crcs(expected),'restore_level':None,'saved_reloaded':True})
                    report['network_state'] = client.command('GET '+network+' state').lines
                    self.assertTrue(any('state=new' in line for line in report['network_state']))
                    report.update(passed=True,original_output=original,dll_sha256=hashlib.sha256((app/'CBusLogicModel.dll').read_bytes()).hexdigest())
                finally:
                    projects.operation('close',project); projects.operation('delete',project)
                    if os.environ.get('CBUS_EDLT_MEASUREMENT_STANDBY_REPORT'):
                        Path(os.environ['CBUS_EDLT_MEASUREMENT_STANDBY_REPORT']).write_text(json.dumps(report,indent=2)+'\n')


if __name__ == '__main__': unittest.main()
