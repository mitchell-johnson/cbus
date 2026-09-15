"""Independent EnableData vectors and exact native database PP acceptance."""
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
from cbus_toolkit.edlt_enable import EdltEnableWidget
from cbus_toolkit.unitspec import UnitSpecStore
from test_edlt import fixture, Session

# Literal output of unchanged Toolkit1.18 CBusLogicModel.dll EnableData.
DEFAULT = '0E0022210000FF0A17FF00000000000000000000000000000000000000000000'
STATIC = '0E35222100002A0A177F003F3E00000000000000000000000000000000000000'
ICONS = '0E27222100002A0A177F00010300000000000000000000000000000000000000'
TEXT = '0E16222100002A0A177F00020000000000000000000000000000000000000000'
REFRESHED = '0E27222100002B0A177F00020000000000000000000000000000000000000000'
HIGH_BIT = '0EA7222100002B0A177F00020000000000000000000000000000000000000000'
ZERO = '0EA7222100002B0A170000020000000000000000000000000000000000000000'
MAXIMUM = '0EA7222100002B0A17FF00020000000000000000000000000000000000000000'
STATUS_LEVEL = '0EA1222100002B0A17FF00020000000000000000000000000000000000000000'
STATUS_PERCENT = '0EA2222100002B0A17FF00020000000000000000000000000000000000000000'
STATUS_BAR = '0EA3222100002B0A17FF00020000000000000000000000000000000000000000'
OPAQUE = '0E0022210405FF0A17090A00000D0E0F101112131415161718191A1B1C1D1E1F'
OPAQUE_BLANK = '0E0022210405FF0A17090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F'


def after(plan):
    result = dict(plan.expected); result.update(plan.changes)
    return result


class EnableWidgetTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltEnableWidget(self.spec)
        self.session = Session(self.spec)

    def plan(self, current=None, **options):
        settings = dict(page=1, position=1, variable=42, level=127)
        settings.update(options)
        return self.editor.plan(self.session.values() if current is None else current, **settings)

    def test_literal_static_dynamic_and_fixed_application(self):
        plan = self.plan(label_text='Enable name', status_text='Ready')
        self.assertEqual(plan.record.hex().upper(), STATIC)
        self.assertEqual((plan.static_allocation.index, plan.status_allocation.index), (63, 62))
        plan = self.plan(after(plan), label_type='dynamic-icon', label_index=1,
                         status_type='dynamic-icon', status_index=3)
        self.assertEqual(plan.record.hex().upper(), ICONS)
        plan = self.plan(after(plan), label_type='dynamic-text', label_index=2,
                         status_type='dynamic-text', status_index=0)
        self.assertEqual(plan.record.hex().upper(), TEXT)
        current = after(plan)
        other = EdltLighting(self.spec).plan(current, page=1, position=2, group=43,
                                            restore_level=137, mode='off-on')
        current = after(other)
        plan = self.plan(current, variable=43, label_type='dynamic-icon', status_type='dynamic-icon')
        self.assertEqual(plan.record.hex().upper(), REFRESHED)
        self.assertEqual((plan.restore_level, plan.restore_source_widget), (137, 7))
        current = after(plan); current['Widget6WidgetByteValue1'] = (0xa7,)
        current['SecondaryApplication'] = (255,)
        plan = self.plan(current, variable=43)
        self.assertEqual(plan.record.hex().upper(), HIGH_BIT)
        self.assertEqual(plan.as_dict()['application'], 203)
        for level, literal in ((0, ZERO), (255, MAXIMUM)):
            boundary = self.plan(after(plan), variable=43, level=level)
            self.assertEqual(boundary.record.hex().upper(), literal)
        for status, literal in (('level', STATUS_LEVEL), ('percent', STATUS_PERCENT), ('bar', STATUS_BAR)):
            styled = self.plan(after(plan), variable=43, level=255, status_type=status)
            self.assertEqual(styled.record.hex().upper(), literal)

    def test_restore_first_numeric_match_preserved_same_variable_and_no_match(self):
        current = after(self.plan())
        for widget, kind, restore in ((7, 2, 137), (8, 14, 99)):
            current[f'Widget{widget}WidgetType'] = (kind,)
            current[f'Widget{widget}WidgetByteValue6'] = (43,)
            current[f'Widget{widget}RestoreLevel'] = (restore,)
        plan = self.plan(current, variable=43)
        self.assertEqual((plan.restore_level, plan.restore_source_widget), (137, 7))
        for name in current:
            if name.startswith(('Widget7', 'Widget8')): self.assertNotIn(name, plan.changes)
        same = after(plan); same['Widget6RestoreLevel'] = (88,)
        self.assertEqual(self.plan(same, variable=43).restore_level, 88)
        missing = self.plan(same, variable=44)
        self.assertEqual((missing.restore_level, missing.restore_source_widget), (0, None))
        fresh = dict(current); fresh['Widget6WidgetType'] = (0,)
        self.assertEqual(self.plan(fresh, variable=43).restore_level, 137)
        # A scene's byte6 is a scene index, not an AppGroup variable.
        current['Widget7WidgetType'] = (6,)
        self.assertEqual(self.plan(current, variable=43).restore_source_widget, 8)

    def test_opaque_default_and_inactive_values_are_preserved(self):
        for control, literal in ((255, OPAQUE), (0, OPAQUE_BLANK)):
            current = self.session.values()
            for index in range(1, 32): current[f'Widget6WidgetByteValue{index}'] = (index,)
            current['Widget6WidgetByteValue1'] = (control,)
            current['Widget6WidgetByteValue7'] = (23,)
            plan = self.plan(current, level=9)
            expected = bytearray.fromhex(literal); expected[6] = 42
            self.assertEqual(plan.record, bytes(expected))
            for index in (4, 5, 10, *range(13, 32)):
                self.assertNotIn(f'Widget6WidgetByteValue{index}', plan.changes)
        current = after(self.plan(label_type='dynamic-icon', label_index=3, status_type='dynamic-icon', status_index=2))
        blank = self.plan(current, label_type='blank', status_type='blank')
        self.assertEqual(blank.record[11:13], b'\0\0')

    def test_dynamic_metadata_guard_and_explicit_reference_type(self):
        current = after(self.plan(label_type='dynamic-text', label_index=1,
                                  status_type='dynamic-icon', status_index=2))
        for options in ({'variable': 43}, {'label_index': 2}, {'status_index': 1},
                        {'variable': 43, 'label_type': 'dynamic-icon'}):
            with self.subTest(options=options), self.assertRaisesRegex(EdltError, 'explicit'):
                self.plan(current, **options)
        same = self.plan(current, label_index=1, status_index=2)
        self.assertEqual(same.record[11:13], bytes((1, 2)))
        changed = self.plan(current, variable=43, label_type='static', label_index=1, status_type='blank')
        self.assertEqual(changed.record[1], 0x30)

    def test_shared_text_reuse_whole_unit_references_and_exhaustion(self):
        current = self.session.values()
        current['Widget1WidgetType'] = (7,); current['Widget1WidgetByteValue11'] = (63,)
        plan = self.plan(current, label_text='New text', status_text='New text')
        self.assertEqual((plan.static_allocation.index, plan.status_allocation.index), (62, 62))
        self.assertTrue(plan.status_allocation.reused)
        self.assertNotIn('StaticTextString63', plan.changes)
        self.assertEqual(self.plan(label_text='Lamp').static_allocation.index, 1)
        current = after(self.plan())
        index = 0
        for widget in range(7, 22):
            current[f'Widget{widget}WidgetType'] = (16,)
            current[f'Widget{widget}WidgetByteValue1'] = (0x35,)
            for offset in range(9, 14):
                current[f'Widget{widget}WidgetByteValue{offset}'] = (min(index, 63),); index += 1
        with self.assertRaisesRegex(EdltError, 'free|available|full|unused'):
            self.plan(current, label_text='Full table new text')

    def test_range_types_display_and_layout_guards(self):
        for options in ({'variable': 255}, {'variable': -1}, {'variable': True}, {'variable': '42'},
                        {'level': 256}, {'level': -1}, {'level': False}, {'page': 2}, {'position': 6},
                        {'label_type': []}, {'status_type': {}}, {'status_type': 'timer'},
                        {'label_index': 0}, {'status_index': 0},
                        {'label_type': 'dynamic-icon', 'label_index': 4},
                        {'status_type': 'static', 'status_index': 64},
                        {'label_text': 'a\0b'}, {'status_text': 'ā' * 32}, {'label_text': ' '},
                        {'label_text': 'Hi', 'label_index': 1}, {'status_text': 'Hi', 'status_type': 'level'}):
            with self.subTest(options=options), self.assertRaises(EdltError): self.plan(**options)
        for control in (0x40, 0x04):
            current = after(self.plan()); current['Widget6WidgetByteValue1'] = (control,)
            with self.assertRaises(EdltError): self.plan(current)
        for index, kind in ((1, 14), (6, 2), (7, 14)):
            current = self.session.values(); current[f'Widget{index}WidgetType'] = (kind,)
            with self.assertRaises(EdltError): self.plan(current)
        self.assertFalse(self.session.calls)

    def test_page_limits_terminators_and_unrelated_values(self):
        plan = self.plan(page=4, position=4, page_mode='multiple')
        self.assertEqual(plan.widget, 21)
        final = after(plan)
        for index in range(6, 21): self.assertEqual(final[f'Widget{index}WidgetType'], (0,))
        self.assertEqual(self.plan(position=5).widget, 10)
        for name in final:
            if name.startswith(('Scene', 'StaticTextString')) and name != 'ScenesCheckSum':
                self.assertEqual(final[name], plan.expected[name])

    def test_rollback_and_no_recovery_after_disconnect(self):
        plan = self.plan(label_text='Enable name', status_text='Ready')
        original = self.editor.snapshot(self.session.values())
        self.session.failure = 'Widget6WidgetByteValue7'
        with self.assertRaises(EdltApplyError) as caught: self.editor.apply(self.session, plan)
        self.assertEqual(self.editor.snapshot(self.session.values()), original)
        self.assertTrue(caught.exception.details['rollback_verified'])
        self.assertFalse(caught.exception.details['saved'])
        self.session.calls.clear()
        initial = self.session.set
        def fail(name, value):
            initial(name, value); self.session.connected = False
            raise TimeoutError('Injected disconnect')
        self.session.set = fail
        with self.assertRaises(EdltApplyError) as caught: self.editor.apply(self.session, plan)
        self.assertEqual(len(self.session.calls), 1)
        self.assertIn('Connection lost', caught.exception.rollback_errors[0])

    def test_profile_stale_forged_plan_identity_and_unsaved_apply(self):
        for settings in ({'catalog_number': '5055EDLB'}, {'firmware': '6.0.00'}):
            with self.assertRaises(EdltError): EdltEnableWidget(self.spec, **settings)
        plan = self.plan()
        for forged in (None, replace(plan, widget=True), replace(plan, record=b'x'),
                       replace(plan, restore_level=255), replace(plan, variable=43),
                       replace(plan, changes={**plan.changes, 'SceneCount': (8,)})):
            with self.assertRaises(EdltError): self.editor.apply(self.session, forged)
        self.session.current['SceneCount'] = (8,)
        with self.assertRaisesRegex(EdltError, 'changed'): self.editor.apply(self.session, plan)
        self.session.current['SceneCount'] = (0,)
        result = self.editor.apply(self.session, plan)
        self.assertTrue(result['verified']); self.assertFalse(result['saved'])
        self.assertFalse(result['physical_device_verified'])
        self.session.identity['UnitType'] = 'KEY4'
        self.session.values = lambda: self.fail('Identity guard must precede PP read')
        with self.assertRaisesRegex(EdltError, 'identity'): self.editor.configure(self.session)


@unittest.skipUnless(all(os.environ.get(key) for key in ('CBUS_CGATE_TEST_HOST', 'CBUS_UNITSPEC_DIR', 'CBUS_TOOLKIT_EXE')),
                     'Set C-Gate host, specifications and Toolkit EXE for native Enable widget acceptance')
class NativeEnableWidgetTests(unittest.TestCase):
    def test_original_dll_native_raw_crc_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.programming import Programmer
        from research.original_oracle import OriginalModelOracle, selected_backend
        root = Path(__file__).resolve().parents[1]
        app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        specs = Path(os.environ['CBUS_UNITSPEC_DIR']).resolve()
        spec = UnitSpecStore(specs).load('KEYGL5.xml')
        editor = EdltEnableWidget(spec)
        project = 'EEN' + uuid4().hex[:5].upper()
        network, unit = f'//{project}/254', f'//{project}/254/p/20'
        report = {'project': project, 'scope': '5055EDL5.5 Enable Off/Preset database PP; no physical device', 'passed': False}
        backend = selected_backend(); report['original_backend'] = backend
        with tempfile.TemporaryDirectory() as folder:
            for name in ('NativeEdltEnableProbe.cs', 'NativeEdltProbe.cs'):
                Path(folder, name).write_bytes((root / 'research' / name).read_bytes())
            def mono(command):
                result = subprocess.run(['docker', 'run', '--rm', '-v', str(app) + ':/input:ro', '-v', folder + ':/work', '-w', '/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5', 'sh', '-c', command],
                    capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            oracle = OriginalModelOracle(root / 'research/NativeEdltEnableProbe.cs', app, backend='windows') if backend == 'windows' else None
            crc_oracle = OriginalModelOracle(root / 'research/NativeEdltProbe.cs', app, backend='windows') if backend == 'windows' else None
            if oracle is not None:
                self.addCleanup(oracle.close); self.addCleanup(crc_oracle.close)
                native = oracle.run()
            else:
                native = mono('mcs -r:/input/CBusLogicModel.dll -r:System.Windows.Forms -r:System.Drawing NativeEdltEnableProbe.cs && MONO_PATH=/input mono NativeEdltEnableProbe.exe')
            for expected in (DEFAULT, STATIC, ICONS, TEXT, OPAQUE, OPAQUE_BLANK):
                self.assertIn(':' + expected + ':0', native)
            for expected in (REFRESHED, HIGH_BIT, ZERO, MAXIMUM, STATUS_LEVEL, STATUS_PERCENT, STATUS_BAR):
                self.assertIn(':' + expected + ':137', native)
            self.assertIn('fixed-application:203', native.splitlines())
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')), timeout=30) as client:
                client.command('PROJECT NEW ' + project)
                try:
                    for text in ('PROJECT USE ' + project, f'DBSET //{project}/Project/Description cbus-toolkit-isolated-edlt-enable-v1',
                                 'DBCREATENET 254 Offline Cni 127.0.0.1:1', 'PROJECT SAVE ' + project,
                                 f'DBADDSAFE {network} Unit 20 EDLT'):
                        client.command(text)
                    for key, value in (('UnitType', 'KEYGL5'), ('UnitName', 'EDLT'), ('FirmwareVersion', '5.5.00'), ('CatalogNumber', '5055EDL')):
                        client.command(f'DBSET {unit}/{key} {value}')
                    client.command('NET LOAD DB ' + project)
                    programmer = Programmer(client)
                    with programmer.load(network, '/db' + unit) as session:
                        session.reset_defaults()
                        original = editor.snapshot(session.values())
                        plan = editor.plan(original, page=1, position=1, variable=42, level=127,
                                           label_text='Enable name', status_text='Ready')
                        self.assertEqual(plan.record.hex().upper(), STATIC)
                        self.assertTrue(editor.apply(session, plan)['verified'])
                        self.assertEqual(session.get_raw_data(0x2c0, 32).lines[-1].split('RawData=')[1], STATIC.lower())
                        for slot, text in ((63, 'Enable name'), (62, 'Ready')):
                            self.assertEqual(session.get_raw_data(0x1100 + slot * 64, 64).lines[-1].split('RawData=')[1],
                                             text.encode().ljust(64, b'\0').hex())
                        for settings, literal in ((dict(label_type='dynamic-icon', label_index=1, status_type='dynamic-icon', status_index=3), ICONS),
                                                  (dict(label_type='dynamic-text', label_index=2, status_type='dynamic-text', status_index=0), TEXT)):
                            next_plan = editor.plan(session.values(), page=1, position=1, variable=42, level=127, **settings)
                            self.assertEqual(next_plan.record.hex().upper(), literal)
                            self.assertTrue(editor.apply(session, next_plan)['verified'])
                            self.assertEqual(session.get_raw_data(0x2c0, 32).lines[-1].split('RawData=')[1], literal.lower())
                        other = EdltLighting(spec).plan(session.values(), page=1, position=2, group=43, restore_level=137, mode='off-on')
                        EdltLighting(spec).apply(session, other)
                        prior = editor.snapshot(session.values())
                        refreshed = editor.plan(prior, page=1, position=1, variable=43, level=127,
                                                label_type='dynamic-icon', status_type='dynamic-icon')
                        self.assertEqual(refreshed.record.hex().upper(), REFRESHED)
                        self.assertEqual((refreshed.restore_level, refreshed.restore_source_widget), (137, 7))
                        self.assertTrue(editor.apply(session, refreshed)['verified'])
                        self.assertEqual(session.get_raw_data(0x1a0, 1).lines[-1].split('RawData=')[1], '89')
                        self.assertEqual(session.get_raw_data(0x2c0, 32).lines[-1].split('RawData=')[1], REFRESHED.lower())
                        session.set('Widget6WidgetByteValue1', '167')
                        for options, literal in ((dict(level=0), ZERO), (dict(level=255), MAXIMUM),
                                (dict(level=255, status_type='level'), STATUS_LEVEL),
                                (dict(level=255, status_type='percent'), STATUS_PERCENT),
                                (dict(level=255, status_type='bar'), STATUS_BAR)):
                            style = editor.plan(session.values(), page=1, position=1, variable=43, **options)
                            self.assertEqual(style.record.hex().upper(), literal)
                            editor.apply(session, style)
                            self.assertEqual(session.get_raw_data(0x2c0, 32).lines[-1].split('RawData=')[1], literal.lower())
                        last = editor.plan(session.values(), page=4, position=4, page_mode='multiple', variable=43, level=255,
                                           label_text='Shared', status_text='Shared')
                        self.assertEqual(last.static_allocation.index, last.status_allocation.index)
                        editor.apply(session, last)
                        self.assertEqual(session.get_raw_data(0x4a0, 32).lines[-1].split('RawData=')[1], last.record.hex())
                        final = editor.snapshot(session.values())
                        for name in final:
                            if name.startswith('Scene') and name != 'ScenesCheckSum': self.assertEqual(final[name], original[name])
                            if name.startswith('Widget7'): self.assertEqual(final[name], prior[name])
                        Path(folder, 'KEYGL5.xml').write_bytes((specs / 'KEYGL5.xml').read_bytes())
                        Path(folder, 'values.tsv').write_text(''.join(name + '\t' + (value if isinstance(value, str) else
                            ' '.join(hex(n) for n in value)) + '\n' for name, value in final.items()))
                        if crc_oracle is not None:
                            crc_output = crc_oracle.run(('KEYGL5.xml', 'values.tsv'),
                                files={name: Path(folder, name).read_bytes() for name in ('KEYGL5.xml', 'values.tsv')})
                        else:
                            crc_output = mono('mcs -r:/input/CBusLogicModel.dll -r:System.Windows.Forms -r:System.Xml.Linq NativeEdltProbe.cs && MONO_PATH=/input mono NativeEdltProbe.exe KEYGL5.xml values.tsv')
                        crcs = {}
                        for line in crc_output.splitlines():
                            if line.startswith('pp-crc:'):
                                _, name, value = line.split(':'); crcs[name] = tuple(int(n, 16) for n in value.split())
                        self.assertEqual(crcs, editor.crcs(final))
                        session.save_to_source()
                    for command in ('PROJECT SAVE ', 'PROJECT CLOSE ', 'PROJECT LOAD ', 'NET LOAD DB '): client.command(command + project)
                    with programmer.load(network, '/db' + unit) as session:
                        self.assertEqual(editor.snapshot(session.values()), final)
                        with self.assertRaisesRegex(EdltError, 'explicit'):
                            editor.configure(session, page=1, position=1, variable=44, level=0)
                        self.assertEqual(editor.snapshot(session.values()), final)
                    self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                    report.update(passed=True, dll_stdout=native, crcs=crcs, first=plan.as_dict(), refreshed=refreshed.as_dict(), last=last.as_dict(),
                                  dll_sha256=hashlib.sha256((app / 'CBusLogicModel.dll').read_bytes()).hexdigest())
                finally:
                    client.command('PROJECT CLOSE ' + project)
                    client.command('PROJECT DELETE ' + project)
                    if os.environ.get('CBUS_EDLT_ENABLE_REPORT'):
                        Path(os.environ['CBUS_EDLT_ENABLE_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__': unittest.main()
