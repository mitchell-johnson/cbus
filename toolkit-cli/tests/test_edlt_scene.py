"""Scene widget literal DLL vectors, guarded references and native PP persistence."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4

from cbus_toolkit.edlt import EdltError, EdltApplyError
from cbus_toolkit.edlt_scene import EdltSceneWidget
from cbus_toolkit.unitspec import UnitSpecStore
from test_edlt import fixture, Session

# Independent output of unchanged Toolkit1.18 SceneData and SaveScenes methods.
DEFAULT = '060026250000001E1F00000000FF000000000000000000000000000000000000'
OFF_ON = '063526250000011A1B0000003FFF000000000000000000000000000000000000'
DYNAMIC = '061626250000011A1B00000302FF000000000000000000000000000000000000'
OPAQUE = '068026250405061E1F090A0B0CFF0E0F101112131415161718191A1B1C1D1E1F'
RAMP = '061626250000011C1D0F000302FF000000000000000000000000000000000000'
NUDGE = '0616262500000120210FFF0302FF000000000000000000000000000000000000'
CYCLE = '069626250000011E1F0FFF0302000100FFFFFFFFFFFF00000000000000000000'
CYCLE8 = '061626250000011E1F0FFF03020001000100010001FF00000000000000000000'
SCENES = bytes.fromhex('02012a4d0114097f02002a5801') + b'\xff' * 219


def prepared(values):
    values = dict(values)
    values.update(SceneCount=(2,), SceneBucket=tuple(SCENES), Scene1StartAddress=(0,), Scene2StartAddress=(8,))
    for index in range(3, 9): values[f'Scene{index}StartAddress'] = (255,)
    values['StaticTextString1'] = tuple(b'Evening'.ljust(64, b'\0'))
    return values


class SceneWidgetTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = EdltSceneWidget(self.spec)
        self.session = Session(self.spec)
        self.session.current = prepared(self.session.current)

    def plan(self, current=None, **options):
        settings = dict(page=1, position=1, scene=2)
        settings.update(options)
        return self.editor.plan(self.session.values() if current is None else current, **settings)

    def test_original_dll_off_on_and_dynamic_records(self):
        plan = self.plan(label_type='scene', status_text='Scene ready')
        self.assertEqual(plan.record.hex().upper(), OFF_ON)
        self.assertEqual(plan.reference.as_dict(), dict(scene=2, pointer=8, application=56, item_count=0,
                                                      trigger_group=42, action_selector=88, name_index=1))
        updated = dict(plan.expected); updated.update(plan.changes)
        dynamic = self.plan(updated, label_type='dynamic-text', label_index=3,
                            status_type='dynamic-text', status_index=2)
        self.assertEqual(dynamic.record.hex().upper(), DYNAMIC)
        again = dict(dynamic.expected); again.update(dynamic.changes)
        switched = self.plan(again, label_type='dynamic-icon', status_type='dynamic-icon')
        self.assertEqual((switched.record[11], switched.record[12]), (3, 2))
        blank = self.plan(again, label_type='blank', status_type='blank')
        self.assertEqual((blank.record[11], blank.record[12]), (3, 2))

    def test_original_dll_ramp_nudge_cycle_vectors_and_inactive_preservation(self):
        dynamic = self.plan(label_type='dynamic-text', label_index=3, status_type='dynamic-text', status_index=2)
        current = dict(dynamic.expected); current.update(dynamic.changes)
        for options, literal in ((dict(mode='ramp', ramp_seconds=1020), RAMP),
                                 (dict(mode='nudge', offset=255), NUDGE),
                                 (dict(scene=None, mode='cycle', scenes=[1, 2, 1], cycle_variant='select'), CYCLE),
                                 (dict(scene=None, mode='cycle', scenes=[1, 2] * 4, cycle_variant='cycle'), CYCLE8)):
            plan = self.plan(current, **options)
            self.assertEqual(plan.record.hex().upper(), literal)
            current.update(plan.changes)
            self.assertFalse(any(name.startswith('Scene') and name != 'ScenesCheckSum' for name in plan.changes))
        self.assertIsNone(plan.reference)
        self.assertEqual([ref.scene for ref in plan.cycle_references], [1, 2] * 4)
        back = self.plan(current, scene=1)
        self.assertEqual(back.mode, 'off-on')
        self.assertEqual(back.record[9:11], bytes((15, 255)))
        self.assertEqual(back.record[13:22], plan.record[13:22])

    def test_mode_inputs_and_all_cycle_references_are_validated(self):
        for options in ({'mode': 'unknown'}, {'mode': []}, {'mode': 'ramp', 'ramp_seconds': 5},
                        {'mode': 'off-on', 'ramp_seconds': 4}, {'offset': 1}, {'mode': 'nudge', 'offset': True},
                        {'mode': 'nudge', 'offset': 256}, {'mode': 'cycle', 'scenes': [1]},
                        {'mode': 'cycle', 'scene': None, 'scenes': []},
                        {'mode': 'cycle', 'scene': None, 'scenes': [1] * 9},
                        {'mode': 'cycle', 'scene': None, 'scenes': [1, True]},
                        {'mode': 'cycle', 'scene': None, 'scenes': [1, 3]},
                        {'mode': 'cycle', 'scene': None, 'scenes': [1], 'cycle_variant': 'bad'},
                        {'cycle_variant': 'select'}, {'scenes': [1]}):
            with self.subTest(options=options), self.assertRaises(EdltError): self.plan(**options)
        current = self.session.values(); current['Widget6WidgetByteValue9'] = (255,)
        with self.assertRaisesRegex(EdltError, 'supply ramp_seconds'): self.plan(current, mode='ramp')
        self.assertEqual(self.plan(current, mode='ramp', ramp_seconds=0).record[9], 0)
        self.assertEqual(self.plan(mode='nudge', offset=0).record[10], 0)
        current = self.session.values(); bucket = bytearray(SCENES); bucket[2] = 255; bucket[4] = 255
        current['SceneBucket'] = tuple(bucket)
        for extra in ({'label_type': 'scene'}, {'label_type': 'dynamic-icon'}, {'status_type': 'dynamic-text'}):
            with self.subTest(extra=extra), self.assertRaises(EdltError):
                self.plan(current, scene=None, mode='cycle', scenes=[2, 1], **extra)
        self.assertFalse(self.session.calls)

    def test_original_default_opaque_bytes_and_inactive_cycle_fields_are_preserved(self):
        original = self.session.values()
        for index in range(1, 32): original[f'Widget6WidgetByteValue{index}'] = (index,)
        original['Widget6WidgetByteValue1'] = (255,)
        plan = self.plan(original, scene=1)
        expected = bytearray.fromhex(OPAQUE)
        expected[6:9] = bytes((0, 26, 27))
        self.assertEqual(plan.record, bytes(expected))
        self.assertEqual(plan.changes.get('Widget6RestoreLevel', (0,)), (0,))
        preserved = set(f'Widget6WidgetByteValue{i}' for i in (4, 5, 9, 10, 11, 12, *range(14, 32)))
        self.assertFalse(set(plan.changes) & preserved)

    def test_shared_status_allocator_preserves_scene_name_and_other_references(self):
        current = self.session.values()
        current['Widget1WidgetType'] = (7,)
        current['Widget1WidgetByteValue11'] = (63,)
        result = self.plan(current, status_text='New static status')
        self.assertEqual(result.status_allocation.index, 62)
        self.assertNotIn('SceneBucket', result.changes)
        self.assertNotIn('StaticTextString1', result.changes)
        reuse = self.plan(current, status_text='Evening')
        self.assertEqual(reuse.status_allocation.index, 1)
        self.assertTrue(reuse.status_allocation.reused)
        self.assertFalse(any(name.startswith('StaticTextString') for name in reuse.changes))
        self.assertIn(255, self.editor.common.static_references(current))

    def test_layout_pages_terminators_and_unrelated_preservation(self):
        plan = self.plan(page=4, position=4, page_mode='multiple')
        self.assertEqual(plan.widget, 21)
        final = dict(plan.expected); final.update(plan.changes)
        for widget in range(6, 21): self.assertEqual(final[f'Widget{widget}WidgetType'], (0,))
        for name in plan.expected:
            if name.startswith('Scene') and name != 'ScenesCheckSum' or name.startswith('StaticTextString'):
                self.assertEqual(final[name], plan.expected[name])
        self.assertEqual(self.plan(position=5).widget, 10)
        current = self.session.values(); current['Widget7WidgetType'] = (6,)
        with self.assertRaisesRegex(EdltError, 'terminator'): self.plan(current)

    def test_invalid_or_unconfigured_references_are_errors_before_mutation(self):
        for scene in (0, 9, True, '2', 3):
            with self.subTest(scene=scene), self.assertRaises(EdltError): self.plan(scene=scene)
        for pointer in (231, 232, 256, 65535):
            current = self.session.values(); current['Scene2StartAddress'] = (pointer,)
            if pointer == 231:
                bucket = bytearray(SCENES); bucket[231] = 2; current['SceneBucket'] = tuple(bucket)
            with self.subTest(pointer=pointer), self.assertRaises(EdltError): self.plan(current)
        for position, value in ((8, 4), (9, 80), (10, 255), (12, 64)):
            current = self.session.values(); bucket = bytearray(SCENES); bucket[position] = value
            current['SceneBucket'] = tuple(bucket)
            with self.subTest(position=position), self.assertRaises(EdltError): self.plan(current)
        current = self.session.values(); current['Scene2StartAddress'] = (0,)
        with self.assertRaisesRegex(EdltError, 'overlaps'): self.plan(current)
        current = self.session.values(); current['SecondaryApplication'] = (255,)
        bucket = bytearray(SCENES); bucket[8] = 3; current['SceneBucket'] = tuple(bucket)
        with self.assertRaisesRegex(EdltError, 'application'): self.plan(current)
        self.assertFalse(self.session.calls)

    def test_label_and_status_constraints(self):
        for options in ({'label_type': 'static'}, {'label_type': []}, {'status_type': {}}, {'label_type': 'scene', 'label_index': 1},
                        {'label_type': 'dynamic-text', 'label_index': 4}, {'status_type': 'percent'},
                        {'status_index': 0}, {'status_type': 'dynamic-icon', 'status_index': 4},
                        {'status_text': 'a\0b'}, {'status_text': 'ā' * 32}, {'status_text': ' '},
                        {'status_text': 'Okay', 'status_index': 2}, {'page': 2}, {'position': 6}):
            with self.subTest(options=options), self.assertRaises(EdltError): self.plan(**options)
        current = self.session.values(); bucket = bytearray(SCENES); bucket[2] = 255; bucket[4] = 255
        current['SceneBucket'] = tuple(bucket)
        for options in ({'label_type': 'dynamic-text'}, {'status_type': 'dynamic-icon'}, {'label_type': 'scene'}):
            with self.subTest(options=options), self.assertRaises(EdltError): self.plan(current, scene=1, **options)
        current = self.session.values(); current['Widget6WidgetType'] = (2,)
        with self.assertRaisesRegex(EdltError, 'another type'): self.plan(current)

    def test_apply_saved_false_and_partial_failure_rollback(self):
        plan = self.plan(status_text='Scene ready')
        original = self.editor.snapshot(self.session.values())
        self.session.failure = 'Widget6WidgetByteValue7'
        with self.assertRaises(EdltApplyError) as caught: self.editor.apply(self.session, plan)
        self.assertEqual(caught.exception.rollback_errors, ())
        self.assertEqual(self.editor.snapshot(self.session.values()), original)
        result = self.editor.apply(self.session, plan)
        self.assertTrue(result['verified']); self.assertFalse(result['saved'])
        self.assertFalse(result['physical_device_verified'])

    def test_disconnected_failure_does_no_recovery_io(self):
        plan = self.plan()
        initial = self.session.set
        def fail(name, value):
            initial(name, value); self.session.connected = False
            raise TimeoutError('Injected disconnect')
        self.session.set = fail
        with self.assertRaises(EdltApplyError) as caught: self.editor.apply(self.session, plan)
        self.assertEqual(len(self.session.calls), 1)
        self.assertIn('Connection lost', caught.exception.rollback_errors[0])
        self.assertFalse(caught.exception.details['saved'])

    def test_identity_staleness_and_forged_plan(self):
        for settings in ({'catalog_number': '5085EDL'}, {'firmware': '6.0.00'}):
            with self.assertRaises(EdltError): EdltSceneWidget(self.spec, **settings)
        plan = self.plan()
        for forged in (None, replace(plan, widget=True), replace(plan, record=b'bad'),
                       replace(plan, changes={**plan.changes, 'SceneBucket': (0,) * 232}),
                       replace(plan, position=2)):
            with self.assertRaises(EdltError): self.editor.apply(self.session, forged)
        self.session.current['SceneCount'] = (8,)
        with self.assertRaisesRegex(EdltError, 'changed'): self.editor.apply(self.session, plan)
        self.session.identity['CatalogNumber'] = '5055EDLB'
        self.session.values = lambda: self.fail('Identity guard must precede PP read')
        with self.assertRaisesRegex(EdltError, 'identity'):
            self.editor.configure(self.session, page=1, position=1, scene=2)
        self.assertFalse(self.session.calls)


@unittest.skipUnless(all(os.environ.get(key) for key in ('CBUS_CGATE_TEST_HOST', 'CBUS_UNITSPEC_DIR', 'CBUS_TOOLKIT_EXE')),
                     'Set C-Gate host, specifications and Toolkit EXE for native Scene widget acceptance')
class NativeSceneWidgetTests(unittest.TestCase):
    def test_original_dll_vectors_and_native_scene_reference_raw_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.programming import Programmer
        from research.original_oracle import OriginalModelOracle, selected_backend
        root = Path(__file__).resolve().parents[1]
        app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        specs = Path(os.environ['CBUS_UNITSPEC_DIR']).resolve()
        editor = EdltSceneWidget(UnitSpecStore(specs).load('KEYGL5.xml'))
        project = 'ESC' + uuid4().hex[:5].upper()
        network, unit = f'//{project}/254', f'//{project}/254/p/20'
        report = {'project': project, 'scope': '5055EDL5.5 Scene Off/On, Ramp, Nudge and Cycle existing-reference database PP; no physical device', 'passed': False}
        backend = selected_backend(); report['original_backend'] = backend
        with tempfile.TemporaryDirectory() as folder:
            for name in ('NativeEdltSceneProbe.cs', 'NativeEdltProbe.cs'):
                Path(folder, name).write_bytes((root / 'research' / name).read_bytes())
            def mono(command):
                result = subprocess.run(['docker', 'run', '--rm', '-v', str(app) + ':/input:ro', '-v', folder + ':/work', '-w', '/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5', 'sh', '-c', command],
                    capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            oracle = OriginalModelOracle(root / 'research/NativeEdltSceneProbe.cs', app, backend='windows') if backend == 'windows' else None
            crc_oracle = OriginalModelOracle(root / 'research/NativeEdltProbe.cs', app, backend='windows') if backend == 'windows' else None
            if oracle is not None:
                self.addCleanup(oracle.close); self.addCleanup(crc_oracle.close)
                native = oracle.run()
            else:
                native = mono('mcs -r:/input/CBusLogicModel.dll -r:System.Windows.Forms NativeEdltSceneProbe.cs && MONO_PATH=/input mono NativeEdltSceneProbe.exe')
            for expected in (DEFAULT, OFF_ON, DYNAMIC, OPAQUE, RAMP, NUDGE, CYCLE, CYCLE8): self.assertIn(':' + expected + ':0', native)
            self.assertIn('cycle-count:3', native.splitlines())
            self.assertIn('cycle-eight-count:8', native.splitlines())
            scene_values = {}
            for line in native.splitlines():
                if line.startswith('scene-pp:'):
                    _, name, value = line.split(':'); scene_values[name] = value
            self.assertEqual(bytes(int(n, 16) for n in scene_values['SceneBucket'].split()), SCENES)
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')), timeout=30) as client:
                client.command('PROJECT NEW ' + project)
                try:
                    for text in ('PROJECT USE ' + project, f'DBSET //{project}/Project/Description cbus-toolkit-isolated-edlt-scene-v1',
                                 'DBCREATENET 254 Offline Cni 127.0.0.1:1', 'PROJECT SAVE ' + project,
                                 f'DBADDSAFE {network} Unit 20 EDLT'):
                        client.command(text)
                    for key, value in (('UnitType', 'KEYGL5'), ('UnitName', 'EDLT'), ('FirmwareVersion', '5.5.00'), ('CatalogNumber', '5055EDL')):
                        client.command(f'DBSET {unit}/{key} {value}')
                    client.command('NET LOAD DB ' + project)
                    programmer = Programmer(client)
                    with programmer.load(network, '/db' + unit) as session:
                        session.reset_defaults()
                        # Preconfigured synthetic scenes serialized by original SaveScenes above.
                        # The widget editor itself has no scene-table mutation API.
                        for name, value in scene_values.items(): session.set(name, value)
                        session.set('StaticTextString1', ' '.join(map(str, b'Evening'.ljust(64, b'\0'))))
                        original = editor.snapshot(session.values())
                        plan = editor.plan(original, page=1, position=1, scene=2, label_type='scene', status_text='Scene ready')
                        self.assertEqual(plan.record.hex().upper(), OFF_ON)
                        self.assertTrue(editor.apply(session, plan)['verified'])
                        self.assertEqual(session.get_raw_data(0x2c0, 32).lines[-1].split('RawData=')[1], OFF_ON.lower())
                        second = editor.plan(session.values(), page=4, position=4, page_mode='multiple', scene=1,
                                             label_type='dynamic-icon', label_index=3, status_type='dynamic-text', status_index=2)
                        self.assertTrue(editor.apply(session, second)['verified'])
                        final = editor.snapshot(session.values())
                        self.assertEqual(session.get_raw_data(0x4a0, 32).lines[-1].split('RawData=')[1], second.record.hex())
                        self.assertEqual(session.get_raw_data(0x2112, 232).lines[-1].split('RawData=')[1], SCENES.hex())
                        for name in final:
                            if name.startswith('Scene') and name != 'ScenesCheckSum': self.assertEqual(final[name], original[name])
                            if name not in plan.changes and name not in second.changes: self.assertEqual(final[name], original[name])
                        dynamic = editor.plan(session.values(), page=1, position=1, scene=2,
                                              label_type='dynamic-text', label_index=3, status_type='dynamic-text', status_index=2)
                        self.assertTrue(editor.apply(session, dynamic)['verified'])
                        mode_records = {}
                        for options, literal in ((dict(mode='ramp', ramp_seconds=1020, scene=2), RAMP),
                                                 (dict(mode='nudge', offset=255, scene=2), NUDGE),
                                                 (dict(mode='cycle', scenes=[1, 2, 1], cycle_variant='select'), CYCLE),
                                                 (dict(mode='cycle', scenes=[1, 2] * 4, cycle_variant='cycle'), CYCLE8)):
                            mode_plan = editor.plan(session.values(), page=1, position=1, **options)
                            self.assertEqual(mode_plan.record.hex().upper(), literal)
                            self.assertTrue(editor.apply(session, mode_plan)['verified'])
                            self.assertEqual(session.get_raw_data(0x2c0, 32).lines[-1].split('RawData=')[1], literal.lower())
                            mode_records[options['mode'] + ':' + options.get('cycle_variant', '')] = literal.lower()
                        final = editor.snapshot(session.values())
                        self.assertEqual(session.get_raw_data(0x2112, 232).lines[-1].split('RawData=')[1], SCENES.hex())
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
                        with self.assertRaisesRegex(EdltError, 'not configured'):
                            editor.configure(session, page=1, position=2, scene=3)
                        self.assertEqual(editor.snapshot(session.values()), final)
                    self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                    report.update(passed=True, dll_stdout=native, crcs=crcs, first=plan.as_dict(), second=second.as_dict(), mode_records=mode_records,
                                  dll_sha256=hashlib.sha256((app / 'CBusLogicModel.dll').read_bytes()).hexdigest())
                finally:
                    client.command('PROJECT CLOSE ' + project)
                    client.command('PROJECT DELETE ' + project)
                    if os.environ.get('CBUS_EDLT_SCENE_REPORT'):
                        Path(os.environ['CBUS_EDLT_SCENE_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__': unittest.main()
