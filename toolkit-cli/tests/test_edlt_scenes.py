"""Original SaveScenes packing/overflow vectors and native complete-table authoring."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4

from cbus_toolkit.edlt import EdltError, EdltApplyError, RAMP_SECONDS
from cbus_toolkit.edlt_scene import EdltSceneWidget
from cbus_toolkit.edlt_scenes import EdltSceneTable, SceneDefinition, SceneItem
from cbus_toolkit.unitspec import UnitSpecStore
from test_edlt import fixture, Session
from test_edlt_scene import prepared, SCENES

LIMIT63 = '62e66a688391ab94ef61e70e7e6030226b95c33127e7f7881f9446d2c9bf4e54'
LIMIT64 = '43add6166edea72dfe8d2075aad73a907c5ff1ad3afeb279c06d845d96bfff36'
EFFECTIVE64 = '8994edb0d1997390ceb455d21496c63e67b39f7a0bc117ff2dbe4b532a71e910'


def definitions():
    return (SceneDefinition('primary', 42, 77, (SceneItem(9, 127, 20),), name_index=1),
            SceneDefinition('primary', 42, 88, name_index=1))


def limit(count):
    scenes = [SceneDefinition('secondary' if i % 2 else 'primary', 42, 70 + i, name_index=1,
                              editable=i % 2 == 0) for i in range(8)]
    scenes[0] = replace(scenes[0], items=tuple(SceneItem(i, i * 4 % 256, RAMP_SECONDS[i % 16], i % 2 == 0)
                                             for i in range(count)))
    return tuple(scenes)


class SceneTableTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture(); self.editor = EdltSceneTable(self.spec); self.session = Session(self.spec)

    def test_original_dll_packing_and_all_empty_pointers(self):
        plan = self.editor.plan(self.session.values(), scenes=definitions())
        self.assertEqual(plan.bucket, SCENES)
        self.assertEqual(plan.pointers, (0, 8, 255, 255, 255, 255, 255, 255))
        current = dict(plan.expected); current.update(plan.changes)
        self.assertEqual(self.editor.read(current), definitions())
        current['SceneCount'] = (0,)
        self.assertEqual(self.editor.read(current), definitions())
        empty = self.editor.plan(current, scenes=[])
        self.assertEqual(empty.bucket, b'\xff' * 232)
        self.assertEqual(empty.pointers, (255,) * 8)

    def test_original_dll_64_item_native_capacity_and_65_item_rejection(self):
        plan = self.editor.plan(self.session.values(), scenes=limit(63))
        self.assertEqual(hashlib.sha256(plan.bucket).hexdigest(), LIMIT63)
        self.assertEqual(plan.pointers, (0, 194, 199, 204, 209, 214, 219, 224))
        full = self.editor.plan(self.session.values(), scenes=limit(64))
        self.assertEqual(hashlib.sha256(full.bucket).hexdigest(), EFFECTIVE64)
        self.assertEqual(full.bucket[-1], 1)
        with self.assertRaisesRegex(EdltError, '64 total'): self.editor.plan(self.session.values(), scenes=limit(65))
        with self.assertRaisesRegex(EdltError, '8 scenes'):
            self.editor.plan(self.session.values(), scenes=list(definitions()) * 5)
        self.assertFalse(self.session.calls)

    def test_name_allocation_order_dedup_and_existing_references(self):
        current = self.session.values(); current['Widget1WidgetType'] = (7,)
        current['Widget1WidgetByteValue11'] = (63,)
        requested = [replace(s, name_index=None, name_text='Shared scene') for s in definitions()]
        plan = self.editor.plan(current, scenes=requested)
        self.assertEqual([s.name_index for s in plan.scenes], [62, 62])
        self.assertEqual([a.reused for a in plan.name_allocations], [False, True])
        different = self.editor.plan(current, scenes=[requested[0], replace(requested[1], name_text='Other scene')])
        self.assertEqual([s.name_index for s in different.scenes], [62, 61])
        self.assertNotIn('StaticTextString63', different.changes)
        self.assertNotIn('Widget1WidgetByteValue11', different.changes)
        reserve = self.editor.plan(current, scenes=[requested[0], replace(definitions()[1], name_index=62)])
        self.assertEqual(reserve.scenes[0].name_index, 61)

    def test_referenced_scene_identity_cannot_be_removed_or_shifted(self):
        self.session.current = prepared(self.session.current)
        widget = EdltSceneWidget(self.spec).plan(self.session.values(), page=1, position=1, scene=2, label_type='scene')
        current = dict(widget.expected); current.update(widget.changes)
        for scenes in (definitions()[:1], definitions()[::-1],
                       (definitions()[0], replace(definitions()[1], action_selector=89)),
                       (definitions()[0], replace(definitions()[1], application='secondary')),
                       (definitions()[0], replace(definitions()[1], name_index=None))):
            with self.subTest(scenes=scenes), self.assertRaisesRegex(EdltError, 'Referenced scene slot 2'):
                self.editor.plan(current, scenes=scenes)
        changed_items = (definitions()[0], replace(definitions()[1], items=(SceneItem(12, 33),)))
        plan = self.editor.plan(current, scenes=changed_items)
        self.assertEqual(plan.references, {2: ('Widget6WidgetByteValue6',)})
        self.assertFalse(any(name.startswith('Widget') and name != 'WidgetsCRC' for name in plan.changes))

    def test_cycle_lists_and_inactive_tails_are_preserved(self):
        current = prepared(self.session.values())
        current.update(Widget6WidgetType=(6,), Widget6WidgetByteValue7=(30,), Widget6WidgetByteValue8=(31,),
                       Widget6WidgetByteValue13=(1,), Widget6WidgetByteValue14=(0,), Widget6WidgetByteValue15=(255,),
                       Widget6WidgetByteValue16=(77,))
        plan = self.editor.plan(current, scenes=definitions())
        self.assertEqual(set(plan.references), {1, 2})
        self.assertFalse(any(name.startswith('Widget') and name != 'WidgetsCRC' for name in plan.changes))
        with self.assertRaises(EdltError): self.editor.plan(current, scenes=definitions()[:1])
        current['Widget6WidgetByteValue14'] = (8,)
        with self.assertRaises(EdltError): self.editor.plan(current, scenes=definitions())
        current['Widget6WidgetByteValue7'] = (255,)
        with self.assertRaisesRegex(EdltError, 'unsupported Scene widget macros'):
            self.editor.plan(current, scenes=definitions())

    def test_invalid_public_fields_and_json_keys(self):
        for make in (lambda: SceneItem(True, 1), lambda: SceneItem(255, 1), lambda: SceneItem(1, -1),
                     lambda: SceneItem(1, 1, 5), lambda: SceneItem(1, 1, editable=1),
                     lambda: SceneDefinition('primary', 255, 0), lambda: SceneDefinition('other', 1, 0),
                     lambda: SceneDefinition('primary', 1, True), lambda: SceneDefinition('primary', 1, 0, editable=1),
                     lambda: SceneDefinition('primary', 1, 0, items=(SceneItem(1, 0), SceneItem(1, 1))),
                     lambda: SceneDefinition('primary', 1, 0, name_index=64),
                     lambda: SceneDefinition('primary', 1, 0, name_index=1, name_text='Name'),
                     lambda: SceneDefinition('primary', 1, 0, name_text='ā' * 32),
                     lambda: SceneDefinition('primary', 1, 0, name_text='a\0b'),
                     lambda: SceneDefinition.from_dict({'application':'primary','trigger_group':1,'action_selector':2,'unknown':3}),
                     lambda: SceneDefinition.from_dict({'application':'primary','trigger_group':1,'action_selector':2,'items':'oops'})):
            with self.subTest(make=make), self.assertRaises(EdltError): make()
        self.assertEqual(SceneDefinition.from_dict(definitions()[0].as_dict()), definitions()[0])
        for source in (None, {}, ['bad']):
            with self.assertRaises(EdltError): self.editor.plan(self.session.values(), scenes=source)

    def test_malformed_source_and_middle_holes_are_never_compacted(self):
        for changes in ({'Scene1StartAddress': (255,)}, {'Scene2StartAddress': (0,)}, {'Scene2StartAddress': (232,)}):
            current = prepared(self.session.values()); current.update(changes)
            with self.assertRaises(EdltError): self.editor.plan(current, scenes=definitions())
        current = self.session.values(); current['SecondaryApplication'] = (255,)
        with self.assertRaisesRegex(EdltError, 'assigned Lighting'):
            self.editor.plan(current, scenes=[replace(definitions()[0], application='secondary')])
        current = prepared(self.session.values()); bucket = bytearray(SCENES); bucket[2] = 255; current['SceneBucket'] = tuple(bucket)
        with self.assertRaisesRegex(EdltError, 'assigned trigger'):
            self.editor.plan(current, scenes=definitions())

    def test_apply_readback_rollback_and_stale_snapshot(self):
        original = self.editor.snapshot(self.session.values())
        plan = self.editor.plan(original, scenes=definitions())
        self.session.failure = 'SceneBucket'
        with self.assertRaises(EdltApplyError) as caught: self.editor.apply(self.session, plan)
        self.assertEqual(caught.exception.rollback_errors, ())
        self.assertEqual(self.editor.snapshot(self.session.values()), original)
        self.assertTrue(self.editor.apply(self.session, plan)['verified'])
        with self.assertRaisesRegex(EdltError, 'changed'): self.editor.apply(self.session, plan)
        self.assertFalse(plan.as_dict()['saved'])

    def test_forged_changes_identity_and_disconnected_write(self):
        plan = self.editor.plan(self.session.values(), scenes=definitions())
        for forged in (None, replace(plan, bucket=b'bad'), replace(plan, pointers=(False,) + plan.pointers[1:]), replace(plan, changes={**plan.changes, 'UnrelatedGlobal': (0,)})):
            with self.assertRaises(EdltError): self.editor.apply(self.session, forged)
        self.session.identity['UnitType'] = 'KEY4'
        with self.assertRaisesRegex(EdltError, 'identity'): self.editor.configure(self.session, scenes=definitions())
        self.assertFalse(self.session.calls)
        self.session.identity['UnitType'] = 'KEYGL5'
        original_set = self.session.set
        def fail(name, value):
            original_set(name, value); self.session.connected = False; raise TimeoutError('Connection lost')
        self.session.set = fail
        with self.assertRaises(EdltApplyError) as caught: self.editor.apply(self.session, plan)
        self.assertEqual(len(self.session.calls), 1)
        self.assertIn('without recovery I/O', caught.exception.rollback_errors[0])


@unittest.skipUnless(all(os.environ.get(key) for key in ('CBUS_CGATE_TEST_HOST', 'CBUS_UNITSPEC_DIR', 'CBUS_TOOLKIT_EXE')),
                     'Set C-Gate host, specifications and Toolkit EXE for native scene-table acceptance')
class NativeSceneTableTests(unittest.TestCase):
    def test_original_serializer_limits_and_native_author_edit_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.programming import Programmer
        from research.original_oracle import OriginalModelOracle, selected_backend
        root = Path(__file__).resolve().parents[1]
        app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        specs = Path(os.environ['CBUS_UNITSPEC_DIR']).resolve()
        spec = UnitSpecStore(specs).load('KEYGL5.xml')
        editor = EdltSceneTable(spec)
        project = 'EST' + uuid4().hex[:5].upper()
        network, unit = f'//{project}/254', f'//{project}/254/p/20'
        report = {'scope': '5055EDL5.5 explicit scene-table database PP authoring; no physical invocation/learning', 'passed': False}
        edited = (SceneDefinition('primary', 42, 77, (SceneItem(9, 255, 0, False), SceneItem(10, 1, 1020)), name_text='Evening'),
                  SceneDefinition('secondary', 55, 255, (SceneItem(1, 200, 120),), name_text='Reading room', editable=False))
        backend = selected_backend(); report['original_backend'] = backend
        with tempfile.TemporaryDirectory() as folder:
            for name in ('NativeEdltScenesProbe.cs', 'NativeEdltProbe.cs'):
                Path(folder, name).write_bytes((root / 'research' / name).read_bytes())
            Path(folder, 'KEYGL5.xml').write_bytes((specs / 'KEYGL5.xml').read_bytes())
            rows = []
            for scene in edited:
                rows.append('\t'.join(map(str, ('scene', int(scene.application == 'secondary'), int(scene.editable), scene.trigger_group,
                    scene.action_selector, 255 if scene.name_index is None else scene.name_index, scene.name_text))))
                rows.extend('\t'.join(map(str, ('item', item.group, item.level, RAMP_SECONDS.index(item.ramp_seconds), int(item.editable)))) for item in scene.items)
            Path(folder, 'scenes.tsv').write_text('\n'.join(rows) + '\n')
            def mono(command):
                result = subprocess.run(['docker', 'run', '--rm', '-v', str(app) + ':/input:ro', '-v', folder + ':/work', '-w', '/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5', 'sh', '-c', command],
                    capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            oracle = OriginalModelOracle(root / 'research/NativeEdltScenesProbe.cs', app, backend='windows') if backend == 'windows' else None
            crc_oracle = OriginalModelOracle(root / 'research/NativeEdltProbe.cs', app, backend='windows') if backend == 'windows' else None
            if oracle is not None:
                self.addCleanup(oracle.close); self.addCleanup(crc_oracle.close)
                native = oracle.run(('scenes.tsv',), files={'scenes.tsv': Path(folder, 'scenes.tsv').read_bytes()})
            else:
                native = mono('mcs -r:/input/CBusLogicModel.dll -r:System.Windows.Forms NativeEdltScenesProbe.cs && MONO_PATH=/input mono NativeEdltScenesProbe.exe scenes.tsv')
            for expected in ('limit63:length:232', 'limit64:length:233', 'limit63:sha256:' + LIMIT63,
                             'limit64:sha256:' + LIMIT64, 'limit63:percent:98', 'limit64:percent:100'):
                self.assertIn(expected, native.splitlines())
            overflow = next(line.split(':', 3)[3] for line in native.splitlines() if line.startswith('limit64:pp:SceneBucket:'))
            self.assertEqual(len(overflow.split()), 233)
            serialized = {}
            for line in native.splitlines():
                if line.startswith('input:pp:'):
                    _, _, name, value = line.split(':'); serialized[name] = tuple(int(n, 16) for n in value.split())
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')), timeout=30) as client:
                client.command('PROJECT NEW ' + project)
                try:
                    for text in ('PROJECT USE ' + project, f'DBSET //{project}/Project/Description cbus-toolkit-isolated-edlt-scene-table-v1',
                                 'DBCREATENET 254 Offline Cni 127.0.0.1:1', 'PROJECT SAVE ' + project,
                                 f'DBADDSAFE {network} Unit 20 EDLT'):
                        client.command(text)
                    for key, value in (('UnitType', 'KEYGL5'), ('UnitName', 'EDLT'), ('FirmwareVersion', '5.5.00'), ('CatalogNumber', '5055EDL')):
                        client.command(f'DBSET {unit}/{key} {value}')
                    client.command('NET LOAD DB ' + project)
                    programmer = Programmer(client)
                    with programmer.load(network, '/db' + unit) as session:
                        session.reset_defaults()
                        session.set('SecondaryApplication', '57')
                        session.set('StaticTextString1', ' '.join(map(str, b'Evening'.ljust(64, b'\0'))))
                        # Original SaveScenes emits an extra finalFF after all232 data bytes.
                        # Exact native PP SET accepts it and normalizes only surplus padding.
                        session.set('SceneBucket', overflow)
                        self.assertEqual(len(session.values()['SceneBucket'].split()), 232)
                        overflow_raw = session.get_raw_data(0x2112, 232).lines[-1].split('RawData=')[1]
                        self.assertEqual(hashlib.sha256(bytes.fromhex(overflow_raw)).hexdigest(), EFFECTIVE64)
                        capacity = editor.plan(session.values(), scenes=limit(64))
                        self.assertTrue(editor.apply(session, capacity)['verified'])
                        raw = session.get_raw_data(0x2112, 232).lines[-1].split('RawData=')[1]
                        self.assertEqual(hashlib.sha256(bytes.fromhex(raw)).hexdigest(), EFFECTIVE64)
                        initial = editor.plan(session.values(), scenes=definitions())
                        self.assertTrue(editor.apply(session, initial)['verified'])
                        widget = EdltSceneWidget(spec).plan(session.values(), page=1, position=1, scene=1, label_type='scene')
                        self.assertTrue(EdltSceneWidget(spec).apply(session, widget)['verified'])
                        before_edit = editor.snapshot(session.values())
                        plan = editor.plan(before_edit, scenes=edited)
                        self.assertEqual(plan.bucket, bytes(serialized['SceneBucket']))
                        self.assertEqual(plan.pointers, tuple(serialized[f'Scene{i}StartAddress'][0] for i in range(1, 9)))
                        self.assertEqual([s.name_index for s in plan.scenes], [1, 63])
                        self.assertTrue(editor.apply(session, plan)['verified'])
                        final = editor.snapshot(session.values())
                        self.assertEqual(session.get_raw_data(0x2112, 232).lines[-1].split('RawData=')[1], plan.bucket.hex())
                        self.assertEqual(session.get_raw_data(0x2102, 16).lines[-1].split('RawData=')[1],
                                         '00000b00ff00ff00ff00ff00ff00ff00')
                        for name in serialized:
                            if name.startswith('Scene'): self.assertEqual(final[name], serialized[name])
                        self.assertEqual(final['StaticTextString63'], tuple(bytes(serialized['StaticTextString63']).ljust(64, b'\0')))
                        self.assertEqual(session.get_raw_data(0x2c0, 32).lines[-1].split('RawData=')[1], widget.record.hex())
                        for name in before_edit:
                            if name not in plan.changes: self.assertEqual(final[name], before_edit[name])
                        Path(folder, 'values.tsv').write_text(''.join(name + '\t' + (value if isinstance(value, str) else
                            ' '.join(hex(n) for n in value)) + '\n' for name, value in final.items()))
                        if crc_oracle is not None:
                            output = crc_oracle.run(('KEYGL5.xml', 'values.tsv'),
                                files={name: Path(folder, name).read_bytes() for name in ('KEYGL5.xml', 'values.tsv')})
                        else:
                            output = mono('mcs -r:/input/CBusLogicModel.dll -r:System.Windows.Forms -r:System.Xml.Linq NativeEdltProbe.cs && MONO_PATH=/input mono NativeEdltProbe.exe KEYGL5.xml values.tsv')
                        crcs = {}
                        for line in output.splitlines():
                            if line.startswith('pp-crc:'):
                                _, name, value = line.split(':'); crcs[name] = tuple(int(n, 16) for n in value.split())
                        self.assertEqual(crcs, editor.crcs(final))
                        with self.assertRaisesRegex(EdltError, 'identity'):
                            editor.configure(session, scenes=edited[::-1])
                        self.assertEqual(editor.snapshot(session.values()), final)
                        session.save_to_source()
                    for command in ('PROJECT SAVE ', 'PROJECT CLOSE ', 'PROJECT LOAD ', 'NET LOAD DB '): client.command(command + project)
                    with programmer.load(network, '/db' + unit) as session:
                        self.assertEqual(editor.snapshot(session.values()), final)
                        self.assertEqual(editor.read(final), plan.scenes)
                    self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                    report.update(passed=True, dll_stdout=native, crcs=crcs, plan=plan.as_dict(), capacity_bucket_sha256=EFFECTIVE64,
                                  original_overflow_bucket_sha256=LIMIT64, original_overflow_length=233, native_normalized_length=232, maximum_items=64,
                                  dll_sha256=hashlib.sha256((app / 'CBusLogicModel.dll').read_bytes()).hexdigest())
                finally:
                    client.command('PROJECT CLOSE ' + project)
                    client.command('PROJECT DELETE ' + project)
                    if os.environ.get('CBUS_EDLT_SCENES_REPORT'):
                        Path(os.environ['CBUS_EDLT_SCENES_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__': unittest.main()
