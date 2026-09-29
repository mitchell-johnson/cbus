from fractions import Fraction
import importlib.util
import json
import os
from pathlib import Path
import unittest
from uuid import uuid4

from cbus_toolkit.din_output_settings import (
    FIELDS, FIRMWARE, LAYOUTS, PROFILES, DinOutputEditor, DinPlan, DinSettingsApplyError,
    DinSettingsError, check_profile, level_to_percent, logic_group_level, percent_to_level,
    profile_refusal, recovery_delay_seconds)
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore
from test_macros import Session

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / 'research/fixtures/din-output-level-original-vectors.json'
RECEIPT = ROOT / 'research/fixtures/din-output-settings-native-acceptance.json'


def fixture(unit_type):
    """Synthetic spec with the admitted layout plus two unrelated parameters."""
    profile = PROFILES[unit_type]
    rows = dict(LAYOUTS[profile.spec_filename])
    count = rows['LevelStoreEnable'][1]
    defaults = {'InterLockingChannel': [0], 'LogicLevelStoreEnable': [1] * 4, 'RestrikeDelay': [60],
                'GroupAddress': [255] * 16, 'LightLevel': [0] * 16, 'LevelStoreEnable': [1] * count,
                'PowerUpDelay': [5] * count, 'MinDimmingLevel': [0] * count,
                'MaxDimmingLevel': [255] * rows['MaxDimmingLevel'][1]}
    parameters = {}
    for name, (address, size, bits, bit, skip, kind) in rows.items():
        fields = {'Name': name, 'Type': kind, 'Address': str(address), 'ArraySize': str(size),
                  'BitAddress': str(bit), 'ArraySkip': str(skip),
                  'DefaultValue': ' '.join(map(str, defaults.get(name, [0] * size)))}
        if kind == 'int':
            fields.update(BitSize=str(bits), MinValue='0', MaxValue='1' if bits == 1 else '255')
        parameters[name] = ParameterSpec(name, kind, 'literal-din-fixture.xml', fields)
    for name, address, value in (('UnitAddress', 32, '255'), ('AreaGroupAddress', 67, '255')):
        parameters[name] = ParameterSpec(name, 'int', 'literal-din-fixture.xml', {
            'Name': name, 'Type': 'int', 'Address': str(address), 'DefaultValue': value})
    return UnitSpec(profile.spec_filename, {'Type': unit_type}, ('literal-din-fixture.xml',), parameters)


def session(unit_type):
    result = Session(fixture(unit_type))
    result.firmware, result.catalog_number = FIRMWARE, None
    return result


def listed(value):
    return [int(v, 0) for v in value.split()]


class OriginalLevelVectorTest(unittest.TestCase):
    def test_frozen_original_instruction_vectors(self):
        document = json.loads(VECTORS.read_text())
        self.assertEqual(document['executable_sha256'],
                         '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab')
        functions = {'PercentToLevel': percent_to_level, 'LevelToPercent': level_to_percent,
                     'LogicGroupRound255': logic_group_level}
        counts = {}
        for row in document['rows']:
            counts[row['routine']] = counts.get(row['routine'], 0) + 1
            self.assertEqual(functions[row['routine']](row['input']), row['output'], row)
        self.assertEqual(counts, {'PercentToLevel': 101, 'LevelToPercent': 256, 'LogicGroupRound255': 101})

    def test_roundtrip_properties_and_domain(self):
        self.assertTrue(all(level_to_percent(percent_to_level(p)) == p for p in range(101)))
        self.assertEqual(sum(percent_to_level(level_to_percent(v)) != v for v in range(256)), 155)
        # Half-way products use Delphi round-half-even, unlike PercentToLevel.
        self.assertEqual([logic_group_level(p) for p in (10, 30, 50, 70, 90)], [26, 76, 128, 178, 230])
        self.assertEqual(logic_group_level(1), round(Fraction(255, 100)))
        self.assertEqual([recovery_delay_seconds(v) for v in (5, 59, 60, 61, 255)], [5, 59, 60, 70, 2010])
        for bad in (-1, 101, True, 1.0, '5'):
            with self.assertRaises(DinSettingsError):
                percent_to_level(bad)
        with self.assertRaises(DinSettingsError):
            level_to_percent(256)

    @unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'requires exact original Toolkit executable')
    def test_original_instructions_regenerate_the_vectors(self):
        path = ROOT / 'research/din_output_levels_original.py'
        spec = importlib.util.spec_from_file_location('din_output_levels_original', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        probe = module.DinLevelOriginalProbe(os.environ['CBUS_TOOLKIT_EXE'])
        self.assertEqual(probe.vectors(), json.loads(VECTORS.read_text())['rows'])


class SourceReviewTest(unittest.TestCase):
    def test_receipt_is_sanitized_and_matches_admitted_profiles(self):
        text = (ROOT / 'research/fixtures/din-output-settings-source-review.json').read_text()
        for private in ('<Param', 'DefaultValue', 'CLIPSAL', 'Kozaderov'):
            self.assertNotIn(private, text)
        review = json.loads(text)
        self.assertEqual(review['format'], 'cbus-din-output-settings-source-review-v1')
        rows = {row['unit_type']: row for row in review['profiles']}
        self.assertEqual({t for t, row in rows.items() if row['admitted']}, set(PROFILES))
        self.assertFalse(rows['RELDN8SP']['admitted'])
        for unit_type, profile in PROFILES.items():
            row = rows[unit_type]
            self.assertEqual((row['spec'], row['channels'], tuple(row['pp_indices']), row['is_relay'], row['interlock_combo']),
                             (profile.spec_filename, profile.channels, profile.indices, profile.relay, profile.interlock))
        bindings = {row['binding'].split('[')[0].split(' ')[0] for row in review['controls']}
        self.assertEqual(bindings - {'LogicGA13Associations..LogicGA16Associations'},
                         set(FIELDS) - {'LogicGA13Associations', 'LogicGA14Associations', 'LogicGA15Associations',
                                        'LogicGA16Associations'})
        native = json.loads(RECEIPT.read_text())
        self.assertTrue(native['passed'])
        self.assertFalse(native['physical_hardware_verified'])
        self.assertEqual({row['unit_type'] for row in native['types']}, set(PROFILES))


class ProfileTest(unittest.TestCase):
    def test_admitted_types_and_refusals(self):
        for unit_type in PROFILES:
            self.assertIsNone(profile_refusal(unit_type, FIRMWARE))
            self.assertIn('2.7.00', profile_refusal(unit_type, '2.6.99'))
            self.assertIn('2.7.00', profile_refusal(unit_type, '2.7.01'))
        for unit_type, reason in (('RELDN8SP', 'nine channels'), ('RELAY4', 'LogicGA0-5'),
                                  ('DIMMER4', 'TfrmCBus1Relay'), ('KEY4', 'Only RELDN4')):
            self.assertIn(reason, profile_refusal(unit_type, FIRMWARE))
        with self.assertRaisesRegex(DinSettingsError, 'Native session'):
            check_profile('RELDN8', '2.6.00', subject='Native session')
        self.assertEqual({t: (p.channels, p.relay, p.interlock) for t, p in PROFILES.items()}, {
            'RELDN4': (4, True, True), 'RELDN8': (8, True, False), 'RELDN8B': (8, True, True),
            'RELDN12': (12, True, True), 'DIMDN4': (4, False, False), 'DIMDN4F': (4, False, False),
            'DIMDN8': (8, False, False), 'DIMDN8F': (8, False, False)})

    def test_editor_rejects_wrong_spec_or_layout(self):
        with self.assertRaisesRegex(DinSettingsError, 'Use RELDN8.xml'):
            DinOutputEditor(fixture('RELDN12'), 'RELDN8')
        spec = fixture('DIMDN8')
        fields = dict(spec.parameters['MaxDimmingLevel'].fields, Address='108')
        spec.parameters['MaxDimmingLevel'] = ParameterSpec('MaxDimmingLevel', 'int', 'x', fields)
        with self.assertRaisesRegex(DinSettingsError, 'layout: MaxDimmingLevel'):
            DinOutputEditor(spec)
        with self.assertRaisesRegex(DinSettingsError, 'nine channels'):
            DinOutputEditor(fixture('RELDN8'), 'RELDN8SP')


class PlanTest(unittest.TestCase):
    def editor(self, unit_type):
        return DinOutputEditor(fixture(unit_type), unit_type)

    def test_logic_tab_associations_function_and_dependencies(self):
        editor, current = self.editor('RELDN12'), fixture('RELDN12').defaults()
        with self.assertRaisesRegex(DinSettingsError, 'Logic group 1 is associated'):
            editor.plan(current, channel=12, logic_groups=[1])
        current['GroupAddress'] = ' '.join(['255'] * 12 + ['30', '31', '32', '33'])
        plan = editor.plan(current, channel=12, logic_groups=[1, 4], logic_function='or')
        self.assertEqual(plan.changes['LogicGA13Associations'][11], 1)
        self.assertEqual(plan.changes['LogicGA16Associations'][11], 1)
        self.assertEqual(plan.changes['LogicFunction'][11], 1)
        self.assertNotIn('LogicGA14Associations', plan.changes)
        with self.assertRaisesRegex(DinSettingsError, 'And or Or|and or or'):
            editor.plan(current, channel=1, logic_groups=[1], logic_function='max')
        with self.assertRaisesRegex(DinSettingsError, 'disables the logic function'):
            editor.plan(current, channel=1, logic_function='and')
        with self.assertRaisesRegex(DinSettingsError, '1..4'):
            editor.plan(current, channel=1, logic_groups=[5])
        dimmer_current = fixture('DIMDN4').defaults()
        dimmer_current['GroupAddress'] = ' '.join(['255'] * 13 + ['31', '255', '255'])
        dimmer = self.editor('DIMDN4').plan(dimmer_current, channel=4, logic_groups={2}, logic_function='max')
        self.assertEqual(dimmer.changes['LogicFunction'], (0, 0, 0, 1))

    def test_logic_group_selector_recovery_and_shared_refusal(self):
        editor, current = self.editor('DIMDN8'), fixture('DIMDN8').defaults()
        with self.assertRaisesRegex(DinSettingsError, 'selector until a channel'):
            editor.plan(current, logic_group=2, logic_group_address=40)
        plan = editor.plan(current, channel=3, logic_groups=[2], logic_group=2, logic_group_address=40,
                           logic_level_store=False, logic_recovery_percent=50)
        self.assertEqual(plan.changes['GroupAddress'][13], 40)
        self.assertEqual(plan.changes['LightLevel'][13], 127)
        self.assertEqual(plan.changes['LogicLevelStoreEnable'], (1, 0, 1, 1))
        with self.assertRaisesRegex(DinSettingsError, 'logic level slider'):
            editor.plan(current, channel=3, logic_groups=[2], logic_group=2, logic_recovery_level=9)
        current['GroupAddress'] = ' '.join(['40'] + ['255'] * 12 + ['40', '255', '255'])
        with self.assertRaisesRegex(DinSettingsError, 'shared by channels'):
            editor.plan(current, logic_group=2, logic_level_store=False)

    def test_turn_on_min_max_percent_coupling_and_raw_levels(self):
        editor, current = self.editor('DIMDN8'), fixture('DIMDN8').defaults()
        plan = editor.plan(current, channel=2, min_percent=40, max_percent=80)
        self.assertEqual((plan.changes['MinDimmingLevel'][1], plan.changes['MaxDimmingLevel'][1]), (102, 204))
        plan = editor.plan(current, channel=2, max_percent=0)
        self.assertEqual(plan.changes['MaxDimmingLevel'][1], 0)
        self.assertNotIn('MinDimmingLevel', plan.changes)
        current['MaxDimmingLevel'] = ' '.join(['255', '76'] + ['255'] * 6)
        plan = editor.plan(current, channel=2, min_percent=30)
        # max slider (30 %) moves to min+1 = 31 % -> level 79.
        self.assertEqual((plan.changes['MinDimmingLevel'][1], plan.changes['MaxDimmingLevel'][1]), (76, 79))
        self.assertEqual(plan.derived, ('MaxDimmingLevel',))
        plan = editor.plan(fixture('DIMDN8').defaults(), channel=1, min_percent=100)
        self.assertEqual((plan.changes['MinDimmingLevel'][0], 'MaxDimmingLevel' in plan.changes), (255, False))
        plan = editor.plan(fixture('DIMDN8').defaults(), channel=8, min_level=1, max_level=254)
        self.assertEqual((plan.changes['MinDimmingLevel'][7], plan.changes['MaxDimmingLevel'][7]), (1, 254))
        with self.assertRaisesRegex(DinSettingsError, 'exceeds'):
            editor.plan(fixture('DIMDN8').defaults(), channel=8, min_level=200, max_level=100)
        with self.assertRaisesRegex(DinSettingsError, 'either'):
            editor.plan(current, channel=1, min_level=1, min_percent=1)
        relay = self.editor('RELDN4')
        plan = relay.plan(fixture('RELDN4').defaults(), channel=4, min_percent=100)
        self.assertEqual(plan.changes, {'MinDimmingLevel': (0, 0, 0, 255)})
        with self.assertRaisesRegex(DinSettingsError, 'minimum threshold'):
            relay.plan(fixture('RELDN4').defaults(), channel=1, max_percent=50)

    def test_recovery_level_store_255_rule_delay_and_dimmer_only_delay(self):
        editor, current = self.editor('DIMDN4'), fixture('DIMDN4').defaults()
        with self.assertRaisesRegex(DinSettingsError, 'disables the recovery level'):
            editor.plan(current, channel=1, recovery_percent=50)
        plan = editor.plan(current, channel=1, level_store=False, recovery_percent=50, recovery_delay=61)
        self.assertEqual(plan.changes['LevelStoreEnable'], (0, 1, 1, 1))
        self.assertEqual(plan.changes['LightLevel'][0], 127)
        self.assertEqual(plan.changes['PowerUpDelay'], (61, 5, 5, 5))
        current['LevelStoreEnable'], current['LightLevel'] = '0 1 1 1', ' '.join(['80'] + ['0'] * 15)
        plan = editor.plan(current, channel=1, level_store=True)
        self.assertEqual(plan.changes['LightLevel'][0], 255)
        self.assertEqual(plan.derived, ('LightLevel',))
        for bad in (4, 256):
            with self.assertRaisesRegex(DinSettingsError, 'Recovery delay'):
                editor.plan(current, channel=2, recovery_delay=bad)
        with self.assertRaisesRegex(DinSettingsError, 'hides the delay'):
            self.editor('RELDN8').plan(fixture('RELDN8').defaults(), channel=1, recovery_delay=10)

    def test_recovery_group_coupling_reproduces_toolkit_propagation(self):
        editor, current = self.editor('RELDN8B'), fixture('RELDN8B').defaults()
        groups = ['7', '7', '7', '9'] + ['255'] * 8 + ['7', '255', '7', '255']
        current['GroupAddress'] = ' '.join(groups)
        current['LevelStoreEnable'] = '0 0 1 0 0 0 0 0 1 1 1 1'
        plan = editor.plan(current, channel=1, recovery_percent=10)
        light = plan.changes['LightLevel']
        # Channel 2 follows via PercentToLevel; channel 3 keeps its level store;
        # logic groups 1 and 3 on group 7 use Round(10 * 2.55) = 26.
        self.assertEqual((light[0], light[1], light[2], light[3], light[12], light[14]), (25, 25, 0, 0, 26, 26))
        with self.assertRaisesRegex(DinSettingsError, 'use a percentage'):
            editor.plan(current, channel=1, recovery_level=25)
        with self.assertRaisesRegex(DinSettingsError, 'shared by other channels'):
            editor.plan(current, channel=1, level_store=True)
        plan = editor.plan(current, channel=4, recovery_level=77)
        self.assertEqual(plan.changes['LightLevel'][3], 77)

    def test_restrike_interlock_and_type_gates(self):
        relay, current = self.editor('RELDN12'), fixture('RELDN12').defaults()
        with self.assertRaisesRegex(DinSettingsError, 'restrike delay until'):
            relay.plan(current, restrike_delay=6)
        plan = relay.plan(current, channel=5, restrike=True, restrike_delay=254, interlock=8)
        self.assertEqual(plan.changes['RestrikeChannel'][4], 1)
        self.assertEqual((plan.changes['RestrikeDelay'], plan.changes['InterLockingChannel']), ((254,), (7,)))
        self.assertEqual(relay.plan(current, interlock=2).changes['InterLockingChannel'], (1,))
        for bad in (1, 9, True):
            with self.assertRaisesRegex(DinSettingsError, 'Interlock'):
                relay.plan(current, interlock=bad)
        with self.assertRaisesRegex(DinSettingsError, '2..4'):
            self.editor('RELDN4').plan(fixture('RELDN4').defaults(), interlock=5)
        for unit_type in ('RELDN8', 'DIMDN8'):
            with self.assertRaisesRegex(DinSettingsError, 'hides the interlock'):
                self.editor(unit_type).plan(fixture(unit_type).defaults(), interlock=2)
        with self.assertRaisesRegex(DinSettingsError, 'only on relay'):
            self.editor('DIMDN8').plan(fixture('DIMDN8').defaults(), channel=1, restrike=True)
        for bad in (0, 255):
            with self.assertRaisesRegex(DinSettingsError, 'Restrike delay'):
                relay.plan(current, channel=1, restrike=True, restrike_delay=bad)
        with self.assertRaisesRegex(DinSettingsError, 'Channel must'):
            relay.plan(current, channel=13, restrike=True)
        with self.assertRaisesRegex(DinSettingsError, 'require a channel'):
            relay.plan(current, restrike=True)

    def test_reldn8_marshalling_channel_map(self):
        editor, current = self.editor('RELDN8'), fixture('RELDN8').defaults()
        plan = editor.plan(current, channel=5, restrike=True, min_percent=50)
        self.assertEqual(plan.changes['RestrikeChannel'], (0,) * 7 + (1,) + (0,) * 4)
        self.assertEqual(plan.changes['MinDimmingLevel'][7], 127)
        plan = editor.plan(current, channel=1, level_store=False, recovery_percent=100)
        self.assertEqual(plan.changes['LevelStoreEnable'], (1, 0) + (1,) * 10)
        self.assertEqual([row['pp_index'] for row in editor.show(current)['channels']], [1, 2, 3, 4, 7, 8, 9, 10])
        self.assertEqual(self.editor('RELDN8B').plan(fixture('RELDN8B').defaults(), channel=5, restrike=True)
                         .changes['RestrikeChannel'][4], 1)

    def test_show_projects_toolkit_display(self):
        editor, current = self.editor('RELDN4'), fixture('RELDN4').defaults()
        current['InterLockingChannel'] = '9'
        view = editor.show(current)
        self.assertEqual(view['interlock'], {'raw': 9, 'toolkit_index': 1, 'channels': 2})
        self.assertEqual(view['restrike_delay'], {'raw': 60, 'seconds': 600, 'toolkit_range': True})
        self.assertIsNone(view['channels'][0]['recovery_percent'])
        self.assertTrue(view['channels'][0]['toolkit_save_rewrites_recovery_level'])
        self.assertNotIn('max_level', view['channels'][0])
        dimmer = self.editor('DIMDN4').show(fixture('DIMDN4').defaults())
        self.assertEqual((dimmer['channels'][3]['max_percent'], dimmer['channels'][3]['recovery_delay_seconds']), (100, 5))
        self.assertEqual(dimmer['interlock']['toolkit_control'], False)


class ApplyTest(unittest.TestCase):
    def test_apply_verifies_profile_schema_staleness_and_preserves_unrelated(self):
        editor, live = DinOutputEditor(fixture('DIMDN8')), session('DIMDN8')
        live.current['UnitAddress'] = '12'
        plan = editor.plan(live.values(), channel=8, min_percent=10, max_percent=90)
        result = editor.apply(live, plan)
        self.assertTrue(result['verified'])
        self.assertEqual([n for n, _ in live.calls], ['MinDimmingLevel', 'MaxDimmingLevel'])
        self.assertEqual((live.current['UnitAddress'], live.current['AreaGroupAddress']), ('12', '255'))
        with self.assertRaisesRegex(DinSettingsError, 'changed since'):
            editor.apply(live, plan)
        stale = session('DIMDN8')
        stale.firmware = '2.6.00'
        with self.assertRaisesRegex(DinSettingsError, 'Native session'):
            editor.apply(stale, editor.plan(stale.values(), channel=1, min_percent=1))
        self.assertEqual(stale.calls, [])
        other = session('DIMDN8F')
        with self.assertRaisesRegex(DinSettingsError, 'unit type differs'):
            editor.apply(other, plan)

    def test_plan_document_roundtrip_and_partial_failure(self):
        editor, live = DinOutputEditor(fixture('RELDN8')), session('RELDN8')
        plan = editor.plan(live.values(), channel=2, restrike=True, identity=('RELDN8', FIRMWARE, '5508RVF'))
        document = json.loads(json.dumps(plan.as_dict()))
        self.assertEqual(document['format'], 'cbus-din-output-settings-plan-v1')
        self.assertEqual(DinPlan.from_dict(document), plan)
        live.failure = 'RestrikeChannel'
        with self.assertRaises(DinSettingsApplyError) as error:
            editor.apply(live, DinPlan.from_dict(document))
        self.assertEqual(error.exception.attempted, ('RestrikeChannel',))
        self.assertEqual(len(live.calls), 1)
        with self.assertRaisesRegex(DinSettingsError, 'Expected a'):
            DinPlan.from_dict({'format': 'other'})


def native_backend():
    if os.environ.get('CBUS_NATIVE_SERVICE_BACKEND') == 'local':
        return 'local' if os.environ.get('CBUS_LOCAL_CGATE_VENDOR') and os.environ.get('CBUS_CGATE_JAVA') else None
    return 'host' if os.environ.get('CBUS_CGATE_TEST_HOST') else None


def raw_bytes(pp, address, count):
    return bytes.fromhex(pp.get_raw_data(address, count).lines[-1].split('RawData=', 1)[1])


# Per admitted type: catalogue number used for the owned C-Gate database unit.
NATIVE_TYPES = (('RELDN4', '5504RVF'), ('RELDN8', '5508RVF'), ('RELDN8B', 'L5508RVF'),
                ('RELDN12', '5512RVF'), ('DIMDN4', '5504D2A'), ('DIMDN4F', 'SLC5504TD4A'),
                ('DIMDN8', '5508D1A'), ('DIMDN8F', 'SLC5508TD2A'))
NATIVE_REFUSED = (('RELDN8SP', '2.7.00', None), ('RELDN8', '2.6.00', '5508RVF'), ('DIMDN8', '2.7.01', '5508D1A'))


@unittest.skipUnless(native_backend() and os.environ.get('CBUS_UNITSPEC_DIR'),
                     'Select native C-Gate and unit specs for DIN output settings acceptance')
class DinOutputNativeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = None
        cls.host, cls.port = os.environ.get('CBUS_CGATE_TEST_HOST'), int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        if native_backend() == 'local':
            from research.local_cgate import LocalCGate
            cls.service = LocalCGate(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
            cls.addClassCleanup(cls.service.close)
            (cls.service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
            cls.service.start()
            cls.host, cls.port = '127.0.0.1', cls.service.port
        cls.store = UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR'])

    def check(self, pp, editor, before, report, case, label, expect_bytes=(), **options):
        plan = editor.plan(pp.values(), identity=(pp.unit_type, pp.firmware, pp.catalog_number), **options)
        result = editor.apply(pp, plan)
        self.assertTrue(result['verified'])
        after = pp.values()
        unrelated = sorted(n for n in before if n not in FIELDS)
        self.assertEqual({n: after[n] for n in unrelated}, {n: before[n] for n in unrelated})
        for address, mask, value in expect_bytes:
            self.assertEqual(raw_bytes(pp, address, 1)[0] & mask, value, (label, address))
            case['raw_byte_assertions'] += 1
        case['positive'].append(label)
        case['unrelated_parameters_preserved'] = len(unrelated)
        report['edits'] += 1
        return after

    def refuse(self, pp, editor, case, label, pattern, **options):
        before = pp.values()
        with self.assertRaisesRegex(DinSettingsError, pattern):
            editor.configure(pp, **options)
        self.assertEqual(pp.values(), before)
        case['invalid'].append(label)

    def exercise(self, client, network, address, unit_type, catalog, report):
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        profile = PROFILES[unit_type]
        editor = DinOutputEditor(self.store.load(profile.spec_filename), unit_type)
        NativeDatabase(client).create_unit(network, address, 'Din' + str(address), unit_type, FIRMWARE,
                                           catalog_number=catalog)
        path = f'/db{network}/p/{address}'
        case = {'unit_type': unit_type, 'catalog_number': catalog, 'spec': profile.spec_filename,
                'positive': [], 'boundary': [], 'invalid': [], 'raw_byte_assertions': 0}
        n, first, second, last = profile.channels, *profile.indices[:2], profile.indices[-1]
        with Programmer(client).load(network, path) as pp:
            self.assertEqual((pp.unit_type, pp.firmware), (unit_type, FIRMWARE))
            editor._verify_session(pp)
            baseline = pp.values()
            # Neighbour fields sharing logic bytes 0x32.. are set first so the
            # read-modify-write is observable.
            pp.set('LogicGA14Associations', ' '.join(['1'] * editor.layout['LogicGA14Associations'][1]))
            pp.set('GroupAddress', ' '.join(['255'] * 13 + ['150', '255', '255']))
            before = pp.values()
            # Logic tab: associations, function, logic group selector and recovery.
            self.refuse(pp, editor, case, 'logic-unassigned-group', 'Logic group 1 is associated',
                        channel=n, logic_groups=[1, 2])
            self.check(pp, editor, before, report, case, 'logic', channel=n, logic_groups=[2, 4],
                       logic_function=('or' if profile.relay else 'max'), logic_group=4,
                       logic_group_address=200, logic_level_store=False, logic_recovery_percent=100,
                       expect_bytes=((0x32 + last, 0x8f, 0x8a), (0x50 + 15, 255, 200), (0x0f, 255, 255),
                                     (0x41, 0x80, 0x00)))
            case['boundary'].append('logic-last-channel-and-group-4')
            # Turn On / Min-Max tab.
            if profile.relay:
                self.check(pp, editor, before, report, case, 'turn-on-threshold', channel=1, min_percent=100,
                           expect_bytes=((0x60 + first, 255, 255),))
                self.check(pp, editor, before, report, case, 'turn-on-raw', channel=n, min_level=1,
                           expect_bytes=((0x60 + last, 255, 1),))
                self.refuse(pp, editor, case, 'relay-max', 'minimum threshold', channel=1, max_percent=50)
            else:
                maximum = editor.layout['MaxDimmingLevel'][0]
                self.check(pp, editor, before, report, case, 'min-max', channel=1, min_percent=40, max_percent=80,
                           expect_bytes=((0x60, 255, 102), (maximum, 255, 204)))
                self.check(pp, editor, before, report, case, 'min-coupling', channel=1, min_percent=80,
                           expect_bytes=((0x60, 255, 204), (maximum, 255, 206)))
                self.check(pp, editor, before, report, case, 'max-boundary', channel=n, max_percent=0,
                           expect_bytes=((maximum + last, 255, 0),))
                case['boundary'].append('max-0-min-0')
                self.refuse(pp, editor, case, 'inverted-raw', 'exceeds', channel=2, min_level=200, max_level=100)
            # Recovery tab.
            bit = 1 << (second % 8)
            self.check(pp, editor, before, report, case, 'recovery-level', channel=2, level_store=False,
                       recovery_percent=50, expect_bytes=((0x40 + second // 8, bit, 0), (second, 255, 127)))
            self.check(pp, editor, before, report, case, 'level-store-255', channel=2, level_store=True,
                       expect_bytes=((0x40 + second // 8, bit, bit), (second, 255, 255)))
            self.refuse(pp, editor, case, 'recovery-with-store', 'disables the recovery', channel=2,
                        recovery_percent=10)
            if profile.relay:
                self.refuse(pp, editor, case, 'relay-delay', 'hides the delay', channel=1, recovery_delay=10)
            else:
                self.check(pp, editor, before, report, case, 'recovery-delay', channel=n, recovery_delay=255,
                           expect_bytes=((0x44 + last, 255, 255),))
                self.check(pp, editor, before, report, case, 'recovery-delay-min', channel=1, recovery_delay=5,
                           expect_bytes=((0x44, 255, 5),))
                case['boundary'].append('recovery-delay-5-255')
                self.refuse(pp, editor, case, 'recovery-delay-low', 'Recovery delay', channel=1, recovery_delay=4)
            # Restrike tab and interlock.
            if profile.relay:
                self.refuse(pp, editor, case, 'restrike-delay-disabled', 'restrike delay until', restrike_delay=6)
                self.check(pp, editor, before, report, case, 'restrike', channel=n, restrike=True, restrike_delay=254,
                           expect_bytes=((0x32 + last, 0x40, 0x40), (0x42, 255, 254)))
                self.check(pp, editor, before, report, case, 'restrike-delay-min', restrike_delay=1,
                           expect_bytes=((0x42, 255, 1),))
                case['boundary'].append('restrike-delay-1-254')
                self.refuse(pp, editor, case, 'restrike-delay-0', 'Restrike delay', restrike_delay=0)
            else:
                self.refuse(pp, editor, case, 'dimmer-restrike', 'only on relay', channel=1, restrike=True)
            if profile.interlock:
                limit = min(n, 8)
                self.check(pp, editor, before, report, case, 'interlock', interlock=limit,
                           expect_bytes=((0x30, 255, limit - 1),))
                self.check(pp, editor, before, report, case, 'interlock-off', interlock=0,
                           expect_bytes=((0x30, 255, 0),))
                case['boundary'].append(f'interlock-0-{limit}')
                self.refuse(pp, editor, case, 'interlock-high', 'Interlock', interlock=limit + 1)
            else:
                self.refuse(pp, editor, case, 'interlock-hidden', 'hides the interlock', interlock=2)
            self.refuse(pp, editor, case, 'channel-high', 'Channel must', channel=n + 1, min_percent=1)
            after = pp.values()
            self.assertEqual(listed(after['LogicGA14Associations']), [1] * editor.layout['LogicGA14Associations'][1])
            unrelated = sorted(n for n in baseline if n not in FIELDS)
            self.assertEqual({k: after[k] for k in unrelated}, {k: baseline[k] for k in unrelated})
            expected = editor.snapshot(after)
            pp.save_to_source()
        client.command('PROJECT SAVE ' + network.split('/')[2])
        with Programmer(client).load(network, path) as pp:
            self.assertEqual(editor.snapshot(pp.values()), expected)
            self.assertEqual(pp.values(), after)
        case['save_reload_passed'] = True
        report['types'].append(case)
        report['raw_byte_assertions'] += case['raw_byte_assertions']

    def refuse_type(self, client, network, address, unit_type, firmware, catalog, report):
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        NativeDatabase(client).create_unit(network, address, 'Ref' + str(address), unit_type, firmware,
                                           catalog_number=catalog)
        spec_type = unit_type if unit_type in PROFILES else 'RELDN8'
        editor = DinOutputEditor(self.store.load(PROFILES[spec_type].spec_filename), spec_type)
        with Programmer(client).load(network, f'/db{network}/p/{address}') as pp:
            before = pp.values()
            with self.assertRaisesRegex(DinSettingsError, 'Native session'):
                editor.configure(pp, channel=1, min_percent=10)
            self.assertEqual(pp.values(), before)
        report['refused'].append({'unit_type': unit_type, 'firmware': firmware, 'values_unchanged': True})

    def test_admitted_types_tabs_raw_bytes_preservation_save_reload_and_refusals(self):
        from cbus_toolkit.cgate import CGateClient
        project = 'DO' + uuid4().hex[:6].upper()
        network = f'//{project}/254'
        report = {'format': 'cbus-din-output-settings-acceptance-v1', 'backend': native_backend(),
                  'firmware': FIRMWARE, 'scope': ('Toolkit source-grounded DIN Logic/Turn On/Recovery/Restrike '
                                                  'settings through native PP and a closed database; no physical outputs'),
                  'types': [], 'refused': [], 'edits': 0, 'raw_byte_assertions': 0, 'passed': False,
                  'physical_hardware_verified': False}
        with CGateClient(self.host, self.port, timeout=30) as client:
            report['greeting'] = client.greeting
            client.command('PROJECT NEW ' + project)
            try:
                client.command('PROJECT USE ' + project)
                client.command('DBCREATENET 254 Din_Offline Cni 127.0.0.1:29999')
                client.command('NET LOAD DB ' + project)
                client.command('PROJECT SAVE ' + project)
                for index, (unit_type, catalog) in enumerate(NATIVE_TYPES):
                    with self.subTest(unit_type=unit_type):
                        self.exercise(client, network, 20 + index, unit_type, catalog, report)
                for index, (unit_type, firmware, catalog) in enumerate(NATIVE_REFUSED):
                    with self.subTest(refused=unit_type, firmware=firmware):
                        self.refuse_type(client, network, 40 + index, unit_type, firmware, catalog, report)
                report['passed'] = (len(report['types']) == len(NATIVE_TYPES)
                                    and len(report['refused']) == len(NATIVE_REFUSED))
                self.assertTrue(report['passed'])
            finally:
                client.command('PROJECT CLOSE ' + project)
                try:
                    client.command('PROJECT DELETE ' + project)
                except Exception as error:  # noqa: BLE001 - cleanup evidence only
                    report['project_delete_error'] = str(error)
                if self.service is not None:
                    report['service'] = {k: self.service.report.get(k) for k in (
                        'vendor_jar_sha256', 'java_version', 'listener_ownership_verified', 'listeners')}
                if os.environ.get('CBUS_DIN_REPORT'):
                    Path(os.environ['CBUS_DIN_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
