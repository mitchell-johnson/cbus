"""Independent literal tests for the five classic coupler/auxiliary conversions.

The admitted source is 1.2.67; the fresh CouplerPro target is 2.2.00. These
portable tests do not execute Toolkit, C-Gate, or hardware.
"""
from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import Mock

from cbus_toolkit import toolkit_conversion_tweakers as tweakers
from cbus_toolkit.toolkit_conversion_coupler_to_neo import (
    COUPLER_ATTRIBUTES, COUPLER_SOURCE_TYPES, COUPLER_TARGET_TYPES,
)
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec


PAIRS = (
    ('KEYBC2', 'BCN2B'), ('KEYBC2', 'BCN4B'), ('KEYBC4', 'BCN2B'),
    ('KEYBC4', 'BCN4B'), ('DINAUX4', 'BCI4A'),
)
SOURCE_GROUPS = '255 0 165 254 17 33 66 99'
EXPECTED_GROUPS = '0xFF 0x00 0xA5 0xFE 0xFF 0xFF 0xFF 0xFF 0x11'
SOURCE_INDICATORS = '3 2 1 0'
EXPECTED_INDICATORS = '1 2 2 0 '
CLASSIC_NAMES = (
    'Application', 'FirmwareVersion', 'Project', 'SerialNo', 'State', 'UnitAddress', 'UnitName',
    'UnitType', 'LearnAnyApp', 'LearnMode', 'LearnedFlag', 'AreaGroupAddress', 'StatusReportInterval',
    'GroupAddress', 'DebounceTime', 'IndicatorBrightness', 'LongPressTime', 'EEPROMLevelStore',
    'LightIndex', 'LightLevel', 'LightLevelStore1', 'LightLevelStore2', 'RampRate', 'InfraRedBank',
    'JPCommand', 'SRCommand', 'LPCommand', 'LRCommand', 'BlockAllocation', 'IndicatorBlockAssignment',
    'IndicatorFunction', 'TimerHighByte', 'TimerLowByte', 'TimerExpiryCommand', 'GAVBroadcastFlag',
)
COUPLER_ADDITIONS = (
    'ControlAppGroupAddress', 'EnableNightlight', 'EnableNightlightControl', 'DisableTimerFlash',
    'FirstKeyThrowAway', 'IndicatorPressedLevel', 'TimerDuration', 'PatchEnable', 'SceneKeySelector',
    'SceneTable', 'SceneTablePointer', 'DisableIR', 'IDBacklightIllumination', 'EnableNightlightOnPCx',
    'EnableNightlightOnPA6', 'PrimaryColour', 'DisableIRNEC', 'KeyDisableGroup', 'KeyDisableGroupInvert',
    'CorridorLinkEnable', 'CorridorMasterGroup', 'CorridorGroupBlock', 'CorridorOfficeGroupBlock',
    'JoinPrimaryApplication', 'JoinSecondaryApplication', 'DualJoinPrimaryApplication',
    'DualJoinSecondaryApplication', 'SecondApplicationBlocks', 'BistableSwitchBlock', 'GroupAssertOnPowerup',
)


def source_values():
    # IndicatorBrightness is intentionally absent from the real source profile.
    return {
        'Application': '0x38 0xff', 'FirmwareVersion': '0x01 0x02 0x43',
        'Project': 'SYNTH', 'SerialNo': '1 2 3 4', 'State': '3',
        'UnitAddress': '0x14', 'UnitName': 'COUPLER', 'UnitType': 'KEYBC4',
        'GroupAddress': SOURCE_GROUPS, 'IndicatorFunction': SOURCE_INDICATORS,
        'LearnAnyApp': '1', 'LearnMode': '1', 'LearnedFlag': '0',
        'DebounceTime': '0x1f', 'LongPressTime': '19',
        'JPCommand': '13 0 15 1', 'GAVBroadcastFlag': '1',
    }


def plan_for(source=None, *, source_type='KEYBC4', target_type='BCN4B', target_parameters=None):
    source = source_values() if source is None else source
    parameters = set(source) | {'IndicatorBrightness'} if target_parameters is None else target_parameters
    return tweakers.plan_writes(source_type, target_type, source, parameters, target_firmware='2.2.00')


def written(plan):
    return {name: value for name, value, _origin in plan.writes}


def synthetic_spec(unit_type, *, source):
    """Minimal independently observed native PP shapes, including BCI4A alias."""
    schema_type = 'BCN4B' if unit_type == 'BCI4A' else unit_type
    filename = schema_type + '.xml'
    shapes = {
        'Application': ('int', 2, 8), 'GroupAddress': ('int', 8 if source else 9, 8),
        'IndicatorFunction': ('int', 4 if source else 8, 2),
        'LearnAnyApp': ('bit', 1, 8), 'LearnMode': ('bit', 1, 8), 'LearnedFlag': ('bit', 1, 8),
    }
    if not source:
        shapes.update({name: ('int', 1, 8) for name in
                       ('IndicatorBrightness', 'BistableSwitchBlock', 'GroupAssertOnPowerup')})
    firmware = '1.2.67' if source else '2.2.00'
    return UnitSpec(filename, {'Type': schema_type, 'MinVersion': firmware, 'MaxVersion': firmware},
                    (filename,), {
                        name: ParameterSpec(name, kind, filename, {'ArraySize': str(size), 'BitSize': str(bits)})
                        for name, (kind, size, bits) in shapes.items()
                    })


class NoIO:
    def command(self, *_args, **_kwargs):
        raise AssertionError('validation must fail before C-Gate I/O')

    command_document = command


class CouplerModelTests(unittest.TestCase):
    def test_source_and_coupler_constructor_inventories_follow_independent_original_order(self):
        self.assertEqual(COUPLER_SOURCE_TYPES, ('KEYBC2', 'KEYBC4', 'DINAUX4'))
        self.assertEqual(COUPLER_TARGET_TYPES, ('BCN2B', 'BCN4B', 'BCI4A'))
        immutable = {'FirmwareVersion', 'SerialNo', 'State', 'UnitType', 'IndicatorBrightness', 'GAVBroadcastFlag'}
        source_attributes = tuple((name, name not in immutable) for name in CLASSIC_NAMES)
        target_names = tuple('IRBank' if name == 'InfraRedBank' else name for name in CLASSIC_NAMES[:-1])
        target_attributes = tuple((name, name not in immutable) for name in target_names + COUPLER_ADDITIONS)
        self.assertEqual(len(source_attributes), 35)
        self.assertEqual(len(target_attributes), 64)
        self.assertEqual(COUPLER_ATTRIBUTES, target_attributes)
        for source_type in ('KEYBC2', 'KEYBC4', 'DINAUX4'):
            with self.subTest(source=source_type):
                self.assertEqual(tweakers.AGENT_ATTRIBUTES[source_type], source_attributes)
        for target_type in ('BCN2B', 'BCN4B', 'BCI4A'):
            with self.subTest(target=target_type):
                self.assertEqual(tweakers.AGENT_ATTRIBUTES[target_type], target_attributes)
                self.assertNotIn('NightlightColour', dict(target_attributes))
                self.assertNotIn('RetardationIndex', dict(target_attributes))

    def test_five_registered_pairs_use_exact_literal_group_and_indicator_vectors(self):
        for source_type, target_type in PAIRS:
            with self.subTest(source=source_type, target=target_type):
                self.assertEqual(tweakers.admitted(source_type.lower(), target_type.lower()), 'TTweakerKeyToNeo')
                plan = plan_for(source_type=source_type, target_type=target_type)
                self.assertEqual(written(plan)['GroupAddress'], EXPECTED_GROUPS)
                self.assertEqual(written(plan)['IndicatorFunction'], EXPECTED_INDICATORS)
                self.assertEqual(plan.model_context['source_firmware'], '1.2.67')
                self.assertEqual(plan.model_context['target_firmware'], '2.2.00')
                self.assertTrue(plan.model_context['fresh_target_model'])

    def test_boundary_and_hexadecimal_vectors_are_independent_literals(self):
        for groups, indicators, expected_groups, expected_indicators in (
            ('0 0 0 0 0 0 0 0', '0 1 2 3',
             '0x00 0x00 0x00 0x00 0xFF 0xFF 0xFF 0xFF 0x00', '0 2 2 1 '),
            ('255 255 255 255 255 255 255 255', '3 3 3 3',
             '0xFF 0xFF 0xFF 0xFF 0xFF 0xFF 0xFF 0xFF 0xFF', '1 1 1 1 '),
            ('$ff 0x00 $a5 0xfe $11 0x21 $42 0x63', '$03 0x02 $01 0x00',
             '0xFF 0x00 0xA5 0xFE 0xFF 0xFF 0xFF 0xFF 0x11', '1 2 2 0 '),
        ):
            with self.subTest(groups=groups, indicators=indicators):
                result = written(plan_for({**source_values(), 'GroupAddress': groups, 'IndicatorFunction': indicators}))
                self.assertEqual(result['GroupAddress'], expected_groups)
                self.assertEqual(result['IndicatorFunction'], expected_indicators)

    def test_source_without_brightness_copies_same_named_attributes_in_constructor_order(self):
        values = source_values()
        before = deepcopy(values)
        plan = plan_for(values)
        self.assertEqual(values, before)
        self.assertEqual([name for name, _value, _origin in plan.writes], [
            'Application', 'Project', 'UnitAddress', 'UnitName', 'LearnAnyApp', 'LearnMode',
            'GroupAddress', 'DebounceTime', 'LongPressTime', 'JPCommand', 'IndicatorFunction',
        ])
        for name in ('Application', 'Project', 'UnitAddress', 'UnitName', 'LearnAnyApp', 'LearnMode',
                     'DebounceTime', 'LongPressTime', 'JPCommand'):
            self.assertEqual(written(plan)[name], values[name], name)
        for name in ('FirmwareVersion', 'SerialNo', 'State', 'UnitType', 'LearnedFlag',
                     'GAVBroadcastFlag', 'IndicatorBrightness'):
            self.assertNotIn(name, written(plan))

    def test_final_coupler_hook_keeps_brightness_unwritten_even_if_a_source_string_exists(self):
        for brightness in ('', '0', '173', '255'):
            with self.subTest(brightness=brightness):
                plan = plan_for({**source_values(), 'IndicatorBrightness': brightness})
                self.assertNotIn('IndicatorBrightness', written(plan))
                self.assertIn('coupler', plan.not_written['IndicatorBrightness'].lower())

    def test_native_parameter_gate_omits_absent_fields_without_changing_transforms(self):
        source = source_values()
        for missing, retained, expected in (
            ('GroupAddress', 'IndicatorFunction', EXPECTED_INDICATORS),
            ('IndicatorFunction', 'GroupAddress', EXPECTED_GROUPS),
            ('LongPressTime', 'GroupAddress', EXPECTED_GROUPS),
        ):
            with self.subTest(missing=missing):
                plan = plan_for(source, target_parameters=set(source) - {missing})
                self.assertNotIn(missing, written(plan))
                self.assertIn('no native target parameter', plan.not_written[missing])
                self.assertEqual(written(plan)[retained], expected)

    def test_native_coupler_indicator_tail_brightness_and_learned_defaults_survive(self):
        spec = synthetic_spec('BCN4B', source=False)
        defaults = {
            'Application': '56 255', 'GroupAddress': '255 255 255 255 255 255 255 255 255',
            'IndicatorFunction': '2 2 2 2 3 3 3 3', 'IndicatorBrightness': '255',
            'LearnAnyApp': '0', 'LearnMode': '0', 'LearnedFlag': '1',
            'BistableSwitchBlock': '0', 'GroupAssertOnPowerup': '0',
        }
        before = deepcopy(defaults)
        expected = tweakers.expected_values(spec, defaults, plan_for(target_parameters=set(spec.parameters)))
        self.assertEqual(expected['GroupAddress'], (255, 0, 165, 254, 255, 255, 255, 255, 17))
        self.assertEqual(expected['IndicatorFunction'], (1, 2, 2, 0, 3, 3, 3, 3))
        self.assertEqual(expected['IndicatorBrightness'], (255,))
        self.assertEqual(expected['LearnedFlag'], (1,))
        self.assertEqual(expected['LearnAnyApp'], (1,))
        self.assertEqual(expected['LearnMode'], (1,))
        self.assertEqual(expected['BistableSwitchBlock'], (0,))
        self.assertEqual(expected['GroupAssertOnPowerup'], (0,))
        self.assertEqual(defaults, before)

    def test_coupler_only_and_native_only_fields_cannot_be_injected_through_source_values(self):
        values = {**source_values(), 'BistableSwitchBlock': '255', 'GroupAssertOnPowerup': '255',
                  'RetardationIndex': '0', 'NightlightColour': '7', 'IRBank': '2'}
        plan = plan_for(values)
        for name in ('BistableSwitchBlock', 'GroupAssertOnPowerup', 'RetardationIndex', 'NightlightColour', 'IRBank'):
            self.assertNotIn(name, written(plan), name)
        for name in ('BistableSwitchBlock', 'GroupAssertOnPowerup', 'IRBank'):
            self.assertIn('no source agent attribute', plan.not_written[name])

    def test_malformed_and_partial_consumed_arrays_are_refused(self):
        for name, value in (
            ('GroupAddress', ''), ('GroupAddress', '1 2 3 4 5 6 7'),
            ('GroupAddress', '1 2 3 4 5 6 7 8 9'), ('GroupAddress', '-1 2 3 4 5 6 7 8'),
            ('GroupAddress', '256 2 3 4 5 6 7 8'), ('GroupAddress', 'oops 2 3 4 5 6 7 8'),
            ('IndicatorFunction', ''), ('IndicatorFunction', '0 1 2'),
            ('IndicatorFunction', '0 1 2 3 0'), ('IndicatorFunction', '0 1 2 4'),
            ('IndicatorFunction', '0 1 2 -1'), ('IndicatorFunction', '0 1 2 1.0'),
        ):
            with self.subTest(parameter=name, value=value):
                with self.assertRaises(tweakers.TweakerConversionError):
                    plan_for({**source_values(), name: value})


class CouplerGuardTests(unittest.TestCase):
    def test_all_five_constructors_accept_the_exact_profile_without_io(self):
        for source_type, target_type in PAIRS:
            with self.subTest(source=source_type, target=target_type):
                source_spec = synthetic_spec(source_type, source=True)
                self.assertNotIn('IndicatorBrightness', source_spec.parameters)
                converter = tweakers.ToolkitTweakerConversion(
                    NoIO(), source_type, source_spec, target_type, synthetic_spec(target_type, source=False))
                self.assertEqual(converter.tweaker, 'TTweakerKeyToNeo')

    def test_bci4a_requires_the_catalogued_bcn4b_schema_alias(self):
        valid = synthetic_spec('BCI4A', source=False)
        self.assertEqual((valid.filename, valid.unit_type), ('BCN4B.xml', 'BCN4B'))
        invalid = (
            replace(valid, filename='BCI4A.xml'),
            replace(valid, metadata={**valid.metadata, 'Type': 'BCI4A'}),
            replace(valid, filename='BCN2B.xml', metadata={**valid.metadata, 'Type': 'BCN2B'}),
        )
        for spec in invalid:
            with self.subTest(filename=spec.filename, schema_type=spec.unit_type):
                with self.assertRaises(tweakers.TweakerConversionError):
                    tweakers.ToolkitTweakerConversion(
                        NoIO(), 'DINAUX4', synthetic_spec('DINAUX4', source=True), 'BCI4A', spec)

    def test_key_and_coupler_firmware_profiles_are_not_interchangeable(self):
        for firmware in (None, '', '2.1.00', '2.2.0', '2.2.01', '2.5.00'):
            with self.subTest(firmware=firmware):
                with self.assertRaises(tweakers.TweakerConversionError):
                    tweakers.plan_writes('KEYBC4', 'BCN4B', source_values(), set(source_values()),
                                         target_firmware=firmware)
        with self.assertRaises(tweakers.TweakerConversionError):
            tweakers.plan_writes('KEY4', 'KEYB4', source_values(), set(source_values()), target_firmware='2.2.00')

    def test_unregistered_cross_family_pairs_stay_refused_before_io(self):
        for source_type, target_type in (
            ('KEYBC2', 'BCI4A'), ('KEYBC4', 'BCI4A'), ('DINAUX4', 'BCN2B'),
            ('DINAUX4', 'BCN4B'), ('KEY1', 'BCN2B'), ('KEYBC4', 'KEYB4'), ('BCN4B', 'KEYBC4'),
        ):
            with self.subTest(source=source_type, target=target_type):
                with self.assertRaises(tweakers.TweakerRefused):
                    tweakers.ToolkitTweakerConversion(NoIO(), source_type, None, target_type, None)

    def test_schema_shape_changes_are_refused_before_io(self):
        for source in (True, False):
            valid = synthetic_spec('KEYBC4' if source else 'BCN4B', source=source)
            for name, parameter in valid.parameters.items():
                invalid = [replace(valid, parameters={key: item for key, item in valid.parameters.items()
                                                      if key != name})]
                for field, value in (('ArraySize', '17'), ('BitSize', '16')):
                    invalid.append(replace(valid, parameters={
                        **valid.parameters, name: replace(parameter, fields={**parameter.fields, field: value})}))
                for index, spec in enumerate(invalid):
                    with self.subTest(source=source, parameter=name, case=index):
                        source_spec = spec if source else synthetic_spec('KEYBC4', source=True)
                        target_spec = synthetic_spec('BCN4B', source=False) if source else spec
                        with self.assertRaises(tweakers.TweakerConversionError):
                            tweakers.ToolkitTweakerConversion(NoIO(), 'KEYBC4', source_spec, 'BCN4B', target_spec)


class ScriptedSession:
    def __init__(self, values):
        self.current = dict(values)
        self.sets = []
        self.saves = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def values(self):
        return dict(self.current)

    def set(self, name, value):
        self.sets.append((name, value))

    def save_to_source(self):
        self.saves += 1


class CouplerApplyTests(unittest.TestCase):
    def make_converter(self, source_type='KEYBC4', target_type='BCN4B', *, source=None, source_firmware='1.2.67'):
        converter = tweakers.ToolkitTweakerConversion(
            NoIO(), source_type, synthetic_spec(source_type, source=True),
            target_type, synthetic_spec(target_type, source=False))
        source_session = ScriptedSession(source_values() if source is None else source)
        target_session = ScriptedSession({
            'Application': '56 255', 'GroupAddress': '255 255 255 255 255 255 255 255 255',
            'IndicatorFunction': '2 2 2 2 3 3 3 3', 'IndicatorBrightness': '255',
            'LearnAnyApp': '0', 'LearnMode': '0', 'LearnedFlag': '1',
            'BistableSwitchBlock': '0', 'GroupAssertOnPowerup': '0',
        })
        # Readback is a literal expected image, not computed from the plan.
        readback_session = ScriptedSession({
            'Application': '56 255', 'GroupAddress': '255 0 165 254 255 255 255 255 17',
            'IndicatorFunction': '1 2 2 0 3 3 3 3', 'IndicatorBrightness': '255',
            'LearnAnyApp': '1', 'LearnMode': '1', 'LearnedFlag': '1',
            'BistableSwitchBlock': '0', 'GroupAssertOnPowerup': '0',
        })
        converter._unit_type = Mock(return_value=source_type)
        converter._unit_firmware = Mock(return_value=source_firmware)
        converter.database = Mock()
        converter.programmer = Mock()
        converter.programmer.load.side_effect = (source_session, target_session, readback_session)
        return converter, source_session, target_session

    @staticmethod
    def apply(converter, *, target_firmware='2.2.00'):
        return converter.apply('//SYNTH/254/p/20', 21, target_firmware=target_firmware,
                               target_catalog='SYNTHETIC')

    def test_each_pair_applies_once_with_literal_readback_and_no_brightness_write(self):
        for source_type, target_type in PAIRS:
            with self.subTest(source=source_type, target=target_type):
                converter, source, target = self.make_converter(source_type, target_type)
                before = deepcopy(source.current)
                result = self.apply(converter)
                self.assertEqual(target.sets, [
                    ('Application', '0x38 0xff'), ('LearnAnyApp', '1'), ('LearnMode', '1'),
                    ('GroupAddress', '0xFF 0x00 0xA5 0xFE 0xFF 0xFF 0xFF 0xFF 0x11'),
                    ('IndicatorFunction', '1 2 2 0 '),
                ])
                self.assertEqual(target.saves, 1)
                self.assertEqual(converter.programmer.load.call_count, 3)
                converter.database.create_unit.assert_called_once_with(
                    '//SYNTH/254', 21, 'Tweaked21', target_type, '2.2.00', catalog_number='SYNTHETIC')
                self.assertEqual(source.current, before)
                self.assertEqual((source.sets, source.saves), ([], 0))
                self.assertEqual(result['failed_writes'], {})
                self.assertEqual(result['verified_parameters'], 9)
                self.assertTrue(result['saved_to_database'])
                for field in ('project_saved', 'source_deleted', 'readdressed', 'hardware_programmed'):
                    self.assertFalse(result[field], field)

    def test_wrong_target_firmware_fails_before_all_io(self):
        for firmware in ('2.1.00', '2.2.01', '2.5.00', ''):
            with self.subTest(firmware=firmware):
                converter, source, target = self.make_converter()
                with self.assertRaises(tweakers.TweakerConversionError):
                    self.apply(converter, target_firmware=firmware)
                converter._unit_type.assert_not_called()
                converter._unit_firmware.assert_not_called()
                converter.programmer.load.assert_not_called()
                converter.database.create_unit.assert_not_called()
                self.assertEqual((source.sets, target.sets), ([], []))

    def test_source_firmware_gate_precedes_pp_read_and_creation(self):
        for firmware in ('1.2.63', '1.2.66', '1.2.68', '2.2.00', ''):
            with self.subTest(firmware=firmware):
                converter, source, target = self.make_converter(source_firmware=firmware)
                with self.assertRaises(tweakers.TweakerConversionError):
                    self.apply(converter)
                converter.programmer.load.assert_not_called()
                converter.database.create_unit.assert_not_called()
                self.assertEqual((source.sets, target.sets), ([], []))

    def test_malformed_source_is_read_once_then_refused_before_creation(self):
        for name, value in (('GroupAddress', '1 2 3 4'), ('IndicatorFunction', '0 1 2 4')):
            with self.subTest(parameter=name, value=value):
                values = {**source_values(), name: value}
                converter, source, target = self.make_converter(source=values)
                with self.assertRaises(tweakers.TweakerConversionError):
                    self.apply(converter)
                converter.programmer.load.assert_called_once_with('//SYNTH/254', '/db//SYNTH/254/p/20')
                converter.database.create_unit.assert_not_called()
                self.assertEqual(source.current, values)
                self.assertEqual((source.sets, target.sets, target.saves), ([], [], 0))


if __name__ == '__main__':
    unittest.main()
