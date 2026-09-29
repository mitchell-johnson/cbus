import json
import os
from pathlib import Path
import unittest

from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from cbus_toolkit.wireless_unit_globals import (
    FIELDS, LAYOUT, UNIT_TYPES, WirelessGlobalsApplyError, WirelessGlobalsEditor, WirelessGlobalsError,
    WirelessGlobalsPlan, check_profile, house_code_bytes, house_code_text, profile_refusal, spec_filename)
from test_macros import Session
from test_wireless_gateway import NativeProject, native_backend, raw_bytes, raw_text, start_service

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / 'research/fixtures/wireless-source-review.json'
RECEIPT = ROOT / 'research/fixtures/wireless-unit-globals-native-acceptance.json'


def fixture(unit_type='WRM4D1'):
    """Synthetic spec with the admitted layout plus two unrelated parameters."""
    defaults = {'HouseCode': '255 255 255 255', 'LearnAllowed': '1', 'LearnMasterMode': '1',
                'LearnNetworkAllowed': '1', 'LearnedFlag': '0', 'KeyMaskAllowed': '0', 'KeyMaskSave': '0'}
    parameters = {}
    for name, (address, size, bits, bit, skip, kind) in LAYOUT.items():
        fields = {'Name': name, 'Type': kind, 'Address': str(address), 'ArraySize': str(size),
                  'BitAddress': str(bit), 'ArraySkip': str(skip), 'DefaultValue': defaults.get(name, '65535')}
        if kind == 'int':
            fields.update(BitSize=str(bits), MinValue='0', MaxValue=str((1 << bits) - 1))
        parameters[name] = ParameterSpec(name, kind, 'literal-wrm-fixture.xml', fields)
    for name, address, value in (('UnitAddress', 0x20, '255'), ('DefaultDNCYCTimer', 0x30, '15')):
        parameters[name] = ParameterSpec(name, 'int', 'literal-wrm-fixture.xml', {
            'Name': name, 'Type': 'int', 'Address': str(address), 'DefaultValue': value})
    return UnitSpec(spec_filename(unit_type), {'Type': unit_type}, ('literal-wrm-fixture.xml',), parameters)


def session(unit_type='WRM4D1', **values):
    result = Session(fixture(unit_type))
    result.firmware, result.catalog_number = '2.4.00', None
    result.current.update(values)
    return result


class SourceReviewTest(unittest.TestCase):
    def test_receipt_pins_the_admitted_profiles(self):
        review = json.loads(REVIEW.read_text())['unit_globals']
        self.assertEqual(review['profiles']['unit_types'], list(UNIT_TYPES))
        self.assertEqual(review['profiles']['firmware'], ['2.0.0', '2.4.99'])


class ProfileAndCodecTest(unittest.TestCase):
    def test_profiles_and_refusals(self):
        for unit_type in UNIT_TYPES:
            self.assertIsNone(profile_refusal(unit_type, '2.0.0'))
        for unit_type, firmware, message in (('WRM2D1EZ', '2.4.00', 'EZ unit'), ('WRM2D1', '1.11.0', 'firmware'),
                                             ('WRM2D1', '2.5.0', 'firmware'), ('WRB2D1', '2.4.00', 'Only WRM')):
            with self.subTest(unit_type=unit_type, firmware=firmware):
                with self.assertRaisesRegex(WirelessGlobalsError, message):
                    check_profile(unit_type, firmware)
        with self.assertRaisesRegex(WirelessGlobalsError, 'Use WRM4D1_2.xml'):
            WirelessGlobalsEditor(fixture('WRM2D1'), 'WRM4D1')
        spec = fixture()
        moved = dict(spec.parameters)
        moved['LearnedFlag'] = ParameterSpec('LearnedFlag', 'bit', 'literal', dict(moved['LearnedFlag'].fields,
                                                                                    BitAddress='6'))
        with self.assertRaisesRegex(WirelessGlobalsError, 'LearnedFlag'):
            WirelessGlobalsEditor(UnitSpec(spec.filename, spec.metadata, spec.sources, moved))

    def test_house_code_display_order(self):
        self.assertEqual(house_code_text((0x78, 0x56, 0x34, 0x12)), '12345678')
        self.assertEqual(house_code_bytes('12345678'), (0x78, 0x56, 0x34, 0x12))
        self.assertEqual(house_code_bytes('abcdEF01'), (0x01, 0xEF, 0xCD, 0xAB))
        for bad in ('1234567', '123456789', '1234567g', None, 12345678):
            with self.subTest(bad=bad):
                with self.assertRaises(WirelessGlobalsError):
                    house_code_bytes(bad)


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.editor = WirelessGlobalsEditor(fixture())

    def test_learn_group_rules(self):
        values = session().values()
        self.assertEqual(dict(self.editor.plan(values, learn_mode='off').changes),
                         {'LearnAllowed': (0,), 'LearnMasterMode': (0,)})
        self.assertEqual(dict(self.editor.plan(values, learn_mode='current').changes), {'LearnMasterMode': (0,)})
        off = session(LearnAllowed='0', LearnMasterMode='0').values()
        self.assertEqual(dict(self.editor.plan(off, learn_mode='any').changes),
                         {'LearnAllowed': (1,), 'LearnMasterMode': (1,)})
        self.assertEqual(dict(self.editor.plan(values, network_learn=False).changes), {'LearnNetworkAllowed': (0,)})
        with self.assertRaisesRegex(WirelessGlobalsError, 'Reset until'):
            self.editor.plan(values, reset_learned=True)
        learned = session(LearnedFlag='1').values()
        self.assertEqual(dict(self.editor.plan(learned, reset_learned=True).changes), {'LearnedFlag': (0,)})
        with self.assertRaisesRegex(WirelessGlobalsError, 'Learn mode'):
            self.editor.plan(values, learn_mode='all')
        with self.assertRaisesRegex(WirelessGlobalsError, 'boolean'):
            self.editor.plan(values, network_learn='on')

    def test_house_code_and_key_masks_are_flagged(self):
        plan = self.editor.plan(session().values(), house_code='12345678', key_enable_masks={1: 0, 4: 0xFFFE},
                                key_mask_allowed=1, key_mask_save=255)
        self.assertEqual(dict(plan.changes), {'HouseCode': (0x78, 0x56, 0x34, 0x12), 'KeyMaskAllowed': (1,),
                                              'KeyMaskSave': (255,), 'KeyEnableMask1': (0,),
                                              'KeyEnableMask4': (0xFFFE,)})
        self.assertEqual(plan.beyond_dialog, ('HouseCode', 'KeyMaskAllowed', 'KeyMaskSave', 'KeyEnableMask1',
                                              'KeyEnableMask4'))
        for options, message in (({'key_enable_masks': {5: 1}}, 'index'), ({'key_enable_masks': {1: 0x10000}}, '0..65535'),
                                 ({'key_mask_allowed': 256}, '0..255'), ({'key_mask_save': True}, '0..255')):
            with self.subTest(options=options):
                with self.assertRaisesRegex(WirelessGlobalsError, message):
                    self.editor.plan(session().values(), **options)

    def test_show(self):
        view = self.editor.show(session(LearnAllowed='0', LearnedFlag='1', HouseCode='0x78 0x56 0x34 0x12',
                                        KeyEnableMask2='0x00ff').values())
        self.assertEqual(view['learn']['mode'], 'off')
        self.assertTrue(view['learn']['any_application'])
        self.assertFalse(view['learn']['application_choice_enabled'])
        self.assertEqual(view['learn']['label'], 'Unit Has Learned: Yes')
        self.assertEqual(view['house_code']['text'], '12345678')
        self.assertTrue(view['key_masks']['toolkit_save_rewrites'])
        self.assertFalse(self.editor.show(session().values())['key_masks']['toolkit_save_rewrites'])


class ApplyTest(unittest.TestCase):
    def test_apply_stale_identity_and_partial_failure(self):
        editor, live = WirelessGlobalsEditor(fixture()), session()
        live.current['UnitAddress'] = '9'
        plan = editor.plan(live.values(), learn_mode='current', house_code='00000001',
                           identity=('WRM4D1', '2.4.00', None))
        result = editor.apply(live, plan)
        self.assertTrue(result['verified'])
        self.assertEqual([n for n, _ in live.calls], ['HouseCode', 'LearnMasterMode'])
        self.assertEqual((live.current['UnitAddress'], live.current['DefaultDNCYCTimer']), ('9', '15'))
        with self.assertRaisesRegex(WirelessGlobalsError, 'changed since'):
            editor.apply(live, plan)
        other = session('WRM4D1')
        other.unit_type = 'WRM4D2'
        with self.assertRaisesRegex(WirelessGlobalsError, 'Native session unit type'):
            editor.configure(other, learn_mode='off')
        document = json.loads(json.dumps(editor.plan(session().values(), network_learn=False,
                                                     key_enable_masks={2: 3}).as_dict()))
        restored = WirelessGlobalsPlan.from_dict(document)
        failing = session()
        failing.failure = 'LearnNetworkAllowed'
        with self.assertRaises(WirelessGlobalsApplyError) as error:
            editor.apply(failing, restored)
        self.assertEqual(error.exception.attempted, ('LearnNetworkAllowed',))
        for bad in ({'format': 'x'}, {**document, 'unit_type': 'WRM2D1EZ'}, {**document, 'changes': []}):
            with self.assertRaises(WirelessGlobalsError):
                WirelessGlobalsPlan.from_dict(bad)


CATALOGUE = {'WRM2D1': '5852D2L1AA', 'WRM2R1': '5852R8F1AA', 'WRM4D1': '5854D2L1AA', 'WRM4D2': '5854D1L2AA',
             'WRM4R1': '5854R8F1AA', 'WRM4R2': '5854R4F2AA', 'WRM8D1': '5858D2L1AA', 'WRM8D2': '5858D1L2AA',
             'WRM8R1': '5858R8F1AA', 'WRM8R2': '5858R4F2AA'}
NATIVE_FIRMWARE = {'WRM2D1': '2.0.0', 'WRM8R2': '2.4.99'}
NATIVE_REFUSED = (('WRM2D1EZ', '2.4.00', 'E3852D2L1EC'), ('WRM2D1', '1.11.0', '5852D2L1AA'),
                  ('WRB2D1', '2.4.00', '5882D2L1AA'))


@unittest.skipUnless(native_backend() and os.environ.get('CBUS_UNITSPEC_DIR'),
                     'Select native C-Gate and unit specs for wireless unit globals acceptance')
class WirelessGlobalsNativeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start_service(cls)

    def check(self, pp, editor, before, case, label, expect_bytes=(), **options):
        plan = editor.plan(pp.values(), identity=(pp.unit_type, pp.firmware, pp.catalog_number), **options)
        self.assertTrue(editor.apply(pp, plan)['verified'])
        after = pp.values()
        unrelated = sorted(n for n in before if n not in FIELDS)
        self.assertEqual({n: after[n] for n in unrelated}, {n: before[n] for n in unrelated})
        for address, mask, value in expect_bytes:
            self.assertEqual(raw_bytes(pp, address, 1)[0] & mask, value, (label, hex(address)))
            case['raw_byte_assertions'] += 1
        case['positive'].append(label)
        case['unrelated_parameters_preserved'] = len(unrelated)

    def refuse(self, pp, editor, case, label, pattern, **options):
        before = pp.values()
        with self.assertRaisesRegex(WirelessGlobalsError, pattern):
            editor.configure(pp, **options)
        self.assertEqual(pp.values(), before)
        case['invalid'].append(label)

    def exercise(self, client, network, address, unit_type, report):
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        firmware = NATIVE_FIRMWARE.get(unit_type, '2.4.00')
        editor = WirelessGlobalsEditor(self.store.load(spec_filename(unit_type)), unit_type)
        NativeDatabase(client).create_unit(network, address, 'Wu' + str(address), unit_type, firmware,
                                           catalog_number=CATALOGUE[unit_type])
        path = f'/db{network}/p/{address}'
        case = {'unit_type': unit_type, 'firmware': firmware, 'catalog_number': CATALOGUE[unit_type],
                'positive': [], 'invalid': [], 'boundary': [], 'raw_byte_assertions': 0}
        with Programmer(client).load(network, path) as pp:
            editor._verify_session(pp)
            before = pp.values()
            self.refuse(pp, editor, case, 'reset-not-learned', 'Reset until', reset_learned=True)
            self.check(pp, editor, before, case, 'learn-off', learn_mode='off', expect_bytes=((0x2F, 0x03, 0x00),))
            self.check(pp, editor, before, case, 'learn-any', learn_mode='any', expect_bytes=((0x2F, 0x03, 0x03),))
            self.check(pp, editor, before, case, 'learn-current-network-off', learn_mode='current',
                       network_learn=False, expect_bytes=((0x2F, 0x07, 0x01),))
            pp.set('LearnedFlag', '1')
            self.check(pp, editor, before, case, 'reset-learned', reset_learned=True,
                       expect_bytes=((0x2F, 0x80, 0x00),))
            self.check(pp, editor, before, case, 'house-code', house_code='12345678',
                       expect_bytes=((0x16, 255, 0x78), (0x19, 255, 0x12)))
            self.check(pp, editor, before, case, 'key-masks', key_enable_masks={1: 0, 4: 0xFFFF, 2: 0x8001},
                       key_mask_allowed=1, key_mask_save=255,
                       expect_bytes=((0x48, 255, 0), (0x49, 255, 0), (0x4A, 255, 0x01), (0x4B, 255, 0x80),
                                     (0x44, 255, 1), (0x45, 255, 255)))
            case['boundary'] += ['house-code-hex', 'mask-0-and-FFFF', 'key-mask-save-255']
            self.refuse(pp, editor, case, 'mask-overflow', '0..65535', key_enable_masks={3: 0x10000})
            self.refuse(pp, editor, case, 'house-code-short', 'eight hexadecimal', house_code='1234567')
            after = pp.values()
            raw = raw_text(pp, 0x10, 0x50)
            view = editor.show(after)
            self.assertEqual((view['learn']['mode'], view['house_code']['text']), ('current', '12345678'))
            pp.save_to_source()
        report['types'].append(case)
        report['edits'] += len(case['positive'])
        report['raw_byte_assertions'] += case['raw_byte_assertions']
        return path, after, raw

    def test_admitted_types_learn_house_code_masks_save_reload_and_refusals(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        report = {'format': 'cbus-wireless-unit-globals-acceptance-v1', 'backend': native_backend(),
                  'scope': ('Toolkit Learn Mode group plus spec-level house code and key-mask edits on WRM 2.x '
                            'database units through native PP; no radio learn or physical unit'),
                  'types': [], 'refused': [], 'edits': 0, 'raw_byte_assertions': 0, 'passed': False,
                  'physical_hardware_verified': False}
        with CGateClient(self.host, self.port, timeout=30) as client, NativeProject(client, 'WU') as project:
            finals = {}
            for index, unit_type in enumerate(UNIT_TYPES):
                with self.subTest(unit_type=unit_type):
                    path, values, raw = self.exercise(client, project.network, 20 + index, unit_type, report)
                    finals[path] = (values, raw)
            editor = WirelessGlobalsEditor(self.store.load(spec_filename('WRM2D1')), 'WRM2D1')
            for index, (unit_type, firmware, catalog) in enumerate(NATIVE_REFUSED):
                NativeDatabase(client).create_unit(project.network, 40 + index, 'Wx' + str(index), unit_type,
                                                   firmware, catalog_number=catalog)
                with Programmer(client).load(project.network, f'/db{project.network}/p/{40 + index}') as pp:
                    before = pp.values()
                    with self.assertRaisesRegex(WirelessGlobalsError, 'Native session'):
                        editor.configure(pp, learn_mode='off')
                    self.assertEqual(pp.values(), before)
                report['refused'].append({'unit_type': unit_type, 'firmware': firmware, 'values_unchanged': True})
            client.command('PROJECT SAVE ' + project.project)
            client.command('PROJECT CLOSE ' + project.project)
            client.command('PROJECT LOAD ' + project.project)
            client.command('PROJECT USE ' + project.project)
            for case, (path, (values, raw)) in zip(report['types'], finals.items()):
                with Programmer(client).load(project.network, path) as pp:
                    self.assertEqual(pp.values(), values)
                    self.assertEqual(raw_text(pp, 0x10, 0x50), raw)
                case['save_close_reload_passed'] = True
            report['passed'] = len(report['types']) == len(UNIT_TYPES) and len(report['refused']) == 3
            self.assertTrue(report['passed'])
        if self.service is not None:
            report['service'] = {k: self.service.report.get(k) for k in ('vendor_jar_sha256', 'java_version')}
        if os.environ.get('CBUS_WIRELESS_GLOBALS_REPORT'):
            Path(os.environ['CBUS_WIRELESS_GLOBALS_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


class NativeReceiptTest(unittest.TestCase):
    def test_retained_native_receipt(self):
        receipt = json.loads(RECEIPT.read_text())
        self.assertTrue(receipt['passed'])
        self.assertFalse(receipt['physical_hardware_verified'])
        self.assertEqual([t['unit_type'] for t in receipt['types']], list(UNIT_TYPES))
        self.assertTrue(all(t['save_close_reload_passed'] for t in receipt['types']))
        self.assertEqual(len(receipt['refused']), len(NATIVE_REFUSED))


if __name__ == '__main__':
    unittest.main()
