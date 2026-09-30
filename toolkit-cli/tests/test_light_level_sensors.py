"""ST7 SENLL light-level dialog/forced-save vectors, receipt checks and closed native PP tests."""
import json
import os
from pathlib import Path
import unittest
from uuid import uuid4

from cbus_toolkit.light_level_sensors import (FORCED, INDICATORS, LAYOUTS, NOT_SENT, PROFILE, LightLevelSensor,
                                              indicator_state, profile_refusal, target_byte)
from cbus_toolkit.sensors import SensorApplyError, SensorError, saved_margin
from cbus_toolkit.sensors import profile_refusal as multisensor_refusal
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore
from test_macros import Session


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / 'docs/light-level-sensor-review.json'
PROFILE_REVIEW = ROOT / 'docs/sensor-profile-review.json'
BITS = ('DisableIR', 'CorridorLinkActive', 'PECFunctionActive', 'PECFunctionIRActive', 'PIRFunctionIRActive',
        'PIRLevelStore', 'PECEnablerGroupLogic', 'PIREnablerGroupLogic', 'SceneKeySelector')
# Independent literal layout from the SENLL_ST7 PP table (address, count, bits,
# bit, skip) and a non-default "dirty" starting state for every forced field.
ROWS = {
    'JPCommand': (104, 8, 4, 4, 1, [7, 13, 13, 13, 5, 5, 5, 5]), 'SRCommand': (104, 8, 4, 0, 1, [0, 7, 15, 15, 5, 5, 5, 5]),
    'LPCommand': (105, 8, 4, 4, 1, [0, 7, 7, 0, 5, 5, 5, 5]), 'LRCommand': (105, 8, 4, 0, 1, [0, 0, 15, 15, 5, 5, 5, 5]),
    'PIRLightMovement': (50, 1, 8, 0, 0, [255]), 'PIRDarkMovement': (51, 1, 8, 0, 0, [255]), 'PIRDark': (52, 1, 8, 0, 0, [255]),
    'IRBank': (53, 1, 2, 0, 0, [3]), 'DisableIR': (53, 1, 1, 2, 0, [0]), 'IRBankKeyOffset': (53, 1, 3, 4, 0, [5]),
    'BlockAllocation': (54, 8, 8, 0, 0, [1, 2, 4, 8, 16, 32, 64, 128]),
    'GroupAddress': (80, 8, 8, 0, 0, [255, 20, 21, 255, 255, 25, 255, 255]),
    'Application': (33, 2, 8, 0, 0, [56, 255]), 'SecondApplicationBlocks': (69, 1, 8, 0, 0, [4]),
    'SceneKeySelector': (96, 8, 1, 7, 0, [1] * 8), 'IndicatorBlockAssignment': (96, 8, 3, 0, 0, [3, 3, 3, 3, 3, 3, 3, 3]),
    'RampRate': (64, 2, 8, 0, 0, [1, 3]),
    'CorridorLinkOfficeBlock': (68, 1, 3, 0, 0, [2]), 'CorridorLinkBlock': (68, 1, 3, 3, 0, [3]),
    'CorridorLinkActive': (68, 1, 1, 7, 0, [1]), 'BroadcastBlock': (70, 1, 3, 0, 0, [5]),
    'IndicatorControl': (70, 1, 2, 3, 0, [2]), 'BroadcastActive': (70, 1, 3, 5, 0, [3]),
    'PECTargetLux': (27, 1, 8, 0, 0, [250]), 'PECMarginLux': (28, 1, 8, 0, 0, [59]),
    'LightLevel': (1, 10, 8, 0, 0, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]),
    'PIREnablerGroup': (88, 1, 8, 0, 0, [8]), 'PECEnablerGroup': (89, 1, 8, 0, 0, [9]),
    'SingleJoinEnablerGroup': (90, 1, 8, 0, 0, [10]), 'DualJoinEnablerGroup': (91, 1, 8, 0, 0, [11]),
    'CorridorLinkEnablerGroup': (92, 1, 8, 0, 0, [12]), 'SingleJoinEnablerControlGroup': (93, 1, 8, 0, 0, [13]),
    'DualJoinEnablerControlGroup': (94, 1, 8, 0, 0, [14]), 'ControlAppGroupAddress': (95, 1, 8, 0, 0, [15]),
    'PECFunctionBlock': (96, 1, 3, 3, 0, [4]), 'PECFunctionActive': (96, 1, 1, 6, 0, [0]),
    'PECFunctionIRKey': (97, 1, 3, 3, 0, [4]), 'PECFunctionIRActive': (97, 1, 1, 6, 0, [1]),
    'PIRFunctionIRKey': (98, 1, 3, 3, 0, [4]), 'PIRFunctionIRActive': (98, 1, 1, 6, 0, [1]),
    'PECLevelStore': (99, 1, 1, 3, 0, [1]), 'PIRLevelStore': (99, 1, 1, 4, 0, [1]),
    'PECEnablerGroupLogic': (99, 1, 1, 5, 0, [1]), 'PIREnablerGroupLogic': (99, 1, 1, 6, 0, [1]),
    'PotentiometerAFunction': (101, 1, 2, 3, 0, [2]), 'PotentiometerBFunction': (101, 1, 2, 5, 0, [1]),
    'PotentiometerATimerBlock': (102, 1, 3, 3, 0, [3]), 'PotentiometerBTimerBlock': (103, 1, 3, 3, 0, [3]),
    'PotentiometerBBankSwitchEnable': (103, 1, 1, 6, 0, [1]),
    'TimerHighByte': (136, 8, 8, 0, 0, [1] * 8), 'TimerLowByte': (144, 8, 8, 0, 0, [44] * 8),
}


def fixture(filename='SENLL_ST7.xml'):
    parameters = {}
    for name, (address, count, bits, bit, skip, values) in ROWS.items():
        kind = 'bit' if name in BITS else 'int'
        fields = {'Name': name, 'Type': kind, 'Address': str(address), 'ArraySize': str(count), 'BitSize': str(bits),
                  'BitAddress': str(bit), 'ArraySkip': str(skip), 'DefaultValue': ' '.join(map(str, values))}
        parameters[name] = ParameterSpec(name, kind, 'literal-senll-fixture.xml', fields)
    # SENLL_ST7.xml declares the SENPILL type, like the vendor file.
    return UnitSpec(filename, {'Type': 'SENPILL'}, ('literal-senll-fixture.xml',), parameters)


def ints(value):
    return [int(v, 0) for v in value.split()]


class LightLevelSaveModelTest(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.sensor = LightLevelSensor(self.spec)

    def session(self, **values):
        session = Session(self.spec)
        session.unit_type, session.firmware, session.catalog_number = 'SENLL', '2.3.00', '5031PE'
        session.current.update({k: ' '.join(map(str, v)) for k, v in values.items()})
        return session

    def test_unchanged_dialog_save_forces_and_normalizes_exactly(self):
        session = self.session()
        result = self.sensor.configure(session)
        values = {name: ints(value) for name, value in session.current.items()}
        for name, value in FORCED.items():
            self.assertEqual(values[name], [value], name)
        # Literal PrepareForcedParameters vector, independent of FORCED.
        self.assertEqual((values['PIRLightMovement'], values['PIRDarkMovement'], values['PIRDark']), ([0], [0], [0]))
        self.assertEqual((values['BroadcastBlock'], values['PECFunctionBlock'], values['PECFunctionActive']), ([4], [1], [1]))
        self.assertEqual((values['PIREnablerGroup'], values['PotentiometerAFunction'], values['DisableIR']), ([255], [0], [1]))
        self.assertEqual(values['RampRate'], [7, 7])
        self.assertEqual(values['LightLevel'], [1, 2, 3, 4, 5, 6, 7, 8, 0, 10])
        # Block 5 has no group: broadcast inactive. Indicator 3 loads as the level LED.
        self.assertEqual(values['BroadcastActive'], [0])
        self.assertEqual(values['IndicatorBlockAssignment'], [1, 0, 0, 0, 0, 0, 0, 0])
        # Target 250 loads clamped to 200; 59/250 -> 24%; 200 * ext(0.24) -> 48.
        self.assertEqual((values['PECTargetLux'], values['PECMarginLux']), ([200], [48]))
        # No application 2: the dialog drops block 3's secondary application.
        self.assertEqual(values['SecondApplicationBlocks'], [0])
        # Attributes the agent marks non-programmable, and fields it leaves alone.
        for name in NOT_SENT[:5] + ('SceneKeySelector', 'IRBank', 'IndicatorControl', 'ControlAppGroupAddress',
                                    'PECEnablerGroup', 'PECLevelStore', 'GroupAddress', 'TimerLowByte'):
            if name in ROWS:
                self.assertEqual(values[name], ROWS[name][-1], name)
        self.assertEqual(result['dialog'], {'indicator': 'light_level', 'target_lux': 2000, 'target_clamped': True,
                                            'margin_percent': 24, 'on_off_application': 'primary',
                                            'secondary_application_available': False})
        self.assertFalse(result['saved'])
        self.assertEqual(self.sensor.plan(session.values()).changes, {})

    def test_indicator_broadcast_and_target_controls(self):
        self.assertEqual([indicator_state(v) for v in range(8)],
                         ['light_level', 'light_level', 'on_off', 'light_level', 'light_level', 'enable',
                          'light_level', 'light_level'])
        for indicator, code in (('light_level', 1), ('on_off', 2), ('enable', 5)):
            session = self.session()
            self.sensor.configure(session, indicator=indicator)
            self.assertEqual(ints(session.current['IndicatorBlockAssignment']), [code] + [0] * 7)
            self.assertEqual(self.sensor.plan(session.values()).dialog['indicator'], indicator)
        session = self.session()
        self.sensor.configure(session, broadcast_group=30)
        self.assertEqual((ints(session.current['GroupAddress'])[4], ints(session.current['BroadcastActive'])), (30, [1]))
        self.sensor.configure(session, broadcast_group=255)
        self.assertEqual(ints(session.current['BroadcastActive']), [0])
        # Lux2550ToByte is Ceil(lux / 10); the dialog accepts up to 2000 lux.
        self.assertEqual([target_byte(v) for v in (0, 1, 10, 455, 1991, 2000)], [0, 1, 1, 46, 200, 200])
        session = self.session()
        result = self.sensor.configure(session, target_lux=500, margin_percent=59)
        self.assertEqual((ints(session.current['PECTargetLux']), ints(session.current['PECMarginLux'])), ([50], [29]))
        self.assertEqual(result['dialog']['margin_percent'], 59)
        # Editing only the target keeps the loaded percentage.
        session = self.session(PECTargetLux=[100], PECMarginLux=[10])
        self.sensor.configure(session, target_lux=1500)
        self.assertEqual((ints(session.current['PECTargetLux']), ints(session.current['PECMarginLux'])),
                         ([150], [saved_margin(150, 10)]))
        with self.assertRaisesRegex(SensorError, 'native margin byte'):
            self.sensor.plan(self.session(PECTargetLux=[1], PECMarginLux=[255]).values(), target_lux=1500)

    def test_groups_application_and_combo_exclusions(self):
        current = self.session().values()
        plan = self.sensor.plan(current, level_group=40, on_off_group=41, enable_group=42)
        self.assertEqual(plan.changes['GroupAddress'], (255, 40, 41, 255, 255, 25, 255, 255))
        self.assertEqual(plan.changes['PECEnablerGroup'], (42,))
        # A combo omits groups used by another block or the enable group.
        for options in ({'level_group': 21}, {'level_group': 25}, {'on_off_group': 9}, {'broadcast_group': 20},
                        {'enable_group': 25}, {'level_group': 50, 'on_off_group': 50}):
            with self.subTest(options=options), self.assertRaisesRegex(SensorError, 'already used'):
                self.sensor.plan(current, **options)
        # Its own current group and 255 are always listed.
        self.assertNotIn('GroupAddress', self.sensor.plan(current, level_group=20).changes)
        self.assertEqual(self.sensor.plan(current, on_off_group=255).changes['GroupAddress'][2], 255)
        # The secondary application needs application 2 and separates group objects.
        with self.assertRaisesRegex(SensorError, 'secondary application'):
            self.sensor.plan(current, on_off_application='secondary')
        session = self.session(Application=[56, 57])
        plan = self.sensor.plan(session.values())
        self.assertEqual(plan.dialog['on_off_application'], 'secondary')
        self.assertNotIn('SecondApplicationBlocks', plan.changes)
        plan = self.sensor.plan(session.values(), on_off_group=20)
        self.assertEqual(plan.changes['GroupAddress'][2], 20)
        plan = self.sensor.plan(session.values(), on_off_application='primary')
        self.assertEqual(plan.changes['SecondApplicationBlocks'], (0,))
        with self.assertRaisesRegex(SensorError, 'already used'):
            self.sensor.plan(session.values(), on_off_application='primary', on_off_group=20)

    def test_refusals_and_bounds(self):
        current = self.session().values()
        for options, pattern in (({'level_group': 256}, '0..255'), ({'level_group': True}, '0..255'),
                                 ({'indicator': 'status'}, 'indicator'), ({'on_off_application': 'app2'}, 'primary'),
                                 ({'target_lux': 2001}, '0..2000'), ({'target_lux': -1}, '0..2000'),
                                 ({'margin_percent': 101}, '0..100'), ({'enable_group': 256}, '0..255'),
                                 ({'identity': ('SENLL', '2.5.00', '5031PE')}, 'SENLL_ST7 catalogue band'),
                                 ({'identity': ('SENLL', '2.3.00', '5754PE')}, 'catalogue number')):
            with self.subTest(options=options), self.assertRaisesRegex(SensorError, pattern):
                self.sensor.plan(current, **options)
        session = self.session(Application=[255, 255])
        with self.assertRaisesRegex(SensorError, 'application'):
            self.sensor.plan(session.values(), level_group=3)
        with self.assertRaises(SensorError):
            LightLevelSensor(fixture('SENPILL_ST7.xml'))

    def test_apply_profile_staleness_preservation_and_partial_failure(self):
        session = self.session()
        session.current['Other'] = 'unchanged'
        plan = self.sensor.plan(session.values(), level_group=19)
        self.assertTrue(self.sensor.apply(session, plan)['verified'])
        self.assertEqual(session.current['Other'], 'unchanged')
        self.assertFalse(any(name in NOT_SENT for name, _ in session.calls))
        with self.assertRaisesRegex(SensorError, 'changed since'):
            self.sensor.apply(session, plan)
        for field, value in (('firmware', '2.5.00'), ('firmware', '2.0.00'), ('catalog_number', '5754PE'),
                             ('unit_type', 'SENPILL'), ('unit_type', 'SENLLA')):
            session = self.session()
            setattr(session, field, value)
            with self.assertRaisesRegex(SensorError, 'Native session'):
                self.sensor.apply(session, plan)
            self.assertEqual(session.calls, [])
        session = self.session()
        session.failure = 'GroupAddress'
        plan = self.sensor.plan(session.values(), level_group=19)
        with self.assertRaises(SensorApplyError) as error:
            self.sensor.apply(session, plan)
        self.assertEqual(error.exception.attempted[-1], 'GroupAddress')
        self.assertEqual(sum(name == 'GroupAddress' for name, _ in session.calls), 1)


class LightLevelProfileTest(unittest.TestCase):
    def test_catalogue_decisions_and_registration_boundaries(self):
        review = json.loads(PROFILE_REVIEW.read_text())
        seen = set()
        for row in review['decisions']:
            if 'firmware_min' not in row:
                continue
            admitted = row['unit_type'] == 'SENLL' and row['toolkit_class'] == 'TST7SENLL' \
                and row['spec'] == PROFILE['spec_filename']
            for version in (row['firmware_min'], row['firmware_max']):
                with self.subTest(row=row, version=version):
                    self.assertEqual(profile_refusal(row['unit_type'], version, row['catalog_number']) is None, admitted)
                    if admitted:
                        seen.add(row['catalog_number'])
        self.assertEqual(seen, set(PROFILE['catalog_numbers']))
        for identity, pattern in ((('SENLL', '1.2.68', '5031PE'), 'TSENLL'), (('SENLL', '2.0.00', '5031PE'), 'no Toolkit'),
                                  (('SENLL', '2.5.00', '5031PE'), 'no Toolkit'), (('SENLLA', '2.4.00', '5754PE'), 'TSENLLA'),
                                  (('SENPILL', '2.3.00', '5753PEIRL'), 'Only SENLL'), (('SENLL', '2.3.00', '5753L'), 'catalogue')):
            with self.subTest(identity=identity):
                self.assertRegex(profile_refusal(*identity), pattern)
        self.assertIn('light_level_sensors', multisensor_refusal('SENLL', '2.3.00', '5031PE'))


class LightLevelReviewTest(unittest.TestCase):
    def setUp(self):
        self.review = json.loads(REVIEW.read_text())

    def test_receipt_is_sanitized_and_matches_the_model(self):
        text = REVIEW.read_text()
        for private in ('<Param', 'DefaultValue', 'CLIPSAL', 'Light Level Sensor', 'Define Broadcast'):
            self.assertNotIn(private, text)
        self.assertFalse(self.review['original_execution'])
        writes = self.review['save']['prepare_forced_parameters']['writes']
        scalar = {w['parameter']: w['value'] for w in writes if w.get('write') == 'SetValue'}
        self.assertEqual(scalar, {k: v for k, v in FORCED.items() if k != 'PotentiometerBBankSwitchEnable'})
        self.assertEqual([w['value'] for w in writes if w['parameter'] == 'RampRate'], [[7, 7]])
        self.assertEqual([(w['index'], w['value']) for w in writes if w['parameter'] == 'LightLevel'], [(8, 0)])
        self.assertEqual([w['parameter'] for w in writes if w.get('programmable') is False], list(NOT_SENT))
        tail = self.review['save']['light_level_before_save']
        self.assertEqual(tail['broadcast_active'], {'block_index': 4, 'group_unused': 0, 'group_used': 1})
        radio = self.review['dialog']['indicator_radio_unit_flag']
        codes = {row['unit_flag']: row['value'] for row in tail['indicator_block_assignment']}
        self.assertEqual({flag: codes[flag] for flag in radio.values()},
                         {flag: [INDICATORS[name]] + [0] * 7 for flag, name in
                          zip(radio.values(), ('light_level', 'on_off', 'enable'))})
        loaded = {row['IndicatorBlockAssignment[0]']: row['unit_flag'] for row in tail['indicator_loaded']}
        self.assertEqual(loaded, {5: 2, 2: 1, None: 0})
        bindings = {row['control']: row['expression'] for row in self.review['dialog']['bindings']}
        self.assertEqual(bindings, {'cmbLightLevel': 'Blocks[1].Group', 'cmbLightOnOff': 'Blocks[2].Group',
                                    'cmbBroadcastGroup': 'Blocks[4].Group', 'cmbEnableGroup': 'LightLevelMaintEnableGroup',
                                    'trkTargetLux': 'LightLevelTargetLux', 'trkMargin': 'LightLevelMarginPerc'})
        target = self.review['dialog']['target']
        self.assertEqual((target['edit_text_byte_clamp'], target['entered_lux_clamp']), (200, 2000))
        self.assertEqual(self.review['dialog']['on_off_application_switch']['block_index'], 2)
        unit = self.review['unit']
        self.assertEqual((unit['MaximumKeyCount'], unit['IsJoinModeSupported'], unit['HasApplication2']), (0, False, True))
        self.assertTrue(set(FORCED) <= set(LAYOUTS))
        self.assertFalse(set(NOT_SENT) & set(LAYOUTS))

    @unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'Set the Toolkit EXE to regenerate the SENLL receipt')
    def test_receipt_regenerates_from_private_inputs(self):
        from research.light_level_sensor_review import review
        exe = Path(os.environ['CBUS_TOOLKIT_EXE'])
        self.assertEqual(json.loads(json.dumps(review(exe, exe.with_suffix('.map')))), self.review)


def native_backend():
    if os.environ.get('CBUS_NATIVE_SERVICE_BACKEND') == 'local':
        return 'local' if os.environ.get('CBUS_LOCAL_CGATE_VENDOR') and os.environ.get('CBUS_CGATE_JAVA') else None
    return 'host' if os.environ.get('CBUS_CGATE_TEST_HOST') else None


def raw_bytes(session, address, count):
    return bytes.fromhex(session.get_raw_data(address, count).lines[-1].split('RawData=', 1)[1])


# One profile per catalogue band, covering all four catalogue numbers and both band edges.
NATIVE_PROFILES = (('SENLL', '2.0.01', '5031PE'), ('SENLL', '2.1.00', 'SLC5031PE'), ('SENLL', '2.2.99', '5031PEWP'),
                   ('SENLL', '2.3.00', 'SLC5031PEWP,GY'), ('SENLL', '2.4.99', '5031PE'))
# C-Gate has no specification for SENLL 2.0.00 or 2.5.00, so those gaps are offline-only.
NATIVE_REFUSED = (('SENLL', '1.2.68', '5031PE'), ('SENLL', '1.9.99', '5031PEWP'), ('SENLL', '2.3.00', '5754PE'),
                  ('SENLLA', '2.4.00', '5754PE'), ('SENPILL', '2.3.00', '5753PEIRL'), ('SENPIRIA', '2.3.00', '5751L'))
# A dirty baseline that the Toolkit save must overwrite, normalize or preserve.
DIRTY = {'PIRLightMovement': '255', 'PIRDarkMovement': '255', 'PIRDark': '255', 'IRBank': '3', 'DisableIR': '0',
         'IRBankKeyOffset': '5', 'CorridorLinkOfficeBlock': '2', 'CorridorLinkBlock': '3', 'CorridorLinkActive': '1',
         'CorridorLinkEnablerGroup': '12', 'BroadcastBlock': '5', 'IndicatorControl': '2', 'BroadcastActive': '3',
         'PIREnablerGroup': '8', 'PECEnablerGroup': '9', 'SingleJoinEnablerGroup': '10', 'DualJoinEnablerGroup': '11',
         'SingleJoinEnablerControlGroup': '13', 'DualJoinEnablerControlGroup': '14', 'ControlAppGroupAddress': '15',
         'SceneKeySelector': '1 1 1 1 1 1 1 1', 'IndicatorBlockAssignment': '3 3 3 3 3 3 3 3',
         'PECFunctionBlock': '4', 'PECFunctionActive': '0', 'PECFunctionIRKey': '4', 'PECFunctionIRActive': '1',
         'PIRFunctionIRKey': '4', 'PIRFunctionIRActive': '1', 'PECLevelStore': '1', 'PIRLevelStore': '1',
         'PECEnablerGroupLogic': '1', 'PIREnablerGroupLogic': '1', 'PotentiometerAFunction': '2',
         'PotentiometerBFunction': '1', 'PotentiometerATimerBlock': '3', 'PotentiometerBTimerBlock': '3',
         'PotentiometerBBankSwitchEnable': '1', 'PECTargetLux': '250', 'PECMarginLux': '59', 'RampRate': '1 3',
         'LightLevel': '1 2 3 4 5 6 7 8 9 10', 'JPCommand': '7 13 13 5 5 5 5 5', 'BlockAllocation': '1 2 4 8 16 32 64 128',
         'GroupAddress': '255 20 21 255 255 25 255 255', 'SecondApplicationBlocks': '4', 'Application': '56 255'}


@unittest.skipUnless(native_backend() and os.environ.get('CBUS_UNITSPEC_DIR'), 'Select native C-Gate and unit specs for SENLL acceptance')
class LightLevelSensorNativeTest(unittest.TestCase):
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
        cls.sensor = LightLevelSensor(UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR']).load(PROFILE['spec_filename']))

    def exercise(self, client, network, address, unit_type, firmware, catalog, report):
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        self.assertIsNone(profile_refusal(unit_type, firmware, catalog))
        sensor = self.sensor
        case = {'unit_type': unit_type, 'firmware': firmware, 'catalog_number': catalog,
                'raw_byte_assertions': 0, 'dialog_cases': 0}
        path = f'{network}/p/{address}'
        NativeDatabase(client).create_unit(network, address, 'SENLL_' + str(address), unit_type, firmware, catalog_number=catalog)
        programmer = Programmer(client)
        with programmer.load(network, '/db' + path) as session:
            session.reset_defaults()
            for name, value in DIRTY.items():
                session.set(name, value)
            baseline = session.values()
            raw_baseline = raw_bytes(session, 96, 8)
            # Unchanged dialog: the Toolkit save alone.
            result = sensor.configure(session)
            self.assertEqual((result['dialog']['margin_percent'], result['dialog']['target_lux']), (24, 2000))
            self.assertEqual(raw_bytes(session, 50, 3), bytes(3))
            self.assertEqual(raw_bytes(session, 64, 2), bytes((7, 7)))
            self.assertEqual(raw_bytes(session, 27, 2), bytes((200, 48)))
            self.assertEqual(raw_bytes(session, 1, 10), bytes((1, 2, 3, 4, 5, 6, 7, 8, 0, 10)))
            self.assertEqual(raw_bytes(session, 88, 8), bytes((255, 9, 255, 255, 255, 255, 255, 15)))
            self.assertEqual(raw_bytes(session, 69, 1)[0], 0)
            case['raw_byte_assertions'] += 6
            for address_, mask, expected in ((53, 0x77, 0x07), (68, 0xbf, 0), (70, 0xff, 0x14), (97, 0x78, 0),
                                             (98, 0x78, 0), (99, 0x78, 0x08), (101, 0x78, 0), (102, 0x38, 0),
                                             (103, 0x78, 0)):
                self.assertEqual(raw_bytes(session, address_, 1)[0] & mask, expected, address_)
                case['raw_byte_assertions'] += 1
            # Byte 96: IndicatorBlockAssignment[0]=1, PECFunctionBlock=1, PECFunctionActive=1;
            # SceneKeySelector bit 7 is never sent. Bytes 97..103 keep bit 7 too.
            block = raw_bytes(session, 96, 8)
            self.assertEqual(block[0], 0x80 | 0x40 | 0x08 | 1)
            self.assertEqual([b & 0x87 for b in block[1:]], [0x80] * 7)
            self.assertEqual([b & 0x80 for b in block], [b & 0x80 for b in raw_baseline])
            case['raw_byte_assertions'] += 3
            self.assertEqual(sensor.plan(session.values()).changes, {})
            case['dialog_cases'] += 1
            # Every indicator state, the three group combos, enable group and target/margin.
            for indicator, code in (('on_off', 2), ('enable', 5), ('light_level', 1)):
                sensor.configure(session, indicator=indicator)
                self.assertEqual(raw_bytes(session, 96, 1)[0] & 7, code)
                case['raw_byte_assertions'] += 1
                case['dialog_cases'] += 1
            sensor.configure(session, level_group=40, on_off_group=41, broadcast_group=42, enable_group=43,
                             target_lux=455, margin_percent=59)
            self.assertEqual(raw_bytes(session, 80, 5), bytes((255, 40, 41, 255, 42)))
            self.assertEqual((raw_bytes(session, 89, 1)[0], raw_bytes(session, 70, 1)[0] >> 5), (43, 1))
            self.assertEqual(raw_bytes(session, 27, 2), bytes((46, saved_margin(46, 59))))
            case['raw_byte_assertions'] += 3
            case['dialog_cases'] += 1
            # 500 lux at 59%: the original x87 margin is 29, not the exact-rounded 30.
            sensor.configure(session, target_lux=500, margin_percent=59, broadcast_group=255)
            self.assertEqual((raw_bytes(session, 27, 2), raw_bytes(session, 70, 1)[0] >> 5), (bytes((50, 29)), 0))
            case['raw_byte_assertions'] += 1
            case['dialog_cases'] += 1
            # Application 2 enables the on/off group's secondary application.
            session.set('Application', '56 57')
            sensor.configure(session, on_off_application='secondary')
            self.assertEqual(raw_bytes(session, 69, 1)[0], 4)
            sensor.configure(session, on_off_application='primary')
            self.assertEqual(raw_bytes(session, 69, 1)[0], 0)
            case['raw_byte_assertions'] += 2
            case['dialog_cases'] += 2
            after = session.values()
            unrelated = sorted(n for n in after if n not in LAYOUTS and n != 'Application')
            self.assertEqual({n: after[n] for n in unrelated}, {n: baseline[n] for n in unrelated})
            for name in NOT_SENT:  # IndicatorFunction and PrimaryColour are absent from SENLL_ST7.
                self.assertEqual(after.get(name), baseline.get(name), name)
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
        NativeDatabase(client).create_unit(network, address, 'Refused_' + str(address), unit_type, firmware, catalog_number=catalog)
        with Programmer(client).load(network, f'/db{network}/p/{address}') as session:
            before = session.values()
            with self.assertRaisesRegex(SensorError, 'Native session'):
                self.sensor.configure(session, level_group=31)
            self.assertEqual(session.values(), before)
        report['refused'].append({'unit_type': unit_type, 'firmware': firmware, 'catalog_number': catalog, 'values_unchanged': True})

    def test_admitted_senll_profiles_forced_save_dialog_preservation_reload_and_refusals(self):
        from cbus_toolkit.cgate import CGateClient
        project = 'LL' + uuid4().hex[:6].upper()
        network = f'//{project}/254'
        report = {'format': 'cbus-light-level-sensor-acceptance-v1', 'backend': native_backend(),
                  'scope': 'Toolkit source-recovered ST7 SENLL dialog and forced save through native PP and a closed '
                           'database; no physical light-level behavior', 'profiles': [], 'refused': [], 'passed': False,
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
                if os.environ.get('CBUS_LIGHT_LEVEL_SENSOR_REPORT'):
                    Path(os.environ['CBUS_LIGHT_LEVEL_SENSOR_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
