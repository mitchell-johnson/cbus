"""Original InputUnit conversion vectors for ten non-sensor registrations.

Expected copied strings and writable decisions are independent literals. The
tests use synthetic schemas and scripted sessions, never native software.
"""
from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import Mock

from cbus_toolkit import toolkit_conversion_tweakers as tweakers
from cbus_toolkit.toolkit_conversion_input_unit import INPUT_IMMUTABLE
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec


PAIRS = (
    ('KEY1', 'KEY2'), ('KEY1', 'KEY4'), ('KEY2', 'KEY1'), ('KEY2', 'KEY4'),
    ('KEY4', 'KEY1'), ('KEY4', 'KEY2'), ('KEYBC2', 'KEYBC4'), ('KEYBC4', 'KEYBC2'),
    ('BCNC4A', 'BCNC4B'), ('BCNC4B', 'BCNC4A'),
)
KEY_TYPES = ('KEY1', 'KEY2', 'KEY4')
COUPLER_TYPES = ('KEYBC2', 'KEYBC4', 'BCNC4A', 'BCNC4B')
GROUPS = '  0x00 0xFf  254 127 0x42 17  18 19  '
INDICATORS = '3 2 1 0 '
CONSTRUCTOR_NAMES = (
    'Application', 'FirmwareVersion', 'Project', 'SerialNo', 'State', 'UnitAddress', 'UnitName',
    'UnitType', 'LearnAnyApp', 'LearnMode', 'LearnedFlag', 'AreaGroupAddress', 'StatusReportInterval',
    'GroupAddress', 'DebounceTime', 'IndicatorBrightness', 'LongPressTime', 'EEPROMLevelStore',
    'LightIndex', 'LightLevel', 'LightLevelStore1', 'LightLevelStore2', 'RampRate', 'InfraRedBank',
    'JPCommand', 'SRCommand', 'LPCommand', 'LRCommand', 'BlockAllocation', 'IndicatorBlockAssignment',
    'IndicatorFunction', 'TimerHighByte', 'TimerLowByte', 'TimerExpiryCommand', 'GAVBroadcastFlag',
)
TWEAKER_SUPPRESSIONS = (
    'InfraRedBank', 'EnableNightlight', 'EnableNightlightControl', 'DisableTimerFlash',
    'FirstKeyThrowAway', 'IndicatorPressedLevel', 'TimerDuration', 'IDBacklightIllumination',
    'PrimaryColour', 'EnableNightlightOnPCx', 'EnableNightlightOnPA6', 'DisableIR', 'DisableIRNEC',
)


def source_values(unit_type='KEY1'):
    values = {
        'Application': '0x38 0xFE', 'FirmwareVersion': '0x01 0x02 0x43',
        'Project': 'SYNTH', 'SerialNo': '1 2 3 4', 'State': '3', 'UnitAddress': '0x14',
        'UnitName': 'INPUT', 'UnitType': unit_type, 'GroupAddress': GROUPS,
        'IndicatorFunction': INDICATORS, 'LearnAnyApp': '1', 'LearnMode': '1', 'LearnedFlag': '0',
        'AreaGroupAddress': '0xfe', 'DebounceTime': '0x1f', 'LongPressTime': '19',
        'JPCommand': '13 0 15 1', 'InfraRedBank': '2', 'UnknownNativeOnly': '55',
    }
    if unit_type in KEY_TYPES:
        values['IndicatorBrightness'] = '0xAD'
    else:
        values['GAVBroadcastFlag'] = '0'
    return values


def plan_for(source_type='KEY1', target_type='KEY2', *, values=None, target_parameters=None):
    values = source_values(source_type) if values is None else values
    parameters = set(values) if target_parameters is None else target_parameters
    return tweakers.plan_writes(source_type, target_type, values, parameters, target_firmware='1.2.67')


def written(plan):
    return {name: value for name, value, _origin in plan.writes}


def synthetic_spec(unit_type):
    schema_type = 'BCNC4A' if unit_type == 'BCNC4B' else unit_type
    filename = schema_type + '.xml'
    shapes = {
        'Application': ('int', 2, 8), 'GroupAddress': ('int', 8, 8),
        'IndicatorFunction': ('int', 4, 2), 'LearnAnyApp': ('bit', 1, 8),
        'LearnMode': ('bit', 1, 8), 'LearnedFlag': ('bit', 1, 8),
    }
    if unit_type in KEY_TYPES:
        shapes['IndicatorBrightness'] = ('int', 1, 8)
    else:
        shapes['GAVBroadcastFlag'] = ('int', 1, 8)
    return UnitSpec(filename, {'Type': schema_type, 'MinVersion': '1.2.67', 'MaxVersion': '1.2.67'},
                    (filename,), {
                        name: ParameterSpec(name, kind, filename, {'ArraySize': str(size), 'BitSize': str(bits)})
                        for name, (kind, size, bits) in shapes.items()
                    })


class NoIO:
    def command(self, *_args, **_kwargs):
        raise AssertionError('validation must fail before C-Gate I/O')

    command_document = command


class InputUnitModelTests(unittest.TestCase):
    def test_all_seven_types_have_the_original_classic_constructor_order_and_flags(self):
        immutable = {'FirmwareVersion', 'SerialNo', 'State', 'UnitType', 'IndicatorBrightness', 'GAVBroadcastFlag'}
        expected = tuple((name, name not in immutable) for name in CONSTRUCTOR_NAMES)
        self.assertEqual(len(expected), 35)
        for unit_type in (*KEY_TYPES, *COUPLER_TYPES):
            with self.subTest(unit_type=unit_type):
                self.assertEqual(tweakers.AGENT_ATTRIBUTES[unit_type], expected)

    def test_all_ten_registered_pairs_preserve_group_indicator_and_application_strings(self):
        for source_type, target_type in PAIRS:
            with self.subTest(source=source_type, target=target_type):
                values = source_values(source_type)
                before = deepcopy(values)
                plan = plan_for(source_type, target_type, values=values)
                self.assertEqual(tweakers.admitted(source_type.lower(), target_type.lower()), 'TTweakerInputUnit')
                self.assertEqual(written(plan)['GroupAddress'], '  0x00 0xFf  254 127 0x42 17  18 19  ')
                self.assertEqual(written(plan)['IndicatorFunction'], '3 2 1 0 ')
                self.assertEqual(written(plan)['Application'], '0x38 0xFE')
                for name in ('GroupAddress', 'IndicatorFunction', 'Application'):
                    self.assertEqual(next(origin for field, _value, origin in plan.writes if field == name), 'copied')
                self.assertEqual(values, before)

    def test_boundary_vectors_do_not_gain_neo_slots_or_indicator_remapping(self):
        for groups, indicators in (
            ('0 0 0 0 0 0 0 0', '0 0 0 0'),
            ('255 255 255 255 255 255 255 255', '3 3 3 3'),
            ('0 127 254 255 42 99 231 17', '0 1 2 3'),
        ):
            with self.subTest(groups=groups, indicators=indicators):
                values = {**source_values(), 'GroupAddress': groups, 'IndicatorFunction': indicators}
                result = written(plan_for(values=values))
                self.assertEqual(result['GroupAddress'], groups)
                self.assertEqual(result['IndicatorFunction'], indicators)
                self.assertEqual(len(result['GroupAddress'].split()), 8)
                self.assertEqual(len(result['IndicatorFunction'].split()), 4)

    def test_pure_plan_does_not_parse_repack_or_pad_unconsumed_pp_strings(self):
        # The original InputUnit hook reads no numeric array. This pure-plan
        # behavior does not assert that C-Gate will accept these PP SET values.
        for groups, indicators in (
            ('17', '3'), ('1 2 3', '0 1'), ('opaque-group-value', 'opaque-indicator-value'),
            ('0 1 2 3 4 5 6 7 8', '0 1 2 3 4'),
        ):
            with self.subTest(groups=groups, indicators=indicators):
                values = {**source_values(), 'GroupAddress': groups, 'IndicatorFunction': indicators}
                result = written(plan_for(values=values))
                self.assertEqual(result['GroupAddress'], groups)
                self.assertEqual(result['IndicatorFunction'], indicators)
        plan = plan_for(values={**source_values(), 'GroupAddress': '', 'IndicatorFunction': ''})
        for name in ('GroupAddress', 'IndicatorFunction'):
            self.assertNotIn(name, written(plan))
            self.assertIn('empty source value', plan.not_written[name])

    def test_original_thirteen_tweaker_suppressions_do_not_create_absent_agent_attributes(self):
        self.assertEqual(INPUT_IMMUTABLE, TWEAKER_SUPPRESSIONS)
        values = {**source_values(), **{name: '7' for name in TWEAKER_SUPPRESSIONS}}
        plan = plan_for(values=values)
        for name in TWEAKER_SUPPRESSIONS:
            self.assertNotIn(name, written(plan), name)
        self.assertIn('InfraRedBank', plan.not_written)
        self.assertEqual(set(TWEAKER_SUPPRESSIONS).intersection(CONSTRUCTOR_NAMES), {'InfraRedBank'})
        for name in TWEAKER_SUPPRESSIONS[1:]:
            self.assertNotIn(name, dict(tweakers.AGENT_ATTRIBUTES['KEY2']))

    def test_key_brightness_is_written_but_coupler_virtual_overrides_keep_it_immutable(self):
        for source_type, target_type in PAIRS:
            with self.subTest(source=source_type, target=target_type):
                values = {**source_values(source_type), 'IndicatorBrightness': '0xAD'}
                plan = plan_for(source_type, target_type, values=values)
                if target_type in KEY_TYPES:
                    self.assertEqual(written(plan)['IndicatorBrightness'], '0xAD')
                else:
                    self.assertNotIn('IndicatorBrightness', written(plan))
                    self.assertIn('IndicatorBrightness', plan.not_written)

    def test_fresh_learned_state_and_metadata_are_not_copied(self):
        for source_type, target_type in PAIRS:
            with self.subTest(source=source_type, target=target_type):
                values = {**source_values(source_type), 'GAVBroadcastFlag': '0'}
                plan = plan_for(source_type, target_type, values=values)
                self.assertEqual(written(plan)['LearnMode'], '1')
                self.assertEqual(written(plan)['LearnAnyApp'], '1')
                for name in ('LearnedFlag', 'GAVBroadcastFlag', 'FirmwareVersion', 'SerialNo', 'State', 'UnitType'):
                    self.assertNotIn(name, written(plan), name)
                self.assertEqual(plan.model_context['source_firmware'], '1.2.67')
                self.assertEqual(plan.model_context['target_firmware'], '1.2.67')
                self.assertTrue(plan.model_context['fresh_target_model'])

    def test_pp_writes_follow_constructor_order_and_preserve_untransformed_strings(self):
        plan = plan_for()
        self.assertEqual([name for name, _value, _origin in plan.writes], [
            'Application', 'Project', 'UnitAddress', 'UnitName', 'LearnAnyApp', 'LearnMode',
            'AreaGroupAddress', 'GroupAddress', 'DebounceTime', 'IndicatorBrightness', 'LongPressTime',
            'JPCommand', 'IndicatorFunction',
        ])
        for name in ('UnitAddress', 'UnitName', 'AreaGroupAddress', 'DebounceTime', 'LongPressTime', 'JPCommand'):
            self.assertEqual(written(plan)[name], source_values()[name], name)
        self.assertNotIn('UnknownNativeOnly', written(plan))

    def test_empty_unmodified_attribute_stays_unwritten_and_missing_native_parameter_is_reported(self):
        values = {**source_values(), 'LongPressTime': ''}
        plan = plan_for(values=values, target_parameters=set(values) - {'DebounceTime'})
        self.assertNotIn('LongPressTime', written(plan))
        self.assertIn('empty source value', plan.not_written['LongPressTime'])
        self.assertNotIn('DebounceTime', written(plan))
        self.assertIn('no native target parameter', plan.not_written['DebounceTime'])


class InputUnitGuardTests(unittest.TestCase):
    def test_all_ten_matching_profiles_construct_without_io(self):
        for source_type, target_type in PAIRS:
            with self.subTest(source=source_type, target=target_type):
                converter = tweakers.ToolkitTweakerConversion(
                    NoIO(), source_type, synthetic_spec(source_type), target_type, synthetic_spec(target_type))
                self.assertEqual(converter.tweaker, 'TTweakerInputUnit')

    def test_bcnc4b_requires_the_exact_catalogued_schema_alias_in_both_directions(self):
        valid = synthetic_spec('BCNC4B')
        self.assertEqual((valid.unit_type, valid.filename), ('BCNC4A', 'BCNC4A.xml'))
        for source_type, target_type in (('BCNC4A', 'BCNC4B'), ('BCNC4B', 'BCNC4A')):
            for invalid in (
                replace(valid, filename='BCNC4B.xml'),
                replace(valid, metadata={**valid.metadata, 'Type': 'BCNC4B'}),
                replace(valid, filename='KEYBC4.xml', metadata={**valid.metadata, 'Type': 'KEYBC4'}),
            ):
                with self.subTest(source=source_type, target=target_type, filename=invalid.filename):
                    source_spec = invalid if source_type == 'BCNC4B' else synthetic_spec(source_type)
                    target_spec = invalid if target_type == 'BCNC4B' else synthetic_spec(target_type)
                    with self.assertRaises(tweakers.TweakerConversionError):
                        tweakers.ToolkitTweakerConversion(NoIO(), source_type, source_spec, target_type, target_spec)

    def test_unregistered_cross_family_pairs_are_refused_before_io(self):
        for source_type, target_type in (
            ('KEY1', 'KEY1'), ('KEYBC2', 'KEYBC2'),
            ('BCNC4A', 'BCNC4A'), ('KEY1', 'KEYBC2'), ('KEYBC2', 'BCNC4A'), ('BCNC4B', 'KEYBC4'),
        ):
            with self.subTest(source=source_type, target=target_type):
                with self.assertRaises(tweakers.TweakerRefused):
                    tweakers.ToolkitTweakerConversion(NoIO(), source_type, None, target_type, None)

    def test_admitted_sensor_self_conversion_requires_its_exact_specs_before_io(self):
        with self.assertRaisesRegex(tweakers.TweakerConversionError, 'source-pinned specification and firmware'):
            tweakers.ToolkitTweakerConversion(NoIO(), 'SENPILL', None, 'SENPILL', None)

    def test_target_firmware_is_exact_and_not_a_neo_profile(self):
        for firmware in (None, '', '1.2.63', '1.2.66', '1.2.68', '1.2.067', '2.2.00', '2.5.00'):
            with self.subTest(firmware=firmware):
                with self.assertRaises(tweakers.TweakerConversionError):
                    tweakers.plan_writes('KEY1', 'KEY2', source_values(), set(source_values()), target_firmware=firmware)

    def test_wrong_schema_type_filename_version_and_core_shape_are_refused_before_io(self):
        for source_type, target_type in (('KEY1', 'KEY2'), ('KEYBC2', 'KEYBC4'), ('BCNC4A', 'BCNC4B')):
            for source in (True, False):
                valid = synthetic_spec(source_type if source else target_type)
                invalid = [None, replace(valid, filename='wrong.xml'),
                           replace(valid, metadata={**valid.metadata, 'Type': 'WRONG'}),
                           replace(valid, metadata={**valid.metadata, 'MinVersion': '9.0.00', 'MaxVersion': '9.0.00'})]
                guarded_names = ('Application', 'GroupAddress', 'IndicatorFunction', 'LearnMode', 'LearnAnyApp', 'LearnedFlag')
                if source_type in KEY_TYPES:
                    guarded_names += ('IndicatorBrightness',)
                for name in guarded_names:
                    invalid.append(replace(valid, parameters={key: item for key, item in valid.parameters.items()
                                                              if key != name}))
                    invalid.append(replace(valid, parameters={
                        **valid.parameters, name: replace(valid.parameters[name], fields={'ArraySize': '17', 'BitSize': '16'})}))
                for index, spec in enumerate(invalid):
                    with self.subTest(source=source_type, target=target_type, source_spec=source, case=index):
                        source_spec = spec if source else synthetic_spec(source_type)
                        target_spec = synthetic_spec(target_type) if source else spec
                        with self.assertRaises(tweakers.TweakerConversionError):
                            tweakers.ToolkitTweakerConversion(NoIO(), source_type, source_spec, target_type, target_spec)


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


class InputUnitApplyTests(unittest.TestCase):
    def make_converter(self, source_type='KEY1', target_type='KEY2', *, source_firmware='1.2.67'):
        converter = tweakers.ToolkitTweakerConversion(
            NoIO(), source_type, synthetic_spec(source_type), target_type, synthetic_spec(target_type))
        source_session = ScriptedSession(source_values(source_type))
        defaults = {
            'Application': '56 255', 'GroupAddress': '255 255 255 255 255 255 255 255',
            'IndicatorFunction': '0 0 0 0', 'LearnAnyApp': '0', 'LearnMode': '0', 'LearnedFlag': '1',
        }
        readback = {
            'Application': '56 254', 'GroupAddress': '0 255 254 127 66 17 18 19',
            'IndicatorFunction': '3 2 1 0', 'LearnAnyApp': '1', 'LearnMode': '1', 'LearnedFlag': '1',
        }
        if target_type in KEY_TYPES:
            defaults['IndicatorBrightness'] = '255'
            readback['IndicatorBrightness'] = '173'
        else:
            defaults['GAVBroadcastFlag'] = '255'
            readback['GAVBroadcastFlag'] = '255'
        target_session = ScriptedSession(defaults)
        readback_session = ScriptedSession(readback)
        converter._unit_type = Mock(return_value=source_type)
        converter._unit_firmware = Mock(return_value=source_firmware)
        converter.database = Mock()
        converter.programmer = Mock()
        converter.programmer.load.side_effect = (source_session, target_session, readback_session)
        return converter, source_session, target_session

    @staticmethod
    def apply(converter, *, target_firmware='1.2.67'):
        return converter.apply('//SYNTH/254/p/20', 21, target_firmware=target_firmware,
                               target_catalog='SYNTHETIC')

    def test_each_pair_stages_exact_copied_strings_and_verifies_one_save(self):
        for source_type, target_type in PAIRS:
            with self.subTest(source=source_type, target=target_type):
                converter, source, target = self.make_converter(source_type, target_type)
                before = deepcopy(source.current)
                result = self.apply(converter)
                expected_sets = [
                    ('Application', '0x38 0xFE'), ('LearnAnyApp', '1'), ('LearnMode', '1'),
                    ('GroupAddress', '  0x00 0xFf  254 127 0x42 17  18 19  '),
                ]
                if target_type in KEY_TYPES:
                    expected_sets.append(('IndicatorBrightness', '0xAD'))
                expected_sets.append(('IndicatorFunction', '3 2 1 0 '))
                self.assertEqual(target.sets, expected_sets)
                self.assertEqual(target.saves, 1)
                self.assertEqual(converter.programmer.load.call_count, 3)
                converter.database.create_unit.assert_called_once_with(
                    '//SYNTH/254', 21, 'Tweaked21', target_type, '1.2.67', catalog_number='SYNTHETIC')
                self.assertEqual(source.current, before)
                self.assertEqual((source.sets, source.saves), ([], 0))
                self.assertEqual(result['failed_writes'], {})
                self.assertEqual(result['verified_parameters'], 7)
                self.assertTrue(result['saved_to_database'])
                for field in ('project_saved', 'source_deleted', 'readdressed', 'hardware_programmed'):
                    self.assertFalse(result[field], field)

    def test_wrong_target_firmware_precedes_all_metadata_and_pp_io(self):
        for firmware in ('1.2.66', '1.2.68', '2.2.00', '2.5.00', ''):
            with self.subTest(firmware=firmware):
                converter, source, target = self.make_converter()
                with self.assertRaises(tweakers.TweakerConversionError):
                    self.apply(converter, target_firmware=firmware)
                converter._unit_type.assert_not_called()
                converter._unit_firmware.assert_not_called()
                converter.programmer.load.assert_not_called()
                converter.database.create_unit.assert_not_called()
                self.assertEqual((source.sets, target.sets), ([], []))

    def test_source_firmware_and_type_refusals_precede_pp_read_and_target_creation(self):
        for source_type, target_type in (('KEY1', 'KEY2'), ('KEYBC2', 'KEYBC4'), ('BCNC4B', 'BCNC4A')):
            for firmware in ('1.2.63', '1.2.66', '1.2.68', '2.2.00', ''):
                with self.subTest(source=source_type, target=target_type, firmware=firmware):
                    converter, source, target = self.make_converter(source_type, target_type, source_firmware=firmware)
                    with self.assertRaises(tweakers.TweakerConversionError):
                        self.apply(converter)
                    converter.programmer.load.assert_not_called()
                    converter.database.create_unit.assert_not_called()
                    self.assertEqual((source.sets, target.sets), ([], []))
        converter, _source, _target = self.make_converter()
        converter._unit_type.return_value = 'KEY4'
        with self.assertRaises(tweakers.TweakerConversionError):
            self.apply(converter)
        converter._unit_firmware.assert_not_called()
        converter.programmer.load.assert_not_called()
        converter.database.create_unit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
