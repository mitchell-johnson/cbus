"""Portable, literal RELDN tweaker vectors; no vendor specs or live endpoints."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from cbus_toolkit import toolkit_conversion_tweakers as tweakers
from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.programming import ProgrammingCommandError
from cbus_toolkit.toolkit_conversion_reldn import relay_assignments
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec


OTHER_RELAYS = ('RELDN12', 'RELDN4', 'RELDN8B', 'RELSM8')
LOGIC_NAMES = ('LogicGA13Associations', 'LogicGA14Associations',
               'LogicGA15Associations', 'LogicGA16Associations')
REPACKED_NAMES = ('GroupAddress', *LOGIC_NAMES)

# These are literal expected vectors transcribed independently of the production
# implementation. The 255 and 254 entries exercise valid byte boundaries; every
# stored group slot has its own value except the explicit reserved-address marker.
SOURCE_ARRAYS = {
    'GroupAddress': '0 10 255 30 40 50 60 70 80 90 100 110 120 130 140 254',
    'LogicGA13Associations': '1 0 1 0 1 1 0 1 0 1 0 1',
    'LogicGA14Associations': '0 1 0 1 0 0 1 0 1 0 1 0',
    'LogicGA15Associations': '1 1 1 1 1 1 1 1 1 1 1 1',
    'LogicGA16Associations': '1 0 0 0 0 1 1 0 0 0 0 1',
}
FORWARD = {
    'GroupAddress': '10 255 30 40 70 80 90 100 255 255 255 255 120 130 140 254',
    'LogicGA13Associations': '0 1 0 1 1 0 1 0 0 0 0 0',
    'LogicGA14Associations': '1 0 1 0 0 1 0 1 0 0 0 0',
    'LogicGA15Associations': '1 1 1 1 1 1 1 1 0 0 0 0',
    'LogicGA16Associations': '0 0 0 0 0 0 0 0 0 0 0 0',
}
REVERSE = {
    'GroupAddress': '255 0 10 255 30 255 255 40 50 60 70 255 120 130 140 254',
    'LogicGA13Associations': '0 1 0 1 0 0 0 1 1 0 1 0',
    'LogicGA14Associations': '0 0 1 0 1 0 0 0 0 1 0 0',
    'LogicGA15Associations': '0 1 1 1 1 0 0 1 1 1 1 0',
    'LogicGA16Associations': '0 1 0 0 0 0 0 0 1 1 0 0',
}

# Constructor order, independently pinned from the recovered base/DIN chain.
# RELSM8 uses the basic output constructor and omits the last three attributes.
FULL_ATTRIBUTES = (
    ('Application', True), ('FirmwareVersion', False), ('Project', True),
    ('SerialNo', False), ('State', False), ('UnitAddress', True),
    ('UnitName', True), ('UnitType', False), ('CheckSum', True), ('Burden', False),
    ('LocalToggleEnable', True), ('ClockGenEnable', True), ('LearnMode', True),
    ('LearnAnyApplication', True), ('LearnedFlag', True), ('AreaGroupAddress', True),
    ('PowerUpDelay', True), ('NetworkPriority', True), ('LightLevel', True),
    ('LogicGA13Associations', True), ('LogicGA14Associations', True),
    ('LogicGA15Associations', True), ('LogicGA16Associations', True),
    ('LogicFunction', True), ('GroupAddress', True), ('MinDimmingLevel', True),
    ('MaxDimmingLevel', True), ('LevelStoreEnable', True), ('LogicLevelStoreEnable', True),
    ('InterLockingChannel', True), ('RestrikeChannel', True), ('RestrikeDelay', True),
)


def source_values():
    return {
        **SOURCE_ARRAYS,
        'Application': '56 255', 'Project': 'SYNTH', 'UnitName': 'SOURCE',
        'UnitAddress': '0x14', 'FirmwareVersion': '9 8 7', 'SerialNo': '1 2 3 4',
        'State': '3', 'UnitType': 'RELDN8', 'Burden': '1', 'CheckSum': '42',
        'PowerUpDelay': '31', 'LightLevel': '18 35 52 69', 'LogicFunction': '1 0 1 0',
        'MinDimmingLevel': '7', 'MaxDimmingLevel': '243', 'LevelStoreEnable': '1',
        'InterLockingChannel': '3', 'RestrikeChannel': '9', 'RestrikeDelay': '17',
        'UnknownNativeOnly': '99',
    }


def writes(plan):
    return {name: value for name, value, _origin in plan.writes}


def synthetic_spec(unit_type):
    """Only the independent public PP shape needed by the constructor guard."""
    parameters = {}
    for name in REPACKED_NAMES:
        group = name == 'GroupAddress'
        size = 16 if group else (4 if unit_type == 'RELDN4' else 12)
        fields = {'ArraySize': str(size), 'BitSize': '8' if group else '1'}
        parameters[name] = ParameterSpec(name, 'int', 'synthetic.xml', fields)
    declared_type = 'RELDN8' if unit_type == 'RELDN8B' else unit_type
    return UnitSpec('synthetic.xml', {'Type': declared_type, 'MinVersion': '2.7.00',
                                    'MaxVersion': '2.7.99'}, ('synthetic.xml',), parameters)


class NoIO:
    def command(self, *_args, **_kwargs):
        raise AssertionError('validation must fail before C-Gate I/O')

    command_document = command


class RELDNConstructorTests(unittest.TestCase):
    def test_original_attribute_order_and_initial_writable_flags(self):
        for unit_type in ('RELDN8', *OTHER_RELAYS):
            with self.subTest(unit_type=unit_type):
                expected = FULL_ATTRIBUTES[:-3] if unit_type == 'RELSM8' else FULL_ATTRIBUTES
                self.assertEqual(tweakers.AGENT_ATTRIBUTES[unit_type], expected)

    def test_seven_safe_directions_are_admitted_case_insensitively(self):
        for other in OTHER_RELAYS:
            with self.subTest(other=other):
                self.assertEqual(tweakers.admitted('reldn8', other.lower()), 'TTweakerRELDN8_TO_X')
                if other != 'RELDN4':
                    self.assertEqual(tweakers.admitted(other.lower(), 'reldn8'), 'TTweakerRELDNX_TO_8')

    def test_four_element_reldn4_source_is_refused_before_io_without_padding(self):
        self.assertEqual(tweakers.lookup('RELDN4', 'RELDN8'), 'TTweakerRELDNX_TO_8')
        with self.assertRaises(tweakers.TweakerRefused):
            tweakers.admitted('reldn4', 'reldn8')
        with self.assertRaises(tweakers.TweakerRefused):
            tweakers.ToolkitTweakerConversion(NoIO(), 'RELDN4', None, 'RELDN8', None)
        source = source_values()
        for name in LOGIC_NAMES:
            source[name] = '1 0 1 0'
        with self.assertRaises(tweakers.TweakerRefused):
            tweakers.plan_writes('RELDN4', 'RELDN8', source, set(source))

    def test_matching_spec_shapes_admit_seven_directions_without_io(self):
        pairs = [('RELDN8', other) for other in OTHER_RELAYS]
        pairs += [(other, 'RELDN8') for other in OTHER_RELAYS if other != 'RELDN4']
        for source_type, target_type in pairs:
            with self.subTest(source=source_type, target=target_type):
                converter = tweakers.ToolkitTweakerConversion(
                    NoIO(), source_type, synthetic_spec(source_type), target_type, synthetic_spec(target_type))
                self.assertEqual((converter.source_type, converter.target_type), (source_type, target_type))

    def test_missing_wrong_or_incomplete_specifications_fail_before_io(self):
        valid = synthetic_spec('RELDN8')
        target = synthetic_spec('RELDN12')
        variants = [None, synthetic_spec('RELDN12')]
        missing = dict(valid.parameters)
        del missing['LogicGA16Associations']
        variants.append(replace(valid, parameters=missing))
        for name, kind, size, width in (
            ('GroupAddress', 'int', 15, 8), ('GroupAddress', 'int', 16, 7),
            ('GroupAddress', 'bit', 16, 8), ('LogicGA13Associations', 'int', 4, 1),
            ('LogicGA14Associations', 'int', 12, 8), ('LogicGA15Associations', 'bit', 12, 1),
        ):
            parameters = dict(valid.parameters)
            parameters[name] = ParameterSpec(name, kind, 'synthetic.xml',
                                             {'ArraySize': str(size), 'BitSize': str(width)})
            variants.append(replace(valid, parameters=parameters))
        for spec in variants:
            with self.subTest(spec=spec):
                with self.assertRaises(tweakers.TweakerConversionError):
                    tweakers.ToolkitTweakerConversion(NoIO(), 'RELDN8', spec, 'RELDN12', target)
        with self.assertRaises(tweakers.TweakerConversionError):
            tweakers.ToolkitTweakerConversion(NoIO(), 'RELDN8', valid, 'RELDN12', valid)

    def test_reldn8b_uses_explicit_reldn8_spec_alias(self):
        alias = synthetic_spec('RELDN8B')
        self.assertEqual(alias.unit_type, 'RELDN8')
        converter = tweakers.ToolkitTweakerConversion(
            NoIO(), 'RELDN8B', alias, 'RELDN8', synthetic_spec('RELDN8'))
        self.assertEqual(converter.source_type, 'RELDN8B')

    def test_firmware_outside_specification_is_refused_before_io(self):
        converter = tweakers.ToolkitTweakerConversion(
            NoIO(), 'RELDN8', synthetic_spec('RELDN8'), 'RELDN12', synthetic_spec('RELDN12'))
        for firmware in ('2.6.99', '2.8.00'):
            with self.subTest(firmware=firmware), self.assertRaises(tweakers.TweakerConversionError):
                converter.apply('//SYNTH/254/p/20', 21, target_firmware=firmware,
                                target_catalog='SYNTHETIC')


class RELDNLiteralModelTests(unittest.TestCase):
    def test_independent_instruction_fixture_and_complete_schema_boundary(self):
        path = Path(__file__).resolve().parents[1] / 'research/fixtures/toolkit-reldn-conversion-literal-vectors.json'
        fixture = json.loads(path.read_text(encoding='utf-8'))
        self.assertFalse(fixture['original_code_executed'])
        self.assertEqual(tuple(fixture['setter_order']), REPACKED_NAMES)
        self.assertEqual(len(fixture['cases']), 4)
        for case in fixture['cases'][:3]:
            with self.subTest(case=case['name']):
                self.assertEqual([len(case['source_values'][name].split()) for name in LOGIC_NAMES], [12] * 4)
                assignments = relay_assignments(case['tweaker'], case['source_values'])
                self.assertEqual([name for name, _value, _origin in assignments], fixture['setter_order'])
                self.assertEqual({name: value for name, value, _origin in assignments}, case['expected_values'])
        # Eight tokens cover the reverse method's direct reads, but the admitted
        # source PP schema has twelve. The static oracle must not widen admission.
        incomplete = fixture['cases'][3]
        self.assertEqual(incomplete['tweaker'], 'TTweakerRELDNX_TO_8')
        self.assertEqual([len(incomplete['source_values'][name].split()) for name in LOGIC_NAMES], [8] * 4)
        with self.assertRaisesRegex(ValueError, 'exactly 12'):
            relay_assignments(incomplete['tweaker'], incomplete['source_values'])
        with self.assertRaises(tweakers.TweakerConversionError):
            tweakers.plan_writes('RELDN12', 'RELDN8', incomplete['source_values'], set(REPACKED_NAMES))

    def test_both_original_rule_directions_and_setter_order_on_complete_arrays(self):
        # Pure original-rule proof is distinct from native-source admission:
        # RELDN4's actual four-element source cannot satisfy this complete input.
        for tweaker, expected in (('TTweakerRELDN8_TO_X', FORWARD),
                                  ('TTweakerRELDNX_TO_8', REVERSE)):
            with self.subTest(tweaker=tweaker):
                assignments = relay_assignments(tweaker, SOURCE_ARRAYS)
                self.assertEqual(tuple(name for name, _value, _origin in assignments), REPACKED_NAMES)
                self.assertEqual({name: value for name, value, _origin in assignments}, expected)

    def test_seven_admitted_directions_match_independent_nondefault_vectors(self):
        for other in OTHER_RELAYS:
            for source_type, target_type, expected in (('RELDN8', other, FORWARD),
                                                       (other, 'RELDN8', REVERSE)):
                if source_type == 'RELDN4':
                    continue
                with self.subTest(source=source_type, target=target_type):
                    source = source_values()
                    before = deepcopy(source)
                    plan = tweakers.plan_writes(source_type, target_type, source, set(source))
                    result = writes(plan)
                    self.assertEqual({name: result[name] for name in REPACKED_NAMES}, expected)
                    self.assertEqual(source, before, 'planning must retain the exact source PP strings')
                    for name in REPACKED_NAMES:
                        self.assertRegex(result[name], r'^[0-9]+(?: [0-9]+)*$')

    def test_non_repacked_writable_values_are_preserved_exactly(self):
        source = source_values()
        source['Application'] = '0x38 0xff'
        source['PowerUpDelay'] = '0x1f'
        for source_type, target_type in (('RELDN8', 'RELDN12'), ('RELDN8B', 'RELDN8')):
            with self.subTest(source=source_type, target=target_type):
                plan = tweakers.plan_writes(source_type, target_type, source, set(source))
                result = writes(plan)
                for name in ('Application', 'Project', 'UnitAddress', 'UnitName', 'CheckSum',
                             'PowerUpDelay', 'LightLevel', 'LogicFunction', 'MinDimmingLevel',
                             'MaxDimmingLevel', 'LevelStoreEnable', 'InterLockingChannel',
                             'RestrikeChannel', 'RestrikeDelay'):
                    self.assertEqual(result[name], source[name], name)
                self.assertNotIn('UnknownNativeOnly', result)

    def test_immutable_metadata_and_burden_are_never_written(self):
        source = source_values()
        for other in OTHER_RELAYS:
            with self.subTest(target=other):
                plan = tweakers.plan_writes('RELDN8', other, source, set(source))
                result = writes(plan)
                for name in ('FirmwareVersion', 'SerialNo', 'State', 'UnitType', 'Burden'):
                    self.assertNotIn(name, result)
                    self.assertEqual(plan.not_written[name], 'initially immutable agent attribute')
                with self.assertRaises(TypeError):
                    plan.not_written['Burden'] = 'mutable'
                with self.assertRaises(FrozenInstanceError):
                    plan.target_type = 'RELDN8'

    def test_pp_writes_follow_constructor_order_not_tweaker_setter_order(self):
        source = source_values()
        plan = tweakers.plan_writes('RELDN8', 'RELDN12', source, set(source))
        names = [name for name, _value, _origin in plan.writes]
        self.assertEqual(names, [
            'Application', 'Project', 'UnitAddress', 'UnitName', 'CheckSum', 'PowerUpDelay',
            'LightLevel', 'LogicGA13Associations', 'LogicGA14Associations',
            'LogicGA15Associations', 'LogicGA16Associations', 'LogicFunction', 'GroupAddress',
            'MinDimmingLevel', 'MaxDimmingLevel', 'LevelStoreEnable', 'InterLockingChannel',
            'RestrikeChannel', 'RestrikeDelay',
        ])

    def test_relsm8_does_not_gain_din_only_attributes(self):
        source = source_values()
        forward = tweakers.plan_writes('RELDN8', 'RELSM8', source, set(source))
        reverse = tweakers.plan_writes('RELSM8', 'RELDN8', source, set(source))
        for name in ('InterLockingChannel', 'RestrikeChannel', 'RestrikeDelay'):
            self.assertNotIn(name, writes(forward))
            self.assertNotIn(name, writes(reverse))
            self.assertIn('no source agent attribute', reverse.not_written[name])

    def test_missing_native_target_parameter_is_reported_without_reordering(self):
        source = source_values()
        native = set(source) - {'LogicGA14Associations'}
        plan = tweakers.plan_writes('RELDN8', 'RELDN8B', source, native)
        self.assertNotIn('LogicGA14Associations', writes(plan))
        self.assertIn('no native target parameter', plan.not_written['LogicGA14Associations'])
        self.assertEqual(writes(plan)['LogicGA13Associations'], FORWARD['LogicGA13Associations'])
        self.assertEqual(writes(plan)['LogicGA15Associations'], FORWARD['LogicGA15Associations'])

    def test_hexadecimal_input_is_rendered_as_single_spaced_decimal(self):
        source = source_values()
        source['GroupAddress'] = '$00 0x0a $ff 0x1e $28 0x32 $3c 0x46 $50 0x5a $64 0x6e $78 0x82 $8c 0xfe'
        source['LogicGA13Associations'] = '$01 0x0 $01 0x0 $01 0x1 $00 0x1 $00 0x1 $00 0x1'
        plan = tweakers.plan_writes('RELDN8', 'RELDN12', source, set(source))
        self.assertEqual(writes(plan)['GroupAddress'], FORWARD['GroupAddress'])
        self.assertEqual(writes(plan)['LogicGA13Associations'], FORWARD['LogicGA13Associations'])

    def test_partial_missing_malformed_or_out_of_range_arrays_fail_closed(self):
        malformed = (
            ('GroupAddress', '0 ' * 15), ('GroupAddress', '0 ' * 17),
            ('GroupAddress', '-1 ' + '0 ' * 15), ('GroupAddress', '256 ' + '0 ' * 15),
            ('GroupAddress', 'oops ' + '0 ' * 15), ('GroupAddress', ''),
            ('LogicGA13Associations', '0 ' * 11), ('LogicGA14Associations', '0 ' * 13),
            ('LogicGA15Associations', '2 ' + '0 ' * 11),
            ('LogicGA16Associations', '0.0 ' + '0 ' * 11),
        )
        for source_type, target_type in (('RELDN8', 'RELDN12'), ('RELDN8B', 'RELDN8')):
            for name, value in malformed:
                with self.subTest(source=source_type, target=target_type, parameter=name, value=value):
                    source = source_values()
                    source[name] = value
                    with self.assertRaises(tweakers.TweakerConversionError):
                        tweakers.plan_writes(source_type, target_type, source, set(source))
            for name in REPACKED_NAMES:
                with self.subTest(source=source_type, target=target_type, missing=name):
                    source = source_values()
                    del source[name]
                    with self.assertRaises(tweakers.TweakerConversionError):
                        tweakers.plan_writes(source_type, target_type, source, set(source))


class ScriptedSession:
    """A staged PP session with explicit write failure and save observations."""
    def __init__(self, values, *, set_error=None):
        self.current = dict(values)
        self.set_error = set_error
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
        if name == 'LogicGA13Associations' and self.set_error is not None:
            raise self.set_error
        self.current[name] = value

    def save_to_source(self):
        self.saves += 1


class RELDNApplyFailureTests(unittest.TestCase):
    def make_converter(self, *, source=None, set_error=None):
        converter = tweakers.ToolkitTweakerConversion(
            NoIO(), 'RELDN8', synthetic_spec('RELDN8'), 'RELDN12', synthetic_spec('RELDN12'))
        source_session = ScriptedSession(SOURCE_ARRAYS if source is None else source)
        target_session = ScriptedSession({
            'GroupAddress': '0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0',
            **{name: '0 0 0 0 0 0 0 0 0 0 0 0' for name in LOGIC_NAMES},
        }, set_error=set_error)
        converter._unit_type = Mock(return_value='RELDN8')
        converter.programmer = Mock()
        converter.programmer.load.side_effect = (source_session, target_session, target_session)
        converter.database = Mock()
        return converter, source_session, target_session

    @staticmethod
    def apply(converter):
        return converter.apply('//SYNTH/254/p/20', 21, target_firmware='2.7.00',
                               target_catalog='SYNTHETIC')

    def test_transport_failure_stops_set_sequence_and_never_attempts_save(self):
        for error in (RuntimeError('timeout after sending PP SET; outcome unknown'),
                      OSError('connection lost after sending PP SET')):
            with self.subTest(error=error):
                converter, source, target = self.make_converter(set_error=error)
                with self.assertRaises(type(error)) as caught:
                    self.apply(converter)
                self.assertIs(caught.exception, error, 'retain the first uncertain transport failure')
                self.assertEqual(target.sets, [('LogicGA13Associations', FORWARD['LogicGA13Associations'])])
                self.assertEqual(target.saves, 0)
                self.assertEqual(converter.programmer.load.call_count, 2)
                self.assertEqual(source.sets, [])

    def test_complete_server_rejection_retains_default_and_continues_original_sequence(self):
        reply = CGateResponse(('408 parameter unavailable',), '408 parameter unavailable', 408)
        for error in (CGateError(reply), ProgrammingCommandError(reply, [(408, 'parameter unavailable')])):
            with self.subTest(error=error):
                converter, source, target = self.make_converter(set_error=error)
                result = self.apply(converter)
                self.assertEqual(result['failed_writes'], {'LogicGA13Associations': str(error)})
                self.assertTrue(result['saved_to_database'])
                self.assertEqual(target.saves, 1)
                self.assertEqual([name for name, _value in target.sets], [
                    'LogicGA13Associations', 'LogicGA14Associations', 'LogicGA15Associations',
                    'LogicGA16Associations', 'GroupAddress',
                ])
                self.assertEqual(target.current, {
                    **FORWARD, 'LogicGA13Associations': '0 0 0 0 0 0 0 0 0 0 0 0',
                })
                self.assertEqual(converter.programmer.load.call_count, 3)
                self.assertEqual(source.sets, [])

    def test_malformed_source_arrays_fail_after_read_and_before_target_creation(self):
        for name, value in (('GroupAddress', '0 0 0'), ('LogicGA13Associations', '1 0 1 0'),
                            ('LogicGA16Associations', '2 0 0 0 0 0 0 0 0 0 0 0')):
            with self.subTest(parameter=name):
                values = {**SOURCE_ARRAYS, name: value}
                converter, source, target = self.make_converter(source=values)
                with self.assertRaises(tweakers.TweakerConversionError):
                    self.apply(converter)
                converter.database.create_unit.assert_not_called()
                self.assertEqual(converter.programmer.load.call_count, 1)
                self.assertEqual(source.current, values)
                self.assertEqual(source.sets, [])
                self.assertEqual(target.sets, [])
                self.assertEqual(target.saves, 0)


if __name__ == '__main__':
    unittest.main()
