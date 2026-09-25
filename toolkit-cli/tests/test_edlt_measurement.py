"""Original MeasurementData vectors and native PP preservation/CRC acceptance."""
from dataclasses import replace
from decimal import localcontext
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4

from cbus_toolkit.edlt import EdltError, EdltApplyError, EdltLighting
from cbus_toolkit.edlt_measurement import EdltMeasurementWidget, measurement_composite
from cbus_toolkit.unitspec import UnitSpecStore, ParameterSpec
from test_edlt import fixture as base_fixture, Session


def fixture():
    spec = base_fixture(); parameters = dict(spec.parameters)
    parameters['UseBigIcon'] = ParameterSpec('UseBigIcon', 'bit', 'synthetic.xml',
        {'Name': 'UseBigIcon', 'Type': 'bit', 'Address': '0x118', 'BitAddress': '4',
         'BitSize': '1', 'DefaultValue': '1'})
    return replace(spec, parameters=parameters)

# Literal outputs of unchanged original MeasurementData, not the Python helper.
DEFAULT = '0C000002010000000000FFFF8740000000000000000000000000000000000000'
UI_MAXIMUM = '0CFEFE05010000000000FFFF8740000000000000000000000000000000000000'
SCALED = '0C2A03017D00FEFFE7FFFFFF8740000000000000000000000000000000000000'
PREFIX_ALLOCATION = '0C2A03017D00FEFFE7FF3FFF8740000000000000000000000000000000000000'
SUFFIX_ALLOCATION = '0C2A03017D00FEFFE7FF3F3E8740000000000000000000000000000000000000'
LABEL_ALLOCATION = '0C2A03017D00FEFFE7FF3F3E873D000000000000000000000000000000000000'
SHARED_TEXT = '0C2A03017D00FEFFE7FF3C3C873C000000000000000000000000000000000000'
EMPTY_TEXT = '0C2A03017D00FEFFE7FFFFFF87FF000000000000000000000000000000000000'
ALLOCATE_WITH64 = '0C2A03017D00FEFFE7FF3FFF8740000000000000000000000000000000000000'
EXACT_INDEXES = '0C2A03017D00FEFFE7FF32338734000000000000000000000000000000000000'
RAW_SIGNED_EXTREMES = '0C2A03010080807FFF7F32338734000000000000000000000000000000000000'
RAW_SIGNED_OPPOSITE = '0C2A0301FF7F7F80008032338734000000000000000000000000000000000000'
RAW_ZERO_GAIN_SETTER = '0C2A030101007F80008032338734000000000000000000000000000000000000'
ZERO_GAIN_BEFORE_GETTER = '0C2A030100007F80008032338734000000000000000000000000000000000000'
ZERO_GAIN_AFTER_GETTER = '0C2A030101007F80008032338734000000000000000000000000000000000000'
OPAQUE = '0C000002010000000000FFFF87400E0F101112131415161718191A1B1C1D1E1F'
NATIVE_PREFIX = '0C2A03017D00FEFFE7FF12FF8740000000000000000000000000000000000000'
NATIVE_SUFFIX = '0C2A03017D00FEFFE7FF123F8740000000000000000000000000000000000000'
NATIVE_LABEL = '0C2A03017D00FEFFE7FF123F873E000000000000000000000000000000000000'
NATIVE_SHARED = '0C2A03017D00FEFFE7FF3D3D873D000000000000000000000000000000000000'


def after(plan):
    return {**plan.expected, **plan.changes}


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture(); self.editor = EdltMeasurementWidget(self.spec); self.session = Session(self.spec)

    def plan(self, current=None, **options):
        settings = dict(page=1, position=1, device_id=0, channel=0); settings.update(options)
        return self.editor.plan(self.session.values() if current is None else current, **settings)

    def scaled(self, current=None, **options):
        return self.plan(current, device_id=42, channel=3, decimal_places=1, gain_mantissa=125, gain_exponent=-2,
                         offset_mantissa=-25, offset_exponent=-1, **options)

    def test_original_defaults_scalar_fields_and_exact_decimal_reporting(self):
        plan = self.plan(); self.assertEqual(plan.record.hex().upper(), DEFAULT)
        self.assertEqual(plan.as_dict()['text_indices'], dict(prefix=255, suffix=255, label=64))
        self.assertFalse(any(key.startswith('StaticTextString') for key in plan.changes))
        self.assertFalse(self.plan(after(plan)).changes)
        self.assertEqual(self.plan(device_id=254, channel=254, decimal_places=5).record.hex().upper(), UI_MAXIMUM)
        plan = self.scaled(); self.assertEqual(plan.record.hex().upper(), SCALED)
        with localcontext() as context:
            context.prec = 1
            self.assertEqual((plan.as_dict()['gain_value'], plan.as_dict()['offset_value']), ('1.25', '-2.5'))
        self.assertFalse(plan.as_dict()['ui_composite_conversion'])
        # Explicit pairs encode0.29 exactly; original composite UI reports0.28.
        exact = self.plan(gain_mantissa=29, gain_exponent=-2)
        self.assertEqual(exact.record[4:7], bytes((29, 0, 254)))
        self.assertEqual(exact.as_dict()['gain_value'], '0.29')

    def test_original_composite_conversion_and_lossy_native_vectors(self):
        vectors = {
            '0': (1, 0, '1'), '-1': (-1, 0, '-1'), '0.125': (125, -3, '0.125'),
            '32767': (32767, 0, '32767'), '-32768': (-32768, 0, '-32768'),
            '32768': (3276, 1, '32760'), '-32769': (-3276, 1, '-32760'),
            '123456': (12345, 1, '123450'), '0.00001': (1, -5, '0.00001'),
            '1000000': (1, 6, '1000000'), '1.23456': (12346, -4, '1.2346'),
            '0.29': (28, -2, '0.28'), '1.15': (114, -2, '1.14'),
            '0.07': (7, -2, '0.07'), '0.58': (57, -2, '0.57'),
            '-0.29': (-28, -2, '-0.28'), '1.000000000000001': (1, 0, '1'),
            '1e-20': (1, -20, '0.00000000000000000001'),
            '1e-50': (1, -50, '0.00000000000000000000000000000000000000000000000001'),
            '1e-51': (1, 0, '1'),
        }
        for value, expected in vectors.items():
            with self.subTest(value=value):
                conversion = measurement_composite(value, gain=True)
                self.assertEqual((conversion['mantissa'], conversion['exponent'], conversion['stored_value']), expected)
        plan = self.plan(gain_value='0.29', offset_value='-2.5')
        self.assertEqual(plan.record[4:10], bytes((28, 0, 254, 255, 231, 255)))
        result = plan.as_dict()
        self.assertTrue(result['ui_composite_conversion'])
        self.assertEqual(result['gain_value'], '0.28')
        self.assertEqual(result['offset_value'], '-2.5')
        self.assertTrue(result['composite_conversions']['gain']['exact'])
        self.assertEqual(result['composite_conversions']['gain']['input'], '0.29')
        self.assertEqual(result['composite_conversions']['gain']['stored_value'], '0.28')
        self.assertFalse(self.plan(gain_mantissa=29, gain_exponent=-2).as_dict()['ui_composite_conversion'])
        for options in ({'gain_value': '0.29', 'gain_mantissa': 29},
                        {'gain_value': '1', 'gain_exponent': 0},
                        {'offset_value': '1', 'offset_mantissa': 1},
                        {'gain_value': 'nan'}, {'gain_value': '1_000'},
                        {'gain_value': '123456789012345678901'}, {'offset_value': object()}):
            with self.subTest(options=options), self.assertRaises(EdltError):
                self.plan(**options)

    def test_original_culture_composite_wrap_and_unrelated_field_preservation(self):
        current = after(self.plan())
        original = bytes.fromhex('0C2A03017D00FEFFE7FF123FC8400E0F101112131415161718191A1B1C1D1E1F')
        for offset, value in enumerate(original):
            name = 'Widget6WidgetType' if offset == 0 else f'Widget6WidgetByteValue{offset}'
            current[name] = (value,)
        plan = self.plan(current, device_id=42, channel=3, gain_value='1e128',
                         measurement_culture='invariant')
        self.assertEqual(plan.record[4:7], bytes((1, 0, 128)))
        self.assertEqual(plan.record[7:], original[7:])
        result = plan.as_dict()
        self.assertEqual(result['measurement_culture'], 'invariant')
        self.assertEqual(result['gain_value'], '0.' + '0' * 127 + '1')
        self.assertEqual(result['offset_value'], '-2.5')
        self.assertEqual(result['composite_conversions']['gain']['editor_exponent'], 128)
        self.assertTrue(result['composite_conversions']['gain']['exponent_wrapped'])
        self.assertEqual(result['composite_conversions']['gain']['display_value'], '0')

    def test_original_static_allocations_sharing_exact_indexes_and_clear(self):
        plan = self.scaled()
        for options, literal in ((dict(prefix_text='Temperature'), PREFIX_ALLOCATION), (dict(suffix_text='C'), SUFFIX_ALLOCATION),
                                 (dict(label_text='Room'), LABEL_ALLOCATION),
                                 (dict(prefix_text='Shared', suffix_text='Shared', label_text='Shared'), SHARED_TEXT),
                                 (dict(prefix_text='', suffix_text='', label_text=''), EMPTY_TEXT),
                                 (dict(label_index=64, prefix_text='After64'), ALLOCATE_WITH64),
                                 (dict(prefix_index=50, suffix_index=51, label_index=52), EXACT_INDEXES)):
            plan = self.plan(after(plan), device_id=42, channel=3, **options)
            self.assertEqual(plan.record.hex().upper(), literal)
        direct = self.plan(after(plan), prefix_index=0, suffix_index=63, label_index=255)
        self.assertEqual((direct.record[10], direct.record[11], direct.record[13]), (0, 63, 255))
        self.assertFalse(any(key.startswith('StaticTextString') for key in direct.changes))
        self.assertEqual(self.plan(label_text=' \t').record[13], 255)

    def test_original_signed_boundaries_and_zero_gain_normalization(self):
        current = after(self.scaled(prefix_index=50, suffix_index=51, label_index=52))
        plan = self.plan(current, device_id=42, channel=3, gain_mantissa=-32768, gain_exponent=-128,
                         offset_mantissa=32767, offset_exponent=127)
        self.assertEqual(plan.record.hex().upper(), RAW_SIGNED_EXTREMES)
        plan = self.plan(after(plan), device_id=42, channel=3, gain_mantissa=32767, gain_exponent=127,
                         offset_mantissa=-32768, offset_exponent=-128)
        self.assertEqual(plan.record.hex().upper(), RAW_SIGNED_OPPOSITE)
        current = after(plan); current['Widget6WidgetByteValue4'] = (0,); current['Widget6WidgetByteValue5'] = (0,)
        plan = self.plan(current, device_id=42, channel=3)
        self.assertEqual(plan.record.hex().upper(), ZERO_GAIN_AFTER_GETTER)
        self.assertTrue(plan.gain_normalized); self.assertEqual(plan.gain_exponent, 127)
        with self.assertRaises(EdltError): self.plan(gain_mantissa=0)
        fixed = self.plan(current, gain_mantissa=5); self.assertFalse(fixed.gain_normalized)

    def test_measurement64_is_counted_and_removable_at_original_capacity(self):
        for count in (61, 62):
            current = after(self.plan()); reference = 0
            for widget in range(7, 22):
                current[f'Widget{widget}WidgetType'] = (16,); current[f'Widget{widget}WidgetByteValue1'] = (0x35,)
                for offset in range(9, 14):
                    current[f'Widget{widget}WidgetByteValue{offset}'] = (min(reference, count-1),); reference += 1
            used = self.editor.common.static_references(current)
            self.assertEqual(len(used), count+2); self.assertEqual(used[64], ('Widget6WidgetByteValue13',))
            if count == 61:
                allocated = self.plan(current, prefix_text='NewAtCapacity')
                self.assertEqual(allocated.record[10], 63); current = after(allocated)
            else:
                with self.assertRaisesRegex(EdltError, 'full'): self.plan(current, prefix_text='NewAtCapacity')
            detached = self.plan(current, label_text='')
            self.assertNotIn(64, self.editor.common.static_references(after(detached)))
            allocated = self.plan(after(detached), suffix_text='AfterDetach')
            self.assertEqual(allocated.record[11], 62 if count == 61 else 63)

    def test_shared64_allowance_is_only_measurement_label_field(self):
        current = after(self.plan())
        for kind, offsets in ((2, (13, 14)), (3, (10, 11)), (4, (9, 10, 11, 12, 13)),
                              (5, (17, 18)), (7, (11, 12)), (8, (9, 10)), (9, (7,)),
                              (12, (10, 11)), (13, (6,)), (14, (11, 12)), (15, (8, 9)),
                              (16, (9, 10, 11, 12, 13))):
            for offset in offsets:
                invalid = dict(current); invalid['Widget6WidgetType'] = (kind,)
                for index in range(1, 32): invalid[f'Widget6WidgetByteValue{index}'] = (0,)
                invalid['Widget6WidgetByteValue1'] = (0x35,); invalid[f'Widget6WidgetByteValue{offset}'] = (64,)
                with self.subTest(kind=kind, offset=offset), self.assertRaises(EdltError): self.editor.common.static_references(invalid)
        invalid = dict(current); invalid['NavWidgetVariant'] = (6,); invalid['PageNameIndex1'] = (64,)
        with self.assertRaises(EdltError): self.editor.common.static_references(invalid)
        invalid = dict(current); invalid['Scene1StartAddress'] = (0,)
        bucket = list(invalid['SceneBucket']); bucket[:5] = (0, 0, 0, 0, 64); invalid['SceneBucket'] = tuple(bucket)
        with self.assertRaises(EdltError): self.editor.common.static_references(invalid)
        invalid = dict(current); invalid['Widget6WidgetByteValue13'] = (65,)
        with self.assertRaises(EdltError): self.editor.common.static_references(invalid)

    def test_defaults_reset_selected_restore_but_preserve_opaque_and_other_fields(self):
        current = self.session.values()
        for offset in range(1, 32): current[f'Widget6WidgetByteValue{offset}'] = (offset,)
        current['Widget6RestoreLevel'] = (153,)
        plan = self.plan(current); self.assertEqual(plan.record.hex().upper(), OPAQUE); self.assertEqual(plan.restore_level, 0)
        current = after(plan); current['Widget6RestoreLevel'] = (99,); current['Widget6WidgetByteValue12'] = (137,)
        plan = self.plan(current); self.assertEqual(plan.restore_level, 99); self.assertEqual(plan.record[12], 137)
        last = self.plan(page_mode='multiple', page=4, position=4)
        self.assertEqual(last.widget, 21); self.assertEqual(self.plan(position=5).widget, 10)
        for name in last.expected:
            if name.startswith('Scene') and name != 'ScenesCheckSum': self.assertNotIn(name, last.changes)
        self.assertNotIn('PrimaryApplication', last.changes); self.assertNotIn('SecondaryApplication', last.changes)
        current = after(self.plan()); current['Widget6WidgetByteValue3'] = (6,)
        with self.assertRaises(EdltError): self.plan(current)
        self.assertEqual(self.plan(current, decimal_places=5).decimal_places, 5)

    def test_ranges_types_profiles_and_text_guards_before_any_io(self):
        for settings in ({'device_id': 255}, {'device_id': True}, {'channel': -1}, {'channel': 255}, {'decimal_places': 6},
                         {'decimal_places': True}, {'gain_mantissa': -32769}, {'gain_mantissa': 32768}, {'gain_mantissa': '1.25'},
                         {'gain_exponent': -129}, {'gain_exponent': 128}, {'offset_mantissa': 32768}, {'offset_exponent': True},
                         {'page': -1}, {'position': 6}, {'page_mode': 'other'}, {'label_text': [], 'label_index': 1},
                         {'prefix_index': 64}, {'suffix_index': 254}, {'label_index': 65}, {'label_index': True},
                         {'label_text': 'a\0b'}, {'prefix_text': 'ā'*32}, {'suffix_text': '\ud800'}, {'prefix_text': 'Hi', 'prefix_index': 1}):
            with self.subTest(settings=settings), self.assertRaises(EdltError): self.plan(**settings)
        current = self.session.values(); current['Widget6WidgetType'] = (15,)
        with self.assertRaises(EdltError): self.plan(current)
        current = self.session.values(); current['Widget7WidgetType'] = (12,)
        with self.assertRaises(EdltError): self.plan(current)
        for settings in ({'catalog_number': '5055EDLB'}, {'firmware': '6.0.00'}):
            with self.assertRaises(EdltError): EdltMeasurementWidget(self.spec, **settings)
        self.assertFalse(self.session.calls)

    def test_stale_forged_identity_guards_and_unsaved_apply(self):
        plan = self.scaled(prefix_text='Temperature', suffix_text='C', label_text='Room')
        for forged in (None, replace(plan, device_id=True), replace(plan, widget=True), replace(plan, gain_mantissa=False),
                       replace(plan, gain_normalized=1), replace(plan, record=b'bad'), replace(plan, allocations={}),
                       replace(plan, changes={**plan.changes, 'SceneCount': (8,)})):
            with self.assertRaises(EdltError): self.editor.apply(self.session, forged)
        self.session.current['SceneCount'] = (8,)
        with self.assertRaisesRegex(EdltError, 'changed'): self.editor.apply(self.session, plan)
        self.session.current['SceneCount'] = (0,)
        result = self.editor.apply(self.session, plan)
        self.assertTrue(result['verified']); self.assertFalse(result['saved']); self.assertFalse(result['physical_device_verified'])
        self.session.identity['UnitType'] = 'KEY4'; self.session.values = lambda: self.fail('Identity must precede PP read')
        with self.assertRaisesRegex(EdltError, 'identity'): self.editor.configure(self.session)

    def test_rollback_and_no_recovery_io_after_disconnect(self):
        plan = self.scaled(prefix_text='Temperature', suffix_text='C'); original = self.editor.snapshot(self.session.values())
        self.session.failure = 'Widget6WidgetByteValue4'
        with self.assertRaises(EdltApplyError) as caught: self.editor.apply(self.session, plan)
        self.assertTrue(caught.exception.details['rollback_verified']); self.assertFalse(caught.exception.details['saved'])
        self.assertEqual(self.editor.snapshot(self.session.values()), original)
        self.session.calls.clear(); initial = self.session.set
        def fail(name, value):
            initial(name, value); self.session.connected = False; raise TimeoutError('Injected disconnect')
        self.session.set = fail
        with self.assertRaises(EdltApplyError) as caught: self.editor.apply(self.session, plan)
        self.assertEqual(len(self.session.calls), 1); self.assertIn('Connection lost', caught.exception.rollback_errors[0])


@unittest.skipUnless(all(os.environ.get(key) for key in ('CBUS_CGATE_TEST_HOST', 'CBUS_UNITSPEC_DIR', 'CBUS_TOOLKIT_EXE')),
                     'Set C-Gate host, specifications and Toolkit EXE for native Measurement acceptance')
class NativeMeasurementTests(unittest.TestCase):
    def test_original_dll_native_raw_crc_and_save_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.programming import Programmer
        from cbus_toolkit.edlt_room_courtesy import EdltRoomCourtesyWidget
        root = Path(__file__).resolve().parents[1]; app = Path(os.environ['CBUS_TOOLKIT_EXE']).resolve().parent
        specs = Path(os.environ['CBUS_UNITSPEC_DIR']).resolve(); spec = UnitSpecStore(specs).load('KEYGL5.xml')
        editor = EdltMeasurementWidget(spec); project = 'EMS' + uuid4().hex[:5].upper()
        network, unit = f'//{project}/254', f'//{project}/254/p/20'
        report = {'project': project, 'scope': '5055EDL5.5 Measurement database PP using explicit scaling pairs; no physical device', 'passed': False}
        from research.original_oracle import OriginalModelOracle, selected_backend
        backend = selected_backend(); report['original_backend'] = backend
        with tempfile.TemporaryDirectory() as folder:
            for name in ('NativeEdltMeasurementProbe.cs', 'NativeEdltProbe.cs'):
                Path(folder, name).write_bytes((root / 'research' / name).read_bytes())
            def mono(command):
                result = subprocess.run(['docker', 'run', '--rm', '-v', str(app) + ':/input:ro', '-v', folder + ':/work', '-w', '/work',
                    'mono@sha256:34d816779b1248b5cfd095770b64ecbaf1798e2aca693a91c11a018dce9c7ad5', 'sh', '-c', command],
                    capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr); return result.stdout
            oracle = OriginalModelOracle(root / 'research/NativeEdltMeasurementProbe.cs', app, backend='windows') if backend == 'windows' else None
            crc_oracle = OriginalModelOracle(root / 'research/NativeEdltProbe.cs', app, backend='windows') if backend == 'windows' else None
            if oracle is not None:
                self.addCleanup(oracle.close); self.addCleanup(crc_oracle.close)
                native = oracle.run()
            else:
                native = mono('mcs -r:/input/CBusLogicModel.dll -r:System.Windows.Forms -r:System.Drawing NativeEdltMeasurementProbe.cs && MONO_PATH=/input mono NativeEdltMeasurementProbe.exe')
            for literal in (DEFAULT, UI_MAXIMUM, SCALED, PREFIX_ALLOCATION, SUFFIX_ALLOCATION, LABEL_ALLOCATION, SHARED_TEXT,
                            EMPTY_TEXT, ALLOCATE_WITH64, EXACT_INDEXES, RAW_SIGNED_EXTREMES, RAW_SIGNED_OPPOSITE,
                            RAW_ZERO_GAIN_SETTER, ZERO_GAIN_BEFORE_GETTER, ZERO_GAIN_AFTER_GETTER, OPAQUE,
                            NATIVE_PREFIX, NATIVE_SUFFIX, NATIVE_LABEL, NATIVE_SHARED):
                self.assertIn(':' + literal + ':0', native)
            for literal in ('default-used:64,255', 'empty-used:255', 'capacity-before:61:63', 'capacity-before:62:64',
                            'capacity-error:62:Static Text Table is full', 'capacity-detached-allocation:62:63',
                            'number-readback:0:1:0', 'extra-readback:0.29:0.28', 'extra-readback:1.15:1.14'):
                self.assertIn(literal, native.splitlines())
            with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')), timeout=30) as client:
                client.command('PROJECT NEW ' + project)
                try:
                    for command in ('PROJECT USE ' + project, f'DBSET //{project}/Project/Description cbus-toolkit-isolated-edlt-measurement-v1',
                                    'DBCREATENET 254 Offline Cni 127.0.0.1:1', 'PROJECT SAVE ' + project, f'DBADDSAFE {network} Unit 20 EDLT'):
                        client.command(command)
                    for key, value in (('UnitType', 'KEYGL5'), ('UnitName', 'EDLT'), ('FirmwareVersion', '5.5.00'), ('CatalogNumber', '5055EDL')):
                        client.command(f'DBSET {unit}/{key} {value}')
                    client.command('NET LOAD DB ' + project); programmer = Programmer(client)
                    with programmer.load(network, '/db' + unit) as session:
                        session.reset_defaults(); session.set('Widget6RestoreLevel', '153'); original = editor.snapshot(session.values())
                        self.assertEqual(bytes(original['StaticTextString18']).rstrip(b'\0'), b'Temperature')
                        first = editor.plan(original, page=1, position=1, device_id=0, channel=0)
                        self.assertEqual(first.record.hex().upper(), DEFAULT); self.assertEqual(first.restore_level, 0); editor.apply(session, first)
                        # Existing shared allocators accept this known64 reference without
                        # reinterpreting it as a real table slot or modifying the source.
                        before = editor.snapshot(session.values())
                        neighbour = EdltRoomCourtesyWidget(spec).plan(before, page=1, position=2, group=42, label_text='Neighbor')
                        self.assertEqual(neighbour.static_allocation.index, 63)
                        self.assertIn(64, neighbour.static_allocation.used_indices)
                        self.assertEqual(editor.snapshot(session.values()), before)
                        sequence = ((dict(device_id=254, channel=254, decimal_places=5), UI_MAXIMUM),
                                    (dict(decimal_places=1, gain_mantissa=125, gain_exponent=-2, offset_mantissa=-25, offset_exponent=-1), SCALED),
                                    (dict(prefix_text='Temperature'), NATIVE_PREFIX), (dict(suffix_text='C'), NATIVE_SUFFIX),
                                    (dict(label_text='Room'), NATIVE_LABEL),
                                    (dict(prefix_text='Shared', suffix_text='Shared', label_text='Shared'), NATIVE_SHARED),
                                    (dict(prefix_text='', suffix_text='', label_text=''), EMPTY_TEXT),
                                    (dict(prefix_text='After64', label_index=64), ALLOCATE_WITH64),
                                    (dict(prefix_index=50, suffix_index=51, label_index=52), EXACT_INDEXES),
                                    (dict(gain_mantissa=-32768, gain_exponent=-128, offset_mantissa=32767, offset_exponent=127), RAW_SIGNED_EXTREMES),
                                    (dict(gain_mantissa=32767, gain_exponent=127, offset_mantissa=-32768, offset_exponent=-128), RAW_SIGNED_OPPOSITE),
                                    (dict(), ZERO_GAIN_AFTER_GETTER))
                        records = []
                        for options, literal in sequence:
                            if literal == ZERO_GAIN_AFTER_GETTER:
                                session.set('Widget6WidgetByteValue4', '0'); session.set('Widget6WidgetByteValue5', '0')
                            settings = dict(page=1, position=1, device_id=42, channel=3); settings.update(options)
                            plan = editor.plan(session.values(), **settings)
                            self.assertEqual(plan.record.hex().upper(), literal); editor.apply(session, plan)
                            self.assertEqual(session.get_raw_data(0x2c0, 32).lines[-1].split('RawData=')[1], literal.lower())
                            if literal == ZERO_GAIN_AFTER_GETTER: self.assertTrue(plan.gain_normalized)
                            records.append(literal)
                        before = editor.snapshot(session.values())
                        with self.assertRaises(EdltError): editor.configure(session, page=1, position=1, device_id=42, channel=3, prefix_index=64)
                        self.assertEqual(editor.snapshot(session.values()), before)
                        plan = editor.plan(before, page=1, position=1, device_id=42, channel=3, gain_mantissa=29, gain_exponent=-2,
                                           offset_mantissa=0, offset_exponent=0, prefix_text='Māori', suffix_text='Māori', label_index=64)
                        self.assertEqual(plan.as_dict()['gain_value'], '0.29'); editor.apply(session, plan)
                        self.assertEqual(plan.record[10], plan.record[11]); self.assertEqual(plan.record[13], 64)
                        self.assertEqual(session.get_raw_data(0x1100+64*plan.record[10], 64).lines[-1].split('RawData=')[1],
                                         'Māori'.encode().ljust(64, b'\0').hex())
                        last = editor.plan(session.values(), page_mode='multiple', page=4, position=4, device_id=42, channel=3)
                        self.assertEqual(last.record[13], 64); editor.apply(session, last)
                        self.assertEqual(session.get_raw_data(0x4a0, 32).lines[-1].split('RawData=')[1], last.record.hex())
                        final = editor.snapshot(session.values())
                        for key in final:
                            if key.startswith('Scene') and key != 'ScenesCheckSum': self.assertEqual(final[key], original[key])
                            if key in ('PrimaryApplication', 'SecondaryApplication'): self.assertEqual(final[key], original[key])
                        Path(folder, 'KEYGL5.xml').write_bytes((specs / 'KEYGL5.xml').read_bytes())
                        Path(folder, 'values.tsv').write_text(''.join(key + '\t' + (value if isinstance(value, str) else ' '.join(hex(n) for n in value)) + '\n' for key, value in final.items()))
                        if crc_oracle is not None:
                            output = crc_oracle.run(('KEYGL5.xml', 'values.tsv'), files={name: Path(folder,name).read_bytes() for name in ('KEYGL5.xml','values.tsv')})
                        else:
                            output = mono('mcs -r:/input/CBusLogicModel.dll -r:System.Windows.Forms -r:System.Xml.Linq NativeEdltProbe.cs && MONO_PATH=/input mono NativeEdltProbe.exe KEYGL5.xml values.tsv')
                        crcs = {parts[1]: tuple(int(n, 16) for n in parts[2].split()) for line in output.splitlines()
                                if (parts := line.split(':'))[0] == 'pp-crc'}
                        self.assertEqual(crcs, editor.crcs(final)); session.save_to_source()
                    for command in ('PROJECT SAVE ', 'PROJECT CLOSE ', 'PROJECT LOAD ', 'NET LOAD DB '): client.command(command + project)
                    with programmer.load(network, '/db' + unit) as session:
                        self.assertEqual(editor.snapshot(session.values()), final)
                        self.assertEqual(session.get_raw_data(0x2cd, 1).lines[-1].split('RawData=')[1], '40')
                    self.assertTrue(any('state=new' in line for line in client.command('GET ' + network + ' state').lines))
                    report.update(passed=True, dll_stdout=native, crcs=crcs, records=records, first=first.as_dict(), last=last.as_dict(),
                                  dll_sha256=hashlib.sha256((app / 'CBusLogicModel.dll').read_bytes()).hexdigest())
                finally:
                    client.command('PROJECT CLOSE ' + project); client.command('PROJECT DELETE ' + project)
                    if os.environ.get('CBUS_EDLT_MEASUREMENT_REPORT'):
                        Path(os.environ['CBUS_EDLT_MEASUREMENT_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__': unittest.main()
