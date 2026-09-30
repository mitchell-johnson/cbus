"""ST7 PIR dialog/forced-save vectors, receipt checks and closed native PP tests."""
import json
import os
from pathlib import Path
import re
import unittest
from uuid import uuid4

from cbus_toolkit.pir_sensors import (FORCED, KEY_EVENTS, LAYOUTS, PROFILES, PIRSensor, margin_percent,
                                      power_up_state, profile, saved_margin)
from cbus_toolkit.sensors import EVENTS, SensorApplyError, SensorError, profile_refusal
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore
from test_macros import Session


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / 'docs/pir-sensor-review.json'
PROFILE_REVIEW = ROOT / 'docs/sensor-profile-review.json'
STAGES = ('JPCommand', 'SRCommand', 'LPCommand', 'LRCommand')
BITS = ('DisableIR', 'CorridorLinkActive', 'PECFunctionActive', 'PECFunctionIRActive', 'PIRFunctionIRActive',
        'PECLevelStore', 'PIRLevelStore', 'PECEnablerGroupLogic', 'PIREnablerGroupLogic')
# Independent literal layout from SENPILL_ST7's PP table (address, count, bits,
# bit, skip) and a non-default "dirty" starting state for every forced field.
ROWS = {
    'JPCommand': (104, 8, 4, 4, 1, [7, 13, 13, 13, 5, 5, 5, 5]), 'SRCommand': (104, 8, 4, 0, 1, [0, 7, 15, 15, 5, 5, 5, 5]),
    'LPCommand': (105, 8, 4, 4, 1, [0, 7, 7, 0, 5, 5, 5, 5]), 'LRCommand': (105, 8, 4, 0, 1, [0, 0, 15, 15, 5, 5, 5, 5]),
    'PIRLightMovement': (50, 1, 8, 0, 0, [255]), 'PIRDarkMovement': (51, 1, 8, 0, 0, [255]), 'PIRDark': (52, 1, 8, 0, 0, [255]),
    'IRBank': (53, 1, 2, 0, 0, [3]), 'DisableIR': (53, 1, 1, 2, 0, [0]), 'IRBankKeyOffset': (53, 1, 3, 4, 0, [5]),
    'BlockAllocation': (54, 8, 8, 0, 0, [1, 2, 4, 8, 16, 32, 64, 128]), 'GroupAddress': (80, 8, 8, 0, 0, [255] * 8),
    'Application': (33, 2, 8, 0, 0, [56, 255]), 'SecondApplicationBlocks': (69, 1, 8, 0, 0, [0]),
    'SceneKeySelector': (96, 8, 1, 7, 0, [1] * 8), 'IndicatorBlockAssignment': (96, 8, 3, 0, 0, [1, 3, 3, 3, 3, 3, 3, 3]),
    'TimerHighByte': (136, 8, 8, 0, 0, [1] * 8), 'TimerLowByte': (144, 8, 8, 0, 0, [44] * 8),
    'TimerExpiryCommand': (72, 8, 4, 0, 0, [15] * 8),
    'CorridorLinkOfficeBlock': (68, 1, 3, 0, 0, [2]), 'CorridorLinkBlock': (68, 1, 3, 3, 0, [3]),
    'CorridorLinkActive': (68, 1, 1, 7, 0, [1]), 'BroadcastBlock': (70, 1, 3, 0, 0, [5]),
    'IndicatorControl': (70, 1, 2, 3, 0, [2]), 'BroadcastActive': (70, 1, 3, 5, 0, [3]),
    'PECTargetLux': (27, 1, 8, 0, 0, [50]), 'PECMarginLux': (28, 1, 8, 0, 0, [7]),
    'LightLevel': (1, 10, 8, 0, 0, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]),
    'PIREnablerGroup': (88, 1, 8, 0, 0, [255]), 'PECEnablerGroup': (89, 1, 8, 0, 0, [9]),
    'SingleJoinEnablerGroup': (90, 1, 8, 0, 0, [10]), 'DualJoinEnablerGroup': (91, 1, 8, 0, 0, [11]),
    'CorridorLinkEnablerGroup': (92, 1, 8, 0, 0, [12]), 'SingleJoinEnablerControlGroup': (93, 1, 8, 0, 0, [13]),
    'DualJoinEnablerControlGroup': (94, 1, 8, 0, 0, [14]), 'ControlAppGroupAddress': (95, 1, 8, 0, 0, [15]),
    'PECFunctionBlock': (96, 1, 3, 3, 0, [4]), 'PECFunctionActive': (96, 1, 1, 6, 0, [1]),
    'PECFunctionIRKey': (97, 1, 3, 3, 0, [4]), 'PECFunctionIRActive': (97, 1, 1, 6, 0, [1]),
    'PIRFunctionIRKey': (98, 1, 3, 3, 0, [4]), 'PIRFunctionIRActive': (98, 1, 1, 6, 0, [1]),
    'PECLevelStore': (99, 1, 1, 3, 0, [1]), 'PIRLevelStore': (99, 1, 1, 4, 0, [0]),
    'PECEnablerGroupLogic': (99, 1, 1, 5, 0, [1]), 'PIREnablerGroupLogic': (99, 1, 1, 6, 0, [0]),
    'PotentiometerAFunction': (101, 1, 2, 3, 0, [2]), 'PotentiometerBFunction': (101, 1, 2, 5, 0, [1]),
    'PotentiometerATimerBlock': (102, 1, 3, 3, 0, [3]), 'PotentiometerBTimerBlock': (103, 1, 3, 3, 0, [3]),
    'PotentiometerBBankSwitchEnable': (103, 1, 1, 6, 0, [1]),
}


def fixture(unit_type='SENPIRIA', filename='SENPIRIA_ST7.xml'):
    parameters = {}
    for name, (address, count, bits, bit, skip, values) in ROWS.items():
        kind = 'bit' if name in BITS else 'int'
        fields = {'Name': name, 'Type': kind, 'Address': str(address), 'ArraySize': str(count), 'BitSize': str(bits),
                  'BitAddress': str(bit), 'ArraySkip': str(skip), 'DefaultValue': ' '.join(map(str, values))}
        parameters[name] = ParameterSpec(name, kind, 'literal-pir-fixture.xml', fields)
    return UnitSpec(filename, {'Type': unit_type}, ('literal-pir-fixture.xml',), parameters)


def ints(value):
    return [int(v, 0) for v in value.split()]


class PIRSaveModelTest(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.sensor = PIRSensor(self.spec)

    def session(self, **values):
        session = Session(self.spec)
        session.firmware, session.catalog_number = '2.3.00', '5751L'
        session.current.update({k: ' '.join(map(str, v)) for k, v in values.items()})
        return session

    def test_unchanged_dialog_save_forces_and_normalizes_exactly(self):
        session = self.session()
        result = self.sensor.configure(session)
        values = {name: ints(value) for name, value in session.current.items()}
        for name, value in FORCED.items():
            self.assertEqual(values[name], [value], name)
        # Literal PrepareForcedParameters vector, independent of FORCED.
        self.assertEqual((values['PIRLightMovement'], values['PIRDarkMovement'], values['PIRDark']), ([9], [10], [4]))
        self.assertEqual((values['PotentiometerAFunction'], values['DisableIR'], values['ControlAppGroupAddress']), ([1], [1], [255]))
        # LightLevel 4..7 and 9 forced to 0; 8 is the occupancy power-up level:
        # logic 0 and level 9 loads "disabled" and saves 0.
        self.assertEqual(values['LightLevel'], [1, 2, 3, 4, 0, 0, 0, 0, 0, 0])
        self.assertEqual(values['SceneKeySelector'], [0, 1, 1, 1, 1, 1, 1, 1])
        self.assertEqual(values['IndicatorBlockAssignment'], [1, 3, 3, 3, 3, 3, 3, 3])
        self.assertEqual(values['BroadcastActive'], [4])
        # 7/50 -> 14%; 50 * ext(0.14) = 7.0000000000000000001 -> 7.
        self.assertEqual((values['PECTargetLux'], values['PECMarginLux']), ([50], [7]))
        self.assertEqual(values['PIRLevelStore'], [0])
        for name in STAGES + ('BlockAllocation', 'GroupAddress', 'TimerHighByte', 'TimerLowByte', 'TimerExpiryCommand'):
            self.assertEqual(values[name], ROWS[name][-1], name)
        self.assertEqual(result['keys'], [])
        self.assertEqual(result['dialog']['power_up'], 'disabled')
        self.assertFalse(result['saved'])

    def test_conditional_indicator_broadcast_and_power_up_round_trips(self):
        session = self.session(IndicatorBlockAssignment=[7, 3, 3, 3, 3, 3, 3, 3], BroadcastActive=[7])
        self.sensor.configure(session)
        self.assertEqual(ints(session.current['IndicatorBlockAssignment']), [7, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(ints(session.current['BroadcastActive']), [0])
        for level, logic, store, state in ((255, 0, 0, 1), (255, 1, 0, 0), (9, 1, 0, 1), (0, 0, 0, 0), (9, 0, 1, 2)):
            self.assertEqual(power_up_state(level, logic, store), state)
        light = [0] * 8 + [255, 0]
        session = self.session(LightLevel=light, PIRLevelStore=[0], PIREnablerGroupLogic=[0], PIREnablerGroup=[30])
        # Loaded "enabled"; flipping the enable polarity keeps the state and
        # therefore rewrites the stored power-up level.
        self.sensor.configure(session, enabled_when='off')
        self.assertEqual((ints(session.current['LightLevel'])[8], ints(session.current['PIREnablerGroupLogic'])), (0, [1]))
        session = self.session(LightLevel=light, PIRLevelStore=[0])
        self.sensor.configure(session, power_up='resume')
        self.assertEqual((ints(session.current['LightLevel'])[8], ints(session.current['PIRLevelStore'])), (255, [1]))
        session = self.session(PIRLevelStore=[1])
        self.sensor.configure(session, power_up='enabled')
        self.assertEqual((ints(session.current['LightLevel'])[8], ints(session.current['PIRLevelStore'])), (255, [0]))

    def test_x87_margin_arithmetic_vectors(self):
        # Hand-derived: ext(0.59) is below 0.59, so 50*ext(0.59) < 29.5 -> 29,
        # while ext(0.10) is above 0.1 and 55*ext(0.10) rounds up to 6.
        for target, percent, margin in ((55, 10, 6), (50, 59, 29), (75, 42, 31), (95, 30, 29), (0, 30, 0), (255, 0, 0)):
            self.assertEqual(saved_margin(target, percent), margin)
        for target, margin, percent in ((50, 7, 14), (255, 1, 0), (8, 1, 12), (0, 9, 0), (1, 255, 25500)):
            self.assertEqual(margin_percent(target, margin), percent)
        session = self.session(PECTargetLux=[136], PECMarginLux=[255])
        with self.assertRaisesRegex(SensorError, '256'):
            self.sensor.plan(session.values())

    def test_key_group_block_timer_link_and_function_prompt(self):
        session = self.session()
        with self.assertRaisesRegex(SensorError, 'restore_functions'):
            self.sensor.plan(session.values(), keys={4: {'group': 20}})
        plan = self.sensor.plan(session.values(), keys={4: {'group': 20, 'timer_seconds': 600, 'expiry': 'ramp_off'}},
                                restore_functions=True)
        self.assertEqual(plan.dialog['restored_functions'], [4])
        final = {**plan.expected, **plan.changes}
        self.assertEqual(tuple(final[n][3] for n in STAGES), EVENTS['any'])
        self.assertEqual((plan.changes['GroupAddress'][3], plan.changes['TimerHighByte'][3], plan.changes['TimerLowByte'][3]), (20, 2, 88))
        kept = self.sensor.plan(session.values(), keys={4: {'group': 20}}, restore_functions=False)
        self.assertNotIn('JPCommand', kept.changes)
        self.assertEqual(kept.dialog['kept_custom_functions'], [4])
        # Key 1 already has the fixed day function: no prompt is needed.
        plan = self.sensor.plan(session.values(), keys={1: {'block': 3, 'group': 7}}, allow_shared_block=True)
        self.assertEqual(plan.changes['BlockAllocation'][:2], (4, 2))
        # Linking copies key 1's blocks to key 2, which fires key 2's template check.
        custom = self.session(SRCommand=[0, 5, 15, 15, 5, 5, 5, 5])
        with self.assertRaisesRegex(SensorError, r'\[2\]'):
            self.sensor.plan(custom.values(), darkness_same_as_light=True)
        self.assertEqual(self.sensor.plan(session.values(), darkness_same_as_light=True).keys, (2,))
        linked = self.sensor.plan(session.values(), darkness_same_as_light=True, restore_functions=True,
                                  keys={1: {'block': 3, 'group': 7}}, allow_shared_block=True)
        self.assertEqual(linked.changes['BlockAllocation'][:2], (4, 4))
        self.assertEqual(linked.keys, (1, 2))
        with self.assertRaisesRegex(SensorError, 'follows'):
            self.sensor.plan(session.values(), darkness_same_as_light=True, keys={2: {'block': 1}})
        # A loaded equal allocation is the dialog's checked link state.
        session = self.session(BlockAllocation=[4, 4, 4, 8, 16, 32, 64, 128])
        plan = self.sensor.plan(session.values(), keys={1: {'block': 1, 'group': 5}}, allow_shared_block=True)
        self.assertTrue(plan.dialog['darkness_same_as_light'])
        self.assertEqual(plan.changes['BlockAllocation'][:2], (1, 1))

    def test_refusals_and_bounds(self):
        current = self.session().values()
        for options, pattern in (({'keys': {5: {'group': 1}}}, 'key 1..4'), ({'keys': {True: {}}}, 'key 1..4'),
                                 ({'keys': {1: {'block': 5, 'group': 1}}}, '1..4'), ({'keys': {1: {'group': 256}}}, '0..255'),
                                 ({'keys': {1: {'color': 1}}}, 'Key options'), ({'keys': {1: {'expiry': 'off'}}}, 'requires timer'),
                                 ({'keys': {1: {'timer_seconds': 65536}}}, '0..65535'),
                                 ({'keys': {1: {'block': 3, 'group': 7}}}, 'shared'),
                                 ({'enabled_when': 'off'}, 'assigned occupancy'), ({'power_up': 'on'}, 'power_up'),
                                 ({'restore_functions': 1}, 'boolean'), ({'identity': ('SENPIRIA', '2.4.00', '5751L')}, 'SENPIRIA_ST7_2'),
                                 ({'identity': ('SENPIRIB', '2.3.00', '5753L')}, 'not SENPIRIA_ST7')):
            with self.subTest(options=options), self.assertRaisesRegex(SensorError, pattern):
                self.sensor.plan(current, **options)
        session = self.session(BlockAllocation=[16, 2, 4, 8, 16, 32, 64, 128])
        with self.assertRaisesRegex(SensorError, 'not one PIR block'):
            self.sensor.plan(session.values(), keys={1: {'group': 3}})
        session = self.session(Application=[200, 255])
        with self.assertRaisesRegex(SensorError, 'Lighting'):
            self.sensor.plan(session.values(), keys={1: {'group': 3}})
        with self.assertRaises(SensorError):
            PIRSensor(fixture('SENPILL', 'SENPILL_ST7.xml'))

    def test_apply_profile_staleness_preservation_and_partial_failure(self):
        session = self.session()
        session.current['Other'] = 'unchanged'
        plan = self.sensor.plan(session.values(), keys={1: {'group': 19}})
        self.assertTrue(self.sensor.apply(session, plan)['verified'])
        self.assertEqual(session.current['Other'], 'unchanged')
        with self.assertRaisesRegex(SensorError, 'changed since'):
            self.sensor.apply(session, plan)
        for field, value in (('firmware', '2.4.00'), ('firmware', '2.0.00'), ('catalog_number', '5753L'),
                             ('unit_type', 'SENPILL'), ('unit_type', 'SENLL')):
            session = self.session()
            setattr(session, field, value)
            with self.assertRaisesRegex(SensorError, 'Native session'):
                self.sensor.apply(session, plan)
            self.assertEqual(session.calls, [])
        session = self.session()
        session.failure = 'GroupAddress'
        plan = self.sensor.plan(session.values(), keys={1: {'group': 19}})
        with self.assertRaises(SensorApplyError) as error:
            self.sensor.apply(session, plan)
        self.assertEqual(error.exception.attempted[-1], 'GroupAddress')
        self.assertEqual(sum(name == 'GroupAddress' for name, _ in session.calls), 1)


class PIRProfileTest(unittest.TestCase):
    def test_catalogue_decisions_and_registration_boundaries(self):
        review = json.loads(PROFILE_REVIEW.read_text())
        seen = set()
        for row in review['decisions']:
            if row['unit_type'] not in PROFILES or 'firmware_min' not in row:
                continue
            pir = row['toolkit_class'] in ('TST7SENPIRSS', 'TST7SENPIROA') and row['spec'].endswith(('_ST7.xml', '_ST7_2.xml'))
            for version in (row['firmware_min'], row['firmware_max']):
                with self.subTest(row=row, version=version):
                    reason, spec = profile(row['unit_type'], version, row['catalog_number'])
                    self.assertEqual(reason is None, pir)
                    if pir:
                        self.assertEqual(spec, row['spec'])
                        self.assertEqual(PROFILES[row['unit_type']]['toolkit_class'], row['toolkit_class'])
                        seen.add((row['unit_type'], row['catalog_number']))
        self.assertEqual(seen, {(t, c) for t, p in PROFILES.items() for c in p['catalog_numbers']})
        for identity, pattern in ((('SENPIRIB', '2.3.10', '5753L'), 'unregistered'), (('SENPIRIB', '2.4.00', '5753L'), 'SENPIRIC'),
                                  (('SENPIRIA', '2.0.00', '5751L'), 'no admitted'), (('SENPIRIA', '2.3.00', '5753L'), 'catalogue'),
                                  (('SENPILL', '2.3.00', '5753PEIRL'), 'multisensor'), (('SENLL', '2.3.00', '5031PE'), 'Only')):
            with self.subTest(identity=identity):
                self.assertRegex(profile(*identity)[0], pattern)
        # The multisensor workflow keeps refusing the PIR types.
        self.assertIn('PIR sensor class', profile_refusal('SENPIRIA', '2.3.00', '5751L'))


class PIRReviewTest(unittest.TestCase):
    def setUp(self):
        self.review = json.loads(REVIEW.read_text())

    def test_receipt_is_sanitized_and_matches_the_model(self):
        text = REVIEW.read_text()
        for private in ('<Param', 'DefaultValue', 'CLIPSAL', 'Motion in'):
            self.assertNotIn(private, text)
        self.assertFalse(self.review['original_execution'])
        writes = self.review['save']['prepare_forced_parameters']['writes']
        scalar = {w['parameter']: w['value'] for w in writes if w.get('write') == 'SetValue'}
        self.assertEqual({k: v for k, v in scalar.items() if k != 'SceneKeySelector'},
                         {k: v for k, v in FORCED.items() if k != 'PotentiometerBBankSwitchEnable'})
        self.assertEqual(scalar['SceneKeySelector'], 0)
        self.assertEqual([(w['index'], w['value']) for w in writes if w['parameter'] == 'LightLevel'],
                         [(4, 0), (5, 0), (6, 0), (7, 0), (9, 0)])
        self.assertEqual(self.review['save']['multisensor_before_save']['unconditional_writes'],
                         [{'parameter': 'PotentiometerBBankSwitchEnable', 'value': 0}])
        self.assertEqual(self.review['save']['pir_before_save']['conditional_write']['value'], [7, 0, 0, 0, 0, 0, 0, 0])
        for key, row in self.review['key_templates'].items():
            self.assertEqual(tuple(row['jp_sr_lp_lr']), EVENTS[KEY_EVENTS[int(key)]])
        unit = self.review['unit']
        self.assertEqual((unit['MaximumBlockCount'], unit['MaximumIndicatorCount']), (4, 1))
        for limits in unit['classes'].values():
            self.assertEqual(limits, {'MaximumKeyCount': 4, 'GetMaximumVirtualKeyCount': 4,
                                      'IsJoinModeSupported': False, 'IsDualJoinModeSupported': False})
        self.assertEqual(self.review['dialog']['hidden_tabs'], ['tsBankSwitch', 'tsEnvironment', 'tsLightLevel', 'tsScenes'])
        self.assertEqual(self.review['dialog']['disabled_block_grid_key_columns'], [5, 6, 7, 8])
        self.assertTrue(set(FORCED) <= set(LAYOUTS))

    @unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'Set the Toolkit EXE to regenerate the PIR receipt')
    def test_receipt_regenerates_from_private_inputs(self):
        from research.pir_sensor_review import review
        exe = Path(os.environ['CBUS_TOOLKIT_EXE'])
        self.assertEqual(json.loads(json.dumps(review(exe, exe.with_suffix('.map')))), self.review)


def native_backend():
    if os.environ.get('CBUS_NATIVE_SERVICE_BACKEND') == 'local':
        return 'local' if os.environ.get('CBUS_LOCAL_CGATE_VENDOR') and os.environ.get('CBUS_CGATE_JAVA') else None
    return 'host' if os.environ.get('CBUS_CGATE_TEST_HOST') else None


def raw_bytes(session, address, count):
    return bytes.fromhex(session.get_raw_data(address, count).lines[-1].split('RawData=', 1)[1])


# One profile per admitted type, catalogue and specification band edge.
NATIVE_PROFILES = (('SENPIROA', '2.0.01', '5750WPL'), ('SENPIROA', '2.4.99', 'SLC5750WPL,GY'),
                   ('SENPIRIA', '2.2.00', 'SLC5751L,WE'), ('SENPIRIA', '2.4.00', '5751L'),
                   ('SENPIRIB', '2.1.00', 'SLC5753L'), ('SENPIRIB', '2.3.9', '5753L'))
NATIVE_REFUSED = (('SENPIRIB', '2.3.10', '5753L'), ('SENPIRIB', '2.4.00', '5753L'), ('SENPIRIA', '2.0.00', '5751L'),
                  ('SENPILL', '2.3.00', '5753PEIRL'), ('SENLL', '2.3.00', '5031PE'))
# A dirty baseline that the Toolkit save must overwrite or normalize.
DIRTY = {'PIRLightMovement': '255', 'PIRDarkMovement': '255', 'PIRDark': '255', 'IRBank': '3', 'DisableIR': '0',
         'IRBankKeyOffset': '5', 'CorridorLinkOfficeBlock': '2', 'CorridorLinkBlock': '3', 'CorridorLinkActive': '1',
         'CorridorLinkEnablerGroup': '12', 'BroadcastBlock': '5', 'IndicatorControl': '2', 'BroadcastActive': '3',
         'PECEnablerGroup': '9', 'SingleJoinEnablerGroup': '10', 'DualJoinEnablerGroup': '11',
         'SingleJoinEnablerControlGroup': '13', 'DualJoinEnablerControlGroup': '14', 'ControlAppGroupAddress': '15',
         'SceneKeySelector': '1 1 1 1 1 1 1 1', 'IndicatorBlockAssignment': '7 3 3 3 3 3 3 3',
         'PECFunctionBlock': '4', 'PECFunctionActive': '1', 'PECFunctionIRKey': '4', 'PECFunctionIRActive': '1',
         'PIRFunctionIRKey': '4', 'PIRFunctionIRActive': '1', 'PECLevelStore': '1', 'PECEnablerGroupLogic': '1',
         'PotentiometerAFunction': '2', 'PotentiometerBFunction': '1', 'PotentiometerATimerBlock': '3',
         'PotentiometerBTimerBlock': '3', 'PotentiometerBBankSwitchEnable': '1', 'PECTargetLux': '50',
         'PECMarginLux': '59', 'PIRLevelStore': '0', 'PIREnablerGroupLogic': '0', 'LightLevel': '1 2 3 4 5 6 7 8 9 10', 'JPCommand': '7 13 13 5 5 5 5 5'}


@unittest.skipUnless(native_backend() and os.environ.get('CBUS_UNITSPEC_DIR'), 'Select native C-Gate and unit specs for PIR acceptance')
class PIRSensorNativeTest(unittest.TestCase):
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

    def exercise(self, client, network, address, unit_type, firmware, catalog, report):
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        reason, spec_name = profile(unit_type, firmware, catalog)
        self.assertIsNone(reason)
        sensor = PIRSensor(self.store.load(spec_name))
        case = {'unit_type': unit_type, 'firmware': firmware, 'catalog_number': catalog, 'spec': spec_name,
                'raw_byte_assertions': 0, 'dialog_cases': 0}
        path = f'{network}/p/{address}'
        NativeDatabase(client).create_unit(network, address, 'PIR_' + str(address), unit_type, firmware, catalog_number=catalog)
        programmer = Programmer(client)
        with programmer.load(network, '/db' + path) as session:
            session.reset_defaults()
            for name, value in DIRTY.items():
                session.set(name, value)
            baseline = session.values()
            # Unchanged dialog: the Toolkit save alone.
            result = sensor.configure(session)
            self.assertEqual(result['dialog']['margin_percent'], 118)
            self.assertEqual(raw_bytes(session, 50, 3), bytes((9, 10, 4)))
            for address_, mask, expected in ((53, 0x77, 0x04), (68, 0xbf, 0), (70, 0xff, 0x80), (89, 255, 255),
                                             (90, 255, 255), (91, 255, 255), (92, 255, 255), (93, 255, 255), (94, 255, 255),
                                             (95, 255, 255), (96, 0xff, 0x07), (97, 0x7f, 0), (98, 0x7f, 0), (99, 0x28, 0),
                                             (101, 0x78, 0x08), (102, 0x38, 0), (103, 0x78, 0), (28, 255, 59)):
                self.assertEqual(raw_bytes(session, address_, 1)[0] & mask, expected, address_)
                case['raw_byte_assertions'] += 1
            self.assertEqual(raw_bytes(session, 1, 10), bytes((1, 2, 3, 4, 0, 0, 0, 0, 0, 0)))
            self.assertEqual(ints(session.values()['SceneKeySelector']), [0, 1, 1, 1, 1, 1, 1, 1])
            self.assertEqual(ints(session.values()['IndicatorBlockAssignment']), [7, 0, 0, 0, 0, 0, 0, 0])
            case['raw_byte_assertions'] += 1
            # Idempotence: a second Toolkit save of the saved state changes nothing.
            self.assertEqual(sensor.plan(session.values()).changes, {})
            case['dialog_cases'] += 1
            # Every key, group, timer and link; blocks 5..8 and keys 5..8 untouched.
            for key in KEY_EVENTS:
                result = sensor.configure(session, keys={key: {'block': key, 'group': 40 + key, 'timer_seconds': 300 + key,
                                                                'expiry': 'ramp_off'}},
                                          restore_functions=True, darkness_same_as_light=False, allow_shared_block=True)
                values = session.values()
                self.assertEqual(tuple(int(values[n].split()[key - 1], 0) for n in STAGES), EVENTS[KEY_EVENTS[key]])
                vector = EVENTS[KEY_EVENTS[key]]
                self.assertEqual(raw_bytes(session, 104 + (key - 1) * 2, 2), bytes((vector[0] << 4 | vector[1], vector[2] << 4 | vector[3])))
                self.assertEqual(raw_bytes(session, 54 + key - 1, 1)[0], 1 << (key - 1))
                self.assertEqual(raw_bytes(session, 80 + key - 1, 1)[0], 40 + key)
                self.assertEqual(raw_bytes(session, 136 + key - 1, 1)[0] * 256 + raw_bytes(session, 144 + key - 1, 1)[0], 300 + key)
                case['raw_byte_assertions'] += 5
                case['dialog_cases'] += 1
            sensor.configure(session, darkness_same_as_light=True, enable_group=23, enabled_when='off', power_up='enabled',
                             restore_functions=True)
            self.assertEqual(raw_bytes(session, 54, 2), bytes((1, 1)))
            self.assertEqual((raw_bytes(session, 88, 1)[0], raw_bytes(session, 99, 1)[0] & 0x50, raw_bytes(session, 9, 1)[0]), (23, 0x40, 0))
            case['raw_byte_assertions'] += 2
            case['dialog_cases'] += 1
            after = session.values()
            touched = set(LAYOUTS)
            unrelated = sorted(n for n in after if n not in touched)
            self.assertEqual({n: after[n] for n in unrelated}, {n: baseline[n] for n in unrelated})
            for name in STAGES + ('BlockAllocation', 'GroupAddress', 'TimerHighByte', 'TimerLowByte', 'TimerExpiryCommand'):
                self.assertEqual(after[name].split()[4:], baseline[name].split()[4:], name)
            case['unrelated_parameters_preserved'] = len(unrelated)
            expected = sensor.snapshot(after)
            session.save_to_source()
        client.command('PROJECT SAVE ' + network.split('/')[2])
        with programmer.load(network, '/db' + path) as session:
            self.assertEqual(sensor.snapshot(session.values()), expected)
            self.assertEqual(session.values(), after)
            self.assertEqual(sensor.plan(session.values()).changes, {})
        case['save_reload_passed'] = True
        report['profiles'].append(case)

    def refuse(self, client, network, address, unit_type, firmware, catalog, report):
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        sensor = PIRSensor(self.store.load('SENPIRIA_ST7.xml'))
        NativeDatabase(client).create_unit(network, address, 'Refused_' + str(address), unit_type, firmware, catalog_number=catalog)
        with Programmer(client).load(network, f'/db{network}/p/{address}') as session:
            before = session.values()
            with self.assertRaisesRegex(SensorError, 'Native session'):
                sensor.configure(session, keys={1: {'group': 31}})
            self.assertEqual(session.values(), before)
        report['refused'].append({'unit_type': unit_type, 'firmware': firmware, 'catalog_number': catalog, 'values_unchanged': True})

    def test_admitted_pir_profiles_forced_save_dialog_preservation_reload_and_refusals(self):
        from cbus_toolkit.cgate import CGateClient
        project = 'PR' + uuid4().hex[:6].upper()
        network = f'//{project}/254'
        report = {'format': 'cbus-pir-sensor-acceptance-v1', 'backend': native_backend(),
                  'scope': 'Toolkit source-recovered ST7 PIR dialog and forced save through native PP and a closed database; '
                           'no physical PIR/lux behavior', 'profiles': [], 'refused': [], 'passed': False,
                  'physical_hardware_verified': False}
        with CGateClient(self.host, self.port, timeout=30) as client:
            report['greeting'] = client.greeting
            client.command('PROJECT NEW ' + project)
            try:
                client.command('PROJECT USE ' + project)
                client.command('DBCREATENET 254 Sensor_Offline Cni 127.0.0.1:29999')
                client.command('NET LOAD DB ' + project)
                client.command('PROJECT SAVE ' + project)
                for index, identity in enumerate(NATIVE_PROFILES):
                    with self.subTest(identity=identity):
                        self.exercise(client, network, 200 + index, *identity, report)
                for index, identity in enumerate(NATIVE_REFUSED):
                    with self.subTest(identity=identity):
                        self.refuse(client, network, 230 + index, *identity, report)
                report['passed'] = len(report['profiles']) == len(NATIVE_PROFILES) and len(report['refused']) == len(NATIVE_REFUSED)
                self.assertTrue(report['passed'])
            finally:
                client.command('PROJECT CLOSE ' + project)
                try:
                    client.command('PROJECT DELETE ' + project)
                except Exception:  # noqa: BLE001 - deletion evidence is recorded, the test result stands
                    report['project_deleted'] = False
                if self.service is not None:
                    report['service'] = {k: self.service.report.get(k) for k in
                                         ('vendor_jar_sha256', 'java_version', 'listener_ownership_verified', 'listeners')}
                if os.environ.get('CBUS_PIR_SENSOR_REPORT'):
                    Path(os.environ['CBUS_PIR_SENSOR_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
