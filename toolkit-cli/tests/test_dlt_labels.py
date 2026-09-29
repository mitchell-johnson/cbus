"""Classic DLT label variants: Toolkit rule, offline plans, XML input and native PP round trip."""
import hashlib
import json
import os
from pathlib import Path
import struct
import unittest

from cbus_toolkit.dlt_labels import (
    BYTE_ADDRESS, CHANGED, DYNAMIC_FLAG, FIELDS, LAYOUT, PLAN_FORMAT, ClassicDltLabels, DltLabelApplyError,
    DltLabelError, DltLabelPlan, flavour_bits, project_unit, variant)
from cbus_toolkit.dlt_profiles import PROFILES
from cbus_toolkit.memory import MemoryCodec, MemoryImage
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore
from test_macros import NATIVE, NATIVE_REASON, Session, closed_network_project, native_endpoint

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / 'research/fixtures/dlt-profile-facts.json'
RECEIPT = ROOT / 'research/fixtures/dlt-label-variants-native-acceptance.json'
# Nonzero neighbours sharing bytes 0x60..0x67 make preservation observable.
NEIGHBOURS = {'IndicatorBlockAssignment': (7, 6, 5, 4, 3, 2, 1, 0), 'IndicatorFunction': (1, 3, 0, 2, 1, 3, 0, 2),
              'SceneKeySelector': (1, 0, 1, 1, 0, 0, 1, 0)}


def fixture(filename='KEYL5.xml', spec_type='KEYL5'):
    """Synthetic spec with the classic DLT label layout plus unrelated parameters."""
    parameters = {}
    defaults = {'IndicatorBlockAssignment': [0, 1, 2, 3, 4, 5, 6, 7], 'IndicatorFunction': [2] * 8}
    for name, (address, size, bits, bit, skip, kind) in (*LAYOUT.items(), DYNAMIC_FLAG):
        fields = {'Name': name, 'Type': kind, 'Address': str(address), 'ArraySize': str(size),
                  'BitAddress': str(bit), 'ArraySkip': str(skip),
                  'DefaultValue': ' '.join(map(str, defaults.get(name, [1] if kind == 'bit' else [0] * size)))}
        if kind == 'int':
            fields.update(BitSize=str(bits), MinValue='0', MaxValue=str((1 << bits) - 1))
        parameters[name] = ParameterSpec(name, kind, 'literal-dlt-fixture.xml', fields)
    for name, address, size, value in (('GroupAddress', 0x50, 9, '255'), ('EnableSceneToggle', 0x3E, 1, '0')):
        fields = {'Name': name, 'Type': 'bit' if size == 1 else 'int', 'Address': str(address),
                  'ArraySize': str(size), 'DefaultValue': ' '.join([value] * size)}
        if name == 'EnableSceneToggle':
            fields['BitAddress'] = '0'
        parameters[name] = ParameterSpec(name, fields['Type'], 'literal-dlt-fixture.xml', fields)
    return UnitSpec(filename, {'Type': spec_type}, ('literal-dlt-fixture.xml',), parameters)


def session(unit_type='KEYBL5', firmware='2.1.00', catalog='5085DL'):
    result = Session(fixture(PROFILES[unit_type].spec_filename, 'KEYDL4' if unit_type == 'KEYDL4' else 'KEYL5'))
    result.unit_type, result.firmware, result.catalog_number = unit_type, firmware, catalog
    return result


def listed(value):
    return tuple(int(item, 0) for item in value.split())


class ToolkitRuleTests(unittest.TestCase):
    def test_load_and_save_rules_round_trip_all_four_variants(self):
        # LoadLabelFlavours: 2*min(MSB,1) + min(LSB,1) + 1; Save: (v-1) mod 2 / (v-1) div 2.
        self.assertEqual([variant(lsb, msb) for msb in (0, 1) for lsb in (0, 1)], [1, 2, 3, 4])
        for value in (1, 2, 3, 4):
            self.assertEqual(variant(*flavour_bits(value)), value)
        for value in (0, 5, -1, True, 2.0, '2'):
            with self.assertRaises(DltLabelError):
                flavour_bits(value)

    def test_label_fields_exactly_cover_the_shared_bytes(self):
        masks = [((1 << bits) - 1) << bit for _address, _size, bits, bit, _skip, _kind in LAYOUT.values()]
        self.assertEqual(sum(masks), 0xFF)
        self.assertEqual(masks[1] | masks[3], 0x48)
        self.assertEqual(CHANGED, ('LabelFlavourLSB', 'LabelFlavourMSB'))


class OfflineModelTests(unittest.TestCase):
    def setUp(self):
        self.editor = ClassicDltLabels(fixture(), 'KEYBL5')
        self.values = fixture().defaults()
        for name, values in NEIGHBOURS.items():
            self.values[name] = ' '.join(map(str, values))

    def test_show_reports_default_variants_and_raw_bytes(self):
        view = self.editor.show(self.values, ('KEYBL5', '2.1.00', '5085DL'))
        self.assertEqual([row['variant'] for row in view['slots']], [1] * 8)
        self.assertEqual(view['slots'][0]['address'], BYTE_ADDRESS)
        self.assertEqual(view['slots'][0]['raw_byte'], 7 | 1 << 4 | 1 << 7)
        self.assertEqual(view['enable_dynamic_labels_raw'], 1)
        self.assertFalse(view['label_text_in_unit'])
        self.assertFalse(view['slot_to_physical_key_verified'])

    def test_plan_boundary_slots_preserve_neighbour_bits(self):
        plan = self.editor.plan(self.values, variants={1: 4, 2: 2, 3: 3, 8: 4},
                                identity=('KEYBL5', '2.1.00', '5085DL'))
        self.assertEqual(plan.variants(), (4, 2, 3, 1, 1, 1, 1, 4))
        self.assertEqual(plan.changes['LabelFlavourLSB'], (1, 1, 0, 0, 0, 0, 0, 1))
        self.assertEqual(plan.changes['LabelFlavourMSB'], (1, 0, 1, 0, 0, 0, 0, 1))
        for row in plan.raw_preview:
            self.assertEqual(row['changed_mask'] & ~0x48, 0)
            self.assertEqual(row['before'] & ~0x48, row['after'] & ~0x48)
        self.assertEqual(plan.raw_preview[0]['after'], 7 | 0x08 | 1 << 4 | 0x40 | 0x80)
        document = plan.as_dict()
        self.assertEqual(document['format'], PLAN_FORMAT)
        self.assertEqual(document['variants_before'], [1] * 8)
        self.assertFalse(document['saved'] or document['labels_transferred'])
        self.assertEqual(DltLabelPlan.from_dict(json.loads(json.dumps(document))), plan)

    def test_codec_image_matches_the_preview(self):
        plan = self.editor.plan(self.values, variants={4: 3})
        after = dict(plan.expected); after.update(plan.changes)
        image = MemoryCodec(fixture()).encode_many(after).apply(MemoryImage.from_bytes(bytes(0x70)))
        self.assertEqual(list(image.read(BYTE_ADDRESS, 8)), [row['after'] for row in plan.raw_preview])

    def test_unchanged_selection_has_no_changes(self):
        self.assertEqual(dict(self.editor.plan(self.values, variants={5: 1}).changes), {})

    def test_invalid_selections_and_identities(self):
        for variants in ({}, {0: 1}, {9: 1}, {1: 0}, {1: 5}, {True: 1}, {'1': 2}):
            with self.subTest(variants=variants), self.assertRaises(DltLabelError):
                self.editor.plan(self.values, variants=variants)
        for identity, pattern in ((('KEYBL5', '1.4.00', '5085DL'), 'MinVersion'),
                                  (('KEYBL5', '2.5.00', '5085DL'), 'IsInternal'),
                                  (('KEYML5', '2.1.00', '5055DL'), 'differs'),
                                  (('KEYBL5', '2.1.00', '5055DL'), 'not a C-Gate catalogue number'),
                                  (('KEYGL5', '5.5.00', '5055EDL'), 'LabelFlavour')):
            with self.subTest(identity=identity), self.assertRaisesRegex(DltLabelError, pattern):
                self.editor.plan(self.values, variants={1: 2}, identity=identity)
        bad = dict(self.values); bad['LabelFlavourLSB'] = '0 0 2 0 0 0 0 0'
        with self.assertRaisesRegex(DltLabelError, 'Invalid current'):
            self.editor.plan(bad, variants={1: 2})
        missing = dict(self.values); del missing['SceneKeySelector']
        with self.assertRaisesRegex(DltLabelError, 'Missing'):
            self.editor.show(missing)

    def test_editor_refuses_edlt_wrong_spec_and_layout(self):
        with self.assertRaisesRegex(DltLabelError, 'LabelFlavour'):
            ClassicDltLabels(fixture('KEYGL5.xml', 'KEYGL5'), 'KEYGL5')
        with self.assertRaisesRegex(DltLabelError, 'KEYL4.xml'):
            ClassicDltLabels(fixture(), 'KEYDL4')
        spec = fixture()
        moved = dict(spec.parameters['LabelFlavourMSB'].fields, BitAddress='5')
        spec.parameters['LabelFlavourMSB'] = ParameterSpec('LabelFlavourMSB', 'int', 'x', moved)
        with self.assertRaisesRegex(DltLabelError, 'layout'):
            ClassicDltLabels(spec, 'KEYBL5')
        with self.assertRaisesRegex(DltLabelError, 'KEYL5'):
            ClassicDltLabels(fixture(), 'KEYL5')

    def test_apply_stale_partial_failure_and_readback(self):
        live = session()
        for name, values in NEIGHBOURS.items():
            live.current[name] = ' '.join(map(str, values))
        before = live.values()
        plan = self.editor.plan(live.values(), variants={2: 4, 7: 3})
        result = self.editor.apply(live, plan)
        self.assertTrue(result['verified'])
        self.assertFalse(result['raw_bytes_verified'])
        self.assertEqual([name for name, _value in live.calls], list(plan.changes))
        self.assertEqual({k: v for k, v in live.values().items() if k not in CHANGED},
                         {k: v for k, v in before.items() if k not in CHANGED})
        with self.assertRaisesRegex(DltLabelError, 'changed since'):
            self.editor.apply(live, plan)
        live = session()
        plan = self.editor.plan(live.values(), variants={1: 4})
        live.failure = 'LabelFlavourMSB'
        with self.assertRaises(DltLabelApplyError) as caught:
            self.editor.apply(live, plan)
        self.assertEqual(caught.exception.attempted, ('LabelFlavourLSB', 'LabelFlavourMSB'))
        self.assertFalse(caught.exception.details['saved'])
        for identity in (('KEYBL5', '1.4.00', '5085DL'), ('KEYML5', '2.1.00', '5055DL')):
            refused = session(*identity)
            with self.subTest(identity=identity), self.assertRaises(DltLabelError):
                self.editor.configure(refused, variants={1: 2})
            self.assertEqual(refused.calls, [])

    def test_decorator_profile_uses_keyl4(self):
        editor = ClassicDltLabels(fixture('KEYL4.xml', 'KEYDL4'), 'KEYDL4')
        live = session('KEYDL4', '3.0.99', 'E5054DL')
        self.assertTrue(editor.configure(live, variants={4: 2})['verified'])
        refused = session('KEYDL4', '2.0.00', 'E5084DL')
        with self.assertRaisesRegex(DltLabelError, 'IsInternal'):
            editor.configure(refused, variants={4: 2})

    def test_project_xml_unit_reader(self):
        rows = ''.join(f'<PP Name="{name}" Value="{value}"/>' for name, value in fixture().defaults().items())
        text = ('<?xml version="1.0" encoding="utf-8"?><Installation><Project><Address>P1</Address>'
                '<Network><Address>254</Address><Unit><Address>20</Address><UnitType>KEYML5</UnitType>'
                f'<FirmwareVersion>3.0.00</FirmwareVersion><CatalogNumber>5055DL</CatalogNumber>{rows}</Unit>'
                '<Unit><Address>21</Address><UnitType>KEYDL4</UnitType><FirmwareVersion>3.0.00</FirmwareVersion>'
                '</Unit></Network></Project></Installation>')
        identity, values = project_unit(text, '//P1/254/p/20')
        self.assertEqual(identity, ('KEYML5', '3.0.00', '5055DL'))
        self.assertEqual(values, fixture().defaults())
        self.assertEqual(project_unit(text, '//P1/254/p/21')[0], ('KEYDL4', '3.0.00', None))
        for path in ('//P2/254/p/20', '//P1/254/p/22'):
            with self.subTest(path=path), self.assertRaises(DltLabelError):
                project_unit(text, path)
        with self.assertRaises(ValueError):
            project_unit(text.replace('<Unit><Address>21', '<Unit><Address>20'), '//P1/254/p/20')
        with self.assertRaises(ValueError):
            project_unit('<!DOCTYPE x [<!ENTITY a "b">]>' + text[text.index('<Installation>'):], '//P1/254/p/20')


@unittest.skipUnless(os.environ.get('CBUS_UNITSPEC_DIR'), 'Set CBUS_UNITSPEC_DIR for decoded classic DLT specs')
class VendorSpecTests(unittest.TestCase):
    def test_keyl5_and_keyl4_layouts_digests_and_includes(self):
        store = UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR'])
        facts = json.loads(FACTS.read_text())['specifications']
        for filename, unit_type in (('KEYL5.xml', 'KEYBL5'), ('KEYL5.xml', 'KEYML5'), ('KEYL4.xml', 'KEYDL4')):
            with self.subTest(unit_type=unit_type):
                spec = store.load(filename)
                self.assertEqual(spec.sources, ('I_NEOCORE.xml', 'I_DLT.xml', filename))
                for name in spec.sources:
                    self.assertEqual(hashlib.sha256((store.directory / name).read_bytes()).hexdigest(),
                                     facts[name]['sha256'])
                self.assertEqual(PROFILES[unit_type].spec_sha256, facts[filename]['sha256'])
                ClassicDltLabels(spec, unit_type)
                self.assertEqual(spec.get('LabelFlavourLSB').source, 'I_DLT.xml')
                self.assertEqual(spec.get('LabelFlavourMSB').source, 'I_DLT.xml')
                self.assertEqual({spec.get(name).source for name in FIELDS if 'Flavour' not in name},
                                 {'I_NEOCORE.xml'})


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'Set CBUS_TOOLKIT_EXE for original LabelFlavour instructions')
class ToolkitBinaryTests(unittest.TestCase):
    def test_pinned_label_flavour_instruction_ranges(self):
        image = Path(os.environ['CBUS_TOOLKIT_EXE']).read_bytes()
        facts = json.loads(FACTS.read_text())['toolkit_label_flavour']
        self.assertEqual(hashlib.sha256(image).hexdigest(), facts['sha256'])
        u16 = lambda offset: struct.unpack_from('<H', image, offset)[0]
        u32 = lambda offset: struct.unpack_from('<I', image, offset)[0]
        pe = u32(60); optional = pe + 24; sections = optional + u16(pe + 20); base = u32(optional + 28)

        def read(va, length):
            rva = va - base
            for index in range(u16(pe + 6)):
                offset = sections + index * 40; start = u32(offset + 12)
                if start <= rva < start + max(u32(offset + 8), u32(offset + 16)):
                    raw = u32(offset + 20) + rva - start
                    return image[raw:raw + length]
            raise AssertionError('VA outside PE sections')
        for row in facts['ranges']:
            with self.subTest(routine=row['routine']):
                code = read(int(row['va'], 16), row['length'])
                self.assertEqual(hashlib.sha256(code).hexdigest(), row['sha256'])
        # Load composes 2*MSB + LSB + 1 before calling SetLabelFlavour.
        compose = read(0x121BF1D, 0x13)
        self.assertEqual(compose[5:13], bytes.fromhex('8b55f403d20355f8'))
        self.assertEqual(compose[13], 0x42)  # inc edx


# Types, catalogue numbers and firmware, including boundary revisions.
NATIVE_TYPES = (('KEYBL5', '2.1.00', '5085DL'), ('KEYML5', '2.0.00', '5055DL'),
                ('KEYML5', '3.0.99', '5055DL'), ('KEYDL4', '3.0.00', 'E5084DL'), ('KEYDL4', '2.1.00', 'E5054DL'))
NATIVE_REFUSED = (('KEYBL5', '1.4.00', '5085DL', 'MinVersion'), ('KEYDL4', '2.0.00', 'E5084DL', 'IsInternal'),
                  ('KEYML5', '2.5.00', '5055DL', 'IsInternal'))
SELECTIONS = ({1: 4, 2: 3, 3: 2, 8: 4}, {1: 1, 8: 2, 5: 3})


def raw_bytes(pp):
    return bytes.fromhex(pp.get_raw_data(BYTE_ADDRESS, 8).lines[-1].split('RawData=', 1)[1])


@unittest.skipUnless(NATIVE, NATIVE_REASON)
class NativeLabelVariantTests(unittest.TestCase):
    def test_native_pp_raw_bytes_preservation_xml_and_close_reload(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer, xml_text
        store = UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR'])
        report = {'format': 'cbus-dlt-label-variants-native-acceptance-v1',
                  'scope': ('Classic DLT LabelFlavourLSB/MSB through owned native C-Gate PP sessions on '
                            'synthetic database units; no physical unit, display or label transfer'),
                  'specs': {name: hashlib.sha256((store.directory / name).read_bytes()).hexdigest()
                            for name in ('KEYL5.xml', 'KEYL4.xml', 'I_DLT.xml', 'I_NEOCORE.xml')},
                  'types': [], 'refused': [], 'passed': False, 'physical_hardware_verified': False}
        with native_endpoint() as (host, port), CGateClient(host, port=port, timeout=30) as client, \
                closed_network_project(client, 'DL') as project:
            report['greeting'] = client.greeting
            network = f'//{project}/254'
            programmer, database = Programmer(client), NativeDatabase(client)
            finals = {}
            for index, (unit_type, firmware, catalog) in enumerate(NATIVE_TYPES):
                with self.subTest(unit_type=unit_type, firmware=firmware):
                    address = 20 + index
                    editor = ClassicDltLabels(store.load(PROFILES[unit_type].spec_filename), unit_type)
                    database.create_unit(network, address, f'Dlt{address}', unit_type, firmware,
                                         catalog_number=catalog)
                    path = f'{network}/p/{address}'
                    case = {'unit_type': unit_type, 'firmware': firmware, 'catalog_number': catalog,
                            'selections': [], 'raw_after_hex': [], 'raw_byte_assertions': 0}
                    with programmer.load(network, '/db' + path) as pp:
                        self.assertEqual((pp.unit_type, pp.firmware, pp.catalog_number), (unit_type, firmware, catalog))
                        for name, values in NEIGHBOURS.items():
                            pp.set(name, ' '.join(map(str, values)))
                        baseline = pp.values()
                        for selection in SELECTIONS:
                            before_raw = raw_bytes(pp)
                            result = editor.configure(pp, variants=selection)
                            self.assertTrue(result['verified'] and result['raw_bytes_verified'])
                            after_raw = raw_bytes(pp)
                            self.assertEqual(after_raw.hex(), result['raw_after_hex'])
                            for before, after in zip(before_raw, after_raw):
                                self.assertEqual(before & ~0x48, after & ~0x48)
                                case['raw_byte_assertions'] += 1
                            values = pp.values()
                            self.assertEqual({k: v for k, v in values.items() if k not in CHANGED},
                                             {k: v for k, v in baseline.items() if k not in CHANGED})
                            shown = [row['variant'] for row in editor.show(values)['slots']]
                            for slot, value in selection.items():
                                self.assertEqual(shown[slot - 1], value)
                            case['selections'].append({str(k): v for k, v in sorted(selection.items())})
                            case['raw_after_hex'].append(after_raw.hex())
                        # A stale plan and an invalid native value are refused without writes.
                        stale = editor.plan(baseline, variants={6: 4})
                        with self.assertRaisesRegex(DltLabelError, 'changed since'):
                            editor.apply(pp, stale)
                        final_values, final_raw = pp.values(), raw_bytes(pp)
                        pp.save_to_source()
                    document = xml_text(database.get(f'//{project}', xml=True))
                    identity, xml_values = project_unit(document, path)
                    self.assertEqual(identity[:2], (unit_type, firmware))
                    self.assertEqual(editor.show(xml_values)['slots'], editor.show(final_values)['slots'])
                    case['database_xml_matches'] = True
                    finals[path] = (unit_type, final_values, final_raw)
                    report['types'].append(case)
            for index, (unit_type, firmware, catalog, pattern) in enumerate(NATIVE_REFUSED):
                with self.subTest(refused=unit_type, firmware=firmware):
                    address = 40 + index
                    database.create_unit(network, address, f'Ref{address}', unit_type, firmware,
                                         catalog_number=catalog)
                    editor = ClassicDltLabels(store.load(PROFILES[unit_type].spec_filename), unit_type)
                    with programmer.load(network, f'/db{network}/p/{address}') as pp:
                        before = pp.values()
                        with self.assertRaisesRegex(DltLabelError, pattern):
                            editor.configure(pp, variants={1: 4})
                        self.assertEqual(pp.values(), before)
                    report['refused'].append({'unit_type': unit_type, 'firmware': firmware,
                                              'reason_matched': pattern, 'values_unchanged': True})
            client.command('PROJECT SAVE ' + project)
            client.command('PROJECT CLOSE ' + project)
            client.command('PROJECT LOAD ' + project)
            client.command('PROJECT USE ' + project)
            for path, (unit_type, values, raw) in finals.items():
                with self.subTest(reload=path), programmer.load(network, '/db' + path) as pp:
                    self.assertEqual(pp.values(), values)
                    self.assertEqual(raw_bytes(pp), raw)
            report['project_close_reload_passed'] = True
            report['passed'] = len(report['types']) == len(NATIVE_TYPES) and len(report['refused']) == len(NATIVE_REFUSED)
            self.assertTrue(report['passed'])
        if os.environ.get('CBUS_DLT_LABEL_REPORT'):
            Path(os.environ['CBUS_DLT_LABEL_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


class NativeReceiptTests(unittest.TestCase):
    def test_retained_native_receipt_is_sanitized_and_complete(self):
        receipt = json.loads(RECEIPT.read_text())
        self.assertEqual(receipt['format'], 'cbus-dlt-label-variants-native-acceptance-v1')
        self.assertTrue(receipt['passed'] and receipt['project_close_reload_passed'])
        self.assertFalse(receipt['physical_hardware_verified'])
        self.assertEqual([(row['unit_type'], row['firmware'], row['catalog_number']) for row in receipt['types']],
                         [tuple(row) for row in NATIVE_TYPES])
        self.assertEqual([(row['unit_type'], row['firmware']) for row in receipt['refused']],
                         [row[:2] for row in NATIVE_REFUSED])
        facts = json.loads(FACTS.read_text())['specifications']
        for name, digest in receipt['specs'].items():
            self.assertEqual(digest, facts[name]['sha256'])
        for case in receipt['types']:
            self.assertTrue(case['database_xml_matches'])
            self.assertEqual(case['raw_byte_assertions'], 8 * len(SELECTIONS))
            for selection, raw in zip(case['selections'], case['raw_after_hex']):
                data = bytes.fromhex(raw)
                for slot, value in selection.items():
                    byte = data[int(slot) - 1]
                    self.assertEqual(variant(byte >> 3 & 1, byte >> 6 & 1), value)
        text = RECEIPT.read_text()
        for forbidden in ('password', '/Users/', '/Volumes/'):
            self.assertNotIn(forbidden, text)


if __name__ == '__main__':
    unittest.main()
