"""Shutter original-model vectors, shared defaults and native PP acceptance."""
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
from cbus_toolkit.edlt_shutter import EdltShutterWidget
from cbus_toolkit.unitspec import UnitSpecStore
from test_edlt import fixture, Session

# Independent output of unchanged original ShutterRelayData properties.
DEFAULT = '033012110000FF0056AA3F000000000000000000000000000000000000000000'
BOUND_DEFAULT = '0330121100002A0056AA3F000000000000000000000000000000000000000000'
PRESETS = '03B0121100002A0106F83F000000000000000000000000000000000000000000'
STATIC = '03B5121100002A0106F83E3F0000000000000000000000000000000000000000'
TWO_KEY = '03B5121100002A0006F83E3F0000000000000000000000000000000000000000'
ICONS = '03A7121100002A0006F801030000000000000000000000000000000000000000'
TEXT = '0396121100002A0006F802000000000000000000000000000000000000000000'
SAME_INDEX_REFRESH = '03A7121100002A0006F802000000000000000000000000000000000000000000'
REFRESHED = '03A7121100002B0006F802000000000000000000000000000000000000000000'
LEVEL = '03A1121100002B0006F802000000000000000000000000000000000000000000'
PERCENT = '03A2121100002B0006F802000000000000000000000000000000000000000000'
BAR = '03A3121100002B0006F802000000000000000000000000000000000000000000'
OPAQUE = '033012110405FF0056AA3F000C0D0E0F101112131415161718191A1B1C1D1E1F'
OPAQUE_BLANK = '033012110405FF0056AA3F0B0C0D0E0F101112131415161718191A1B1C1D1E1F'
# Exact original-DLL outputs when Blind already exists at slot5, as it does in
# the native KEYGL5 default snapshot. Initial shared-table state matters.
REUSED_DEFAULT = '0330121100002A0056AA05000000000000000000000000000000000000000000'
REUSED_PRESETS = '03B0121100002A0106F805000000000000000000000000000000000000000000'
REUSED_STATIC = '03B5121100002A0106F83F3E0000000000000000000000000000000000000000'
REUSED_TWO_KEY = '03B5121100002A0006F83F3E0000000000000000000000000000000000000000'


def after(plan):
    result = dict(plan.expected); result.update(plan.changes)
    return result


class ShutterWidgetTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltShutterWidget(self.spec)
        self.session = Session(self.spec)

    def plan(self, current=None, **options):
        settings = dict(page=1, position=1, group=42)
        settings.update(options)
        return self.editor.plan(self.session.values() if current is None else current, **settings)

    def test_default_then_custom_text_has_original_allocation_side_effect(self):
        plan = self.plan()
        self.assertEqual(plan.record.hex().upper(), BOUND_DEFAULT)
        self.assertEqual(plan.default_label_allocation.index, 63)
        self.assertEqual(bytes(plan.changes['StaticTextString63']).rstrip(b'\0'), b'Blind')
        self.assertIsNone(plan.static_allocation)
        custom = self.plan(application='secondary', mode='two-key-presets', preset_left=6, preset_right=248,
                           label_text='Shade', status_text='Ready')
        self.assertEqual(custom.record.hex().upper(), STATIC)
        self.assertEqual((custom.default_label_allocation.index, custom.static_allocation.index,
                          custom.status_allocation.index), (63, 62, 63))
        # Ready replaces the now-unreferenced intermediate Blind in slot63.
        self.assertEqual(bytes(custom.changes['StaticTextString63']).rstrip(b'\0'), b'Ready')
        blank = self.plan(label_type='blank')
        self.assertEqual(bytes(blank.changes['StaticTextString63']).rstrip(b'\0'), b'Blind')
        self.assertEqual(blank.record[10], 0)
        unchanged = self.plan(after(plan))
        self.assertIsNone(unchanged.default_label_allocation)
        self.assertFalse(unchanged.changes)

    def test_original_mode_dynamic_and_status_vectors(self):
        plan = self.plan(application='secondary', mode='two-key-presets', preset_left=6, preset_right=248)
        self.assertEqual(plan.record.hex().upper(), PRESETS)
        for options, literal in ((dict(mode='two-key-presets', label_text='Shade', status_text='Ready'), STATIC),
                                 (dict(), TWO_KEY),
                                 (dict(label_type='dynamic-icon', label_index=1, status_type='dynamic-icon', status_index=3), ICONS),
                                 (dict(label_type='dynamic-text', label_index=2, status_type='dynamic-text', status_index=0), TEXT),
                                 (dict(group=43, label_type='dynamic-icon', status_type='dynamic-icon'), REFRESHED),
                                 (dict(group=43, status_type='level'), LEVEL),
                                 (dict(group=43, status_type='percent'), PERCENT),
                                 (dict(group=43, status_type='bar'), BAR)):
            plan = self.plan(after(plan), application='secondary', **options)
            self.assertEqual(plan.record.hex().upper(), literal)
        self.assertEqual(plan.record[8:10], bytes((6, 248)))
        self.assertEqual(plan.as_dict()['application'], 57)

    def test_opaque_bytes_blank_status_and_preset_validation(self):
        for control, literal in ((255, OPAQUE), (0, OPAQUE_BLANK)):
            current = self.session.values()
            for index in range(1, 32): current[f'Widget6WidgetByteValue{index}'] = (index,)
            current['Widget6WidgetByteValue1'] = (control,)
            plan = self.plan(current)
            expected = bytearray.fromhex(literal); expected[6] = 42
            self.assertEqual(plan.record, bytes(expected))
            for index in (4, 5, *range(12, 32)):
                self.assertNotIn(f'Widget6WidgetByteValue{index}', plan.changes)
        current = after(self.plan()); current['Widget6WidgetByteValue8'] = (0,)
        with self.assertRaisesRegex(EdltError, 'existing Shutter preset'): self.plan(current)
        repaired = self.plan(current, mode='two-key-presets', preset_left=6)
        self.assertEqual(repaired.record[8:10], bytes((6, 170)))
        self.assertEqual(self.plan(after(repaired)).record[8:10], repaired.record[8:10])

    def test_restore_first_numeric_group_match_across_applications(self):
        current = after(self.plan())
        other = EdltLighting(self.spec).plan(current, page=1, position=2, group=43, mode='off-on', restore_level=137)
        current = after(other)
        current['Widget8WidgetType'] = (14,); current['Widget8WidgetByteValue6'] = (43,)
        current['Widget8RestoreLevel'] = (99,)
        plan = self.plan(current, group=43, application='secondary')
        self.assertEqual((plan.restore_level, plan.restore_source_widget), (137, 7))
        for name in current:
            if name.startswith(('Widget7', 'Widget8')): self.assertNotIn(name, plan.changes)
        same = after(plan); same['Widget6RestoreLevel'] = (88,)
        self.assertEqual(self.plan(same, group=43, application='primary').restore_level, 88)
        absent = self.plan(same, group=44)
        self.assertEqual((absent.restore_level, absent.restore_source_widget), (0, None))

    def test_shared_references_default_reuse_dedup_and_full_table(self):
        current = self.session.values(); current['Widget1WidgetType'] = (7,)
        current['Widget1WidgetByteValue11'] = (63,)
        current['StaticTextString1'] = tuple(b'Blind'.ljust(64, b'\0'))
        plan = self.plan(current, label_text='Same', status_text='Same')
        self.assertEqual(plan.default_label_allocation.index, 1)
        self.assertTrue(plan.default_label_allocation.reused)
        self.assertEqual((plan.static_allocation.index, plan.status_allocation.index), (62, 62))
        self.assertTrue(plan.status_allocation.reused)
        self.assertNotIn('StaticTextString63', plan.changes)
        current = after(self.plan()); index = 0
        for widget in range(7, 22):
            current[f'Widget{widget}WidgetType'] = (16,)
            current[f'Widget{widget}WidgetByteValue1'] = (0x35,)
            for offset in range(9, 14):
                current[f'Widget{widget}WidgetByteValue{offset}'] = (min(index, 63),); index += 1
        with self.assertRaises(EdltError): self.plan(current, label_text='Full table new text')
        current['Widget6WidgetType'] = (0,)
        current['StaticTextString63'] = tuple(b'Not the default'.ljust(64, b'\0'))
        # Even blank final display must account for the original default allocation.
        with self.assertRaises(EdltError): self.plan(current, label_type='blank')

    def test_dynamic_changes_need_metadata_or_explicit_display_type(self):
        current = after(self.plan(label_type='dynamic-text', label_index=1,
                                  status_type='dynamic-icon', status_index=2))
        for options in ({'group': 43}, {'application': 'secondary'}, {'label_index': 2}, {'status_index': 1},
                        {'label_index': 1}, {'status_index': 2}, {'label_index': 1, 'status_index': 2},
                        {'group': 43, 'label_type': 'dynamic-icon'}):
            with self.subTest(options=options), self.assertRaisesRegex(EdltError, 'explicit'):
                self.plan(current, **options)
        self.assertEqual(self.plan(current).record[10:12], bytes((1, 2)))
        declared = self.plan(current, label_type='dynamic-text', label_index=1,
                             status_type='dynamic-icon', status_index=2)
        self.assertEqual(declared.record[10:12], bytes((1, 2)))
        fixed = self.plan(current, group=43, label_type='static', label_index=1, status_type='blank')
        self.assertEqual(fixed.record[1], 0x30)

    def test_range_profile_page_layout_and_reference_guards(self):
        for options in ({'group': 255}, {'group': True}, {'group': '42'}, {'mode': []}, {'mode': 'dimmer'},
                        {'preset_left': 6}, {'mode': 'two-key-presets', 'preset_left': 5},
                        {'mode': 'two-key-presets', 'preset_right': 249}, {'mode': 'two-key-presets', 'preset_left': True},
                        {'application': 'enable'}, {'page': 2}, {'position': 6}, {'label_type': []},
                        {'status_type': 'timer'}, {'status_index': 0}, {'status_type': 'static', 'status_index': 64},
                        {'label_type': 'dynamic-icon', 'label_index': 4}, {'label_text': 'a\0b'},
                        {'status_text': 'ā' * 32}, {'label_text': ' '}, {'label_text': 'Hi', 'label_index': 1}):
            with self.subTest(options=options), self.assertRaises(EdltError): self.plan(**options)
        for index, kind in ((1, 3), (6, 14), (7, 3)):
            current = self.session.values(); current[f'Widget{index}WidgetType'] = (kind,)
            with self.assertRaises(EdltError): self.plan(current)
        current = self.session.values(); current['SecondaryApplication'] = (255,)
        with self.assertRaisesRegex(EdltError, 'assigned Lighting'): self.plan(current, application='secondary')
        for field in ('firmware', 'catalog_number'):
            with self.assertRaises(EdltError): EdltShutterWidget(self.spec, **{field: 'wrong'})
        last = self.plan(page=4, position=4, page_mode='multiple')
        self.assertEqual(last.widget, 21)
        self.assertEqual(self.plan(position=5).widget, 10)
        final = after(last)
        for widget in range(6, 21): self.assertEqual(final[f'Widget{widget}WidgetType'], (0,))
        for name in final:
            if name.startswith('Scene') and name != 'ScenesCheckSum': self.assertEqual(final[name], last.expected[name])
        self.assertFalse(self.session.calls)

    def test_apply_stale_identity_canonical_and_verified_unsaved_state(self):
        plan = self.plan(label_text='Shade')
        for forged in (None, replace(plan, widget=True), replace(plan, record=b'bad'),
                       replace(plan, application=203), replace(plan, default_label_allocation=None),
                       replace(plan, restore_level=False), replace(plan, restore_source_widget=True),
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

    def test_failed_staging_rolls_back_and_disconnect_does_no_recovery_io(self):
        plan = self.plan(label_text='Shade', status_text='Ready')
        original = self.editor.snapshot(self.session.values())
        self.session.failure = 'Widget6WidgetByteValue8'
        with self.assertRaises(EdltApplyError) as caught: self.editor.apply(self.session, plan)
        self.assertEqual(self.editor.snapshot(self.session.values()), original)
        self.assertTrue(caught.exception.details['rollback_verified'])
        self.assertFalse(caught.exception.details['saved'])
        self.session.calls.clear(); initial = self.session.set
        def fail(name, value):
            initial(name, value); self.session.connected = False
            raise TimeoutError('Injected disconnect')
        self.session.set = fail
        with self.assertRaises(EdltApplyError) as caught: self.editor.apply(self.session, plan)
        self.assertEqual(len(self.session.calls), 1)
        self.assertIn('Connection lost', caught.exception.rollback_errors[0])


@unittest.skipUnless(all(os.environ.get(key) for key in ('CBUS_CGATE_TEST_HOST', 'CBUS_UNITSPEC_DIR', 'CBUS_TOOLKIT_EXE')),
                     'Set C-Gate host, specifications and Toolkit EXE for native Shutter widget acceptance')
class NativeShutterWidgetTests(unittest.TestCase):
    def test_original_dll_both_modes_native_raw_crc_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.programming import Programmer
        from research.original_oracle import OriginalModelOracle, selected_backend
        root = Path(__file__).resolve().parents[1]
        app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        specs = Path(os.environ['CBUS_UNITSPEC_DIR']).resolve()
        spec = UnitSpecStore(specs).load('KEYGL5.xml'); editor = EdltShutterWidget(spec)
        project = 'ESH' + uuid4().hex[:5].upper()
        network, unit = f'//{project}/254', f'//{project}/254/p/20'
        report = {'project': project, 'scope': '5055EDL5.5 Shutter two-key/presets database PP; no physical device', 'passed': False}
        backend = selected_backend(); report['original_backend'] = backend
        with tempfile.TemporaryDirectory() as folder:
            for name in ('NativeEdltShutterProbe.cs', 'NativeEdltProbe.cs'):
                Path(folder, name).write_bytes((root / 'research' / name).read_bytes())
            def mono(command):
                result = subprocess.run(['docker', 'run', '--rm', '-v', str(app) + ':/input:ro', '-v', folder + ':/work', '-w', '/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5', 'sh', '-c', command],
                    capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            oracle = OriginalModelOracle(root / 'research/NativeEdltShutterProbe.cs', app, backend='windows') if backend == 'windows' else None
            crc_oracle = OriginalModelOracle(root / 'research/NativeEdltProbe.cs', app, backend='windows') if backend == 'windows' else None
            if oracle is not None:
                self.addCleanup(oracle.close); self.addCleanup(crc_oracle.close)
                native = oracle.run()
            else:
                native = mono('mcs -r:/input/CBusLogicModel.dll -r:System.Windows.Forms -r:System.Drawing NativeEdltShutterProbe.cs && MONO_PATH=/input mono NativeEdltShutterProbe.exe')
            for expected in (DEFAULT, BOUND_DEFAULT, PRESETS, STATIC, TWO_KEY, ICONS, TEXT, SAME_INDEX_REFRESH, OPAQUE, OPAQUE_BLANK):
                self.assertIn(':' + expected + ':0', native)
            for expected in (REUSED_DEFAULT, REUSED_PRESETS, REUSED_STATIC, REUSED_TWO_KEY):
                self.assertIn(':' + expected + ':0', native)
            for expected in (REFRESHED, LEVEL, PERCENT, BAR): self.assertIn(':' + expected + ':137', native)
            self.assertIn('static-text:Shade:62:Ready:63', native.splitlines())
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')), timeout=30) as client:
                client.command('PROJECT NEW ' + project)
                try:
                    for text in ('PROJECT USE ' + project, f'DBSET //{project}/Project/Description cbus-toolkit-isolated-edlt-shutter-v1',
                                 'DBCREATENET 254 Offline Cni 127.0.0.1:1', 'PROJECT SAVE ' + project,
                                 f'DBADDSAFE {network} Unit 20 EDLT'):
                        client.command(text)
                    for key, value in (('UnitType', 'KEYGL5'), ('UnitName', 'EDLT'), ('FirmwareVersion', '5.5.00'), ('CatalogNumber', '5055EDL')):
                        client.command(f'DBSET {unit}/{key} {value}')
                    client.command('NET LOAD DB ' + project)
                    programmer = Programmer(client)
                    with programmer.load(network, '/db' + unit) as session:
                        session.reset_defaults(); session.set('SecondaryApplication', '57')
                        original = editor.snapshot(session.values())
                        self.assertEqual(bytes(original['StaticTextString5']).rstrip(b'\0'), b'Blind')
                        first = editor.plan(original, page=1, position=1, group=42)
                        self.assertEqual(first.record.hex().upper(), REUSED_DEFAULT)
                        self.assertEqual(first.default_label_allocation.index, 5)
                        self.assertTrue(first.default_label_allocation.reused)
                        self.assertTrue(editor.apply(session, first)['verified'])
                        self.assertEqual(session.get_raw_data(0x1240, 64).lines[-1].split('RawData=')[1], b'Blind'.ljust(64, b'\0').hex())
                        records = {}
                        for options, literal in ((dict(mode='two-key-presets', preset_left=6, preset_right=248), REUSED_PRESETS),
                                (dict(mode='two-key-presets', label_text='Shade', status_text='Ready'), REUSED_STATIC),
                                (dict(), REUSED_TWO_KEY),
                                (dict(label_type='dynamic-icon', label_index=1, status_type='dynamic-icon', status_index=3), ICONS),
                                (dict(label_type='dynamic-text', label_index=2, status_type='dynamic-text', status_index=0), TEXT)):
                            plan = editor.plan(session.values(), page=1, position=1, group=42, application='secondary', **options)
                            self.assertEqual(plan.record.hex().upper(), literal)
                            editor.apply(session, plan)
                            self.assertEqual(session.get_raw_data(0x2c0, 32).lines[-1].split('RawData=')[1], literal.lower())
                            if literal == REUSED_STATIC:
                                for slot, text in ((63, b'Shade'), (62, b'Ready')):
                                    self.assertEqual(session.get_raw_data(0x1100 + 64 * slot, 64).lines[-1].split('RawData=')[1], text.ljust(64, b'\0').hex())
                            records[literal] = plan.mode
                        before_same_index = editor.snapshot(session.values())
                        for settings in ({'label_index': 2}, {'status_index': 0}, {'label_index': 2, 'status_index': 0}):
                            with self.subTest(settings=settings), self.assertRaisesRegex(EdltError, 'explicit'):
                                editor.configure(session, page=1, position=1, group=42, application='secondary', **settings)
                            self.assertEqual(editor.snapshot(session.values()), before_same_index)
                        declared = editor.plan(session.values(), page=1, position=1, group=42, application='secondary',
                                               label_type='dynamic-icon', label_index=2, status_type='dynamic-icon', status_index=0)
                        self.assertEqual(declared.record.hex().upper(), SAME_INDEX_REFRESH)
                        editor.apply(session, declared)
                        self.assertEqual(session.get_raw_data(0x2c0, 32).lines[-1].split('RawData=')[1], SAME_INDEX_REFRESH.lower())
                        light = EdltLighting(spec)
                        light.apply(session, light.plan(session.values(), page=1, position=2, group=43, mode='off-on', restore_level=137))
                        prior = editor.snapshot(session.values())
                        for options, literal in ((dict(label_type='dynamic-icon', status_type='dynamic-icon'), REFRESHED),
                                (dict(status_type='level'), LEVEL), (dict(status_type='percent'), PERCENT), (dict(status_type='bar'), BAR)):
                            plan = editor.plan(session.values(), page=1, position=1, group=43, application='secondary', **options)
                            self.assertEqual(plan.record.hex().upper(), literal)
                            self.assertEqual(plan.restore_level, 137)
                            editor.apply(session, plan)
                            self.assertEqual(session.get_raw_data(0x2c0, 32).lines[-1].split('RawData=')[1], literal.lower())
                        self.assertEqual(session.get_raw_data(0x1a0, 1).lines[-1].split('RawData=')[1], '89')
                        last = editor.plan(session.values(), page=4, position=4, page_mode='multiple', group=43,
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
                            editor.configure(session, page=1, position=1, group=44, application='secondary')
                        self.assertEqual(editor.snapshot(session.values()), final)
                    self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                    report.update(passed=True, dll_stdout=native, crcs=crcs, first=first.as_dict(), last=last.as_dict(), records=records,
                                  dll_sha256=hashlib.sha256((app / 'CBusLogicModel.dll').read_bytes()).hexdigest())
                finally:
                    client.command('PROJECT CLOSE ' + project)
                    client.command('PROJECT DELETE ' + project)
                    if os.environ.get('CBUS_EDLT_SHUTTER_REPORT'):
                        Path(os.environ['CBUS_EDLT_SHUTTER_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__': unittest.main()
