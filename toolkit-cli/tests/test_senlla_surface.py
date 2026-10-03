"""Independent SENLLA surface component facts; no original or device execution."""
import copy
from dataclasses import replace
import unittest

from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.senlla_surface import (
    BITS, LAYOUTS, SENLLASurface, SurfaceView, check_profile, display_margin_percent,
    display_target_lux, logical_bank_level_overlay, logical_bank_usage_parameters,
)
from cbus_toolkit.sensors import SensorError
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec


IDENTITY = ('SENLLA', '2.4.00', '5754PE')
# Authored minimal schema, independently transcribed numeric layout facts.
# BankSwitchGroupUsed is int, despite its single-bit elements.
ROWS = (
    ('PowerUpTargetGroupLevel', 'int', 16, 1, 8, 0, 0, [13]),
    ('PowerUpMarginGroupLevel', 'int', 17, 1, 8, 0, 0, [89]),
    ('PowerUpBankSwitchGroupLevel', 'int', 18, 1, 8, 0, 0, [231]),
    ('LightLevelTargetGroup', 'int', 19, 1, 8, 0, 0, [255]),
    ('LightLevelMarginGroup', 'int', 20, 1, 8, 0, 0, [255]),
    ('BankSwitchThresholdGroup', 'int', 21, 1, 8, 0, 0, [255]),
    ('LightLevelTargetGroupLevelStore', 'bit', 22, 1, 1, 0, 0, [0]),
    ('LightLevelMarginGroupLevelStore', 'bit', 22, 1, 1, 1, 0, [0]),
    ('BankSwitchGroupLevelStore', 'bit', 22, 1, 1, 2, 0, [0]),
    ('BankSwitchThresholdBehaviour', 'int', 22, 1, 2, 4, 0, [0]),
    ('PECTargetLux', 'int', 27, 1, 8, 0, 0, [40]),
    ('PECMarginLux', 'int', 28, 1, 8, 0, 0, [8]),
    ('BankSwitchGroupUsed', 'int', 72, 8, 1, 6, 0, [0] * 8),
)


def fixture(filename='SENLLA.xml'):
    parameters = {}
    for name, kind, address, count, bits, bit, skip, values in ROWS:
        fields = {'Name': name, 'Type': kind, 'Address': str(address), 'ArraySize': str(count),
                  'BitSize': str(bits), 'BitAddress': str(bit), 'ArraySkip': str(skip),
                  'DefaultValue': ' '.join(map(str, values))}
        parameters[name] = ParameterSpec(name, kind, 'authored-senlla-component.xml', fields)
    return UnitSpec(filename, {'Type': 'SENLLA'}, ('authored-senlla-component.xml',), parameters)


class SENLLASurfaceTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.surface = SENLLASurface(self.spec)

    def view(self, **changes):
        values = {**self.spec.defaults(), **changes}
        before = copy.deepcopy(values)
        result = self.surface.view(values, identity=IDENTITY)
        self.assertEqual(values, before)
        return result.as_dict()

    def test_exact_profile_and_canonical_firmware_boundaries(self):
        for version in ('2.4.00', '2.4.01', '2.4.50', '2.4.99'):
            with self.subTest(version=version):
                self.assertEqual(check_profile('SENLLA', version, '5754PE'), ('SENLLA', version, '5754PE'))
        for identity in (('SENLL', '2.4.00', '5031PE'), ('SENPILLA', '2.4.00', '5753PEIRL'),
                         ('SENLLA', '2.3.99', '5754PE'), ('SENLLA', '2.5.00', '5754PE'),
                         ('SENLLA', '2.4.100', '5754PE'), ('SENLLA', '2.4.0', '5754PE'),
                         ('SENLLA', '2.4.000', '5754PE'), ('SENLLA', '2.4.00', 'SLC5754PE'),
                         ('SENLLA', '2.4.00', '5754pe'), ('SENLLA', None, '5754PE'),
                         ('SENLLA', True, '5754PE')):
            with self.subTest(identity=identity), self.assertRaises(SensorError):
                check_profile(*identity)
        for identity in (None, list(IDENTITY), IDENTITY[:2]):
            with self.subTest(identity=identity), self.assertRaises(SensorError):
                self.surface.view(self.spec.defaults(), identity=identity)

    def test_thirteen_independent_layouts_and_types(self):
        self.assertEqual(len(LAYOUTS), 13)
        self.assertEqual(dict(LAYOUTS), {name: (address, count, bits, bit, skip)
                                       for name, _kind, address, count, bits, bit, skip, _values in ROWS})
        self.assertEqual(BITS, {'LightLevelTargetGroupLevelStore', 'LightLevelMarginGroupLevelStore',
                               'BankSwitchGroupLevelStore'})
        with self.assertRaisesRegex(SensorError, 'SENLLA.xml'):
            SENLLASurface(fixture('SENLL_ST7.xml'))
        for name, parameter in self.spec.parameters.items():
            for field in ('Address', 'ArraySize', 'BitSize', 'BitAddress', 'ArraySkip'):
                fields = {**parameter.fields, field: str(int(parameter.fields[field]) + 1)}
                wrong = replace(parameter, fields=fields)
                spec = replace(self.spec, parameters={**self.spec.parameters, name: wrong})
                with self.subTest(name=name, field=field), self.assertRaisesRegex(SensorError, name):
                    SENLLASurface(spec)
            wrong_kind = 'int' if parameter.type == 'bit' else 'bit'
            wrong = replace(parameter, type=wrong_kind, fields={**parameter.fields, 'Type': wrong_kind})
            with self.subTest(name=name, field='Type'), self.assertRaisesRegex(SensorError, name):
                SENLLASurface(replace(self.spec, parameters={**self.spec.parameters, name: wrong}))

    def test_missing_or_invalid_raw_fields_refuse_without_input_mutation(self):
        for name in LAYOUTS:
            values = self.spec.defaults()
            del values[name]
            before = copy.deepcopy(values)
            with self.subTest(missing=name), self.assertRaisesRegex(SensorError, name):
                self.surface.view(values, identity=IDENTITY)
            self.assertEqual(values, before)
        for name, value in (
                ('LightLevelTargetGroup', -1), ('LightLevelTargetGroup', 256),
                ('PowerUpTargetGroupLevel', True), ('PowerUpTargetGroupLevel', 3.0),
                ('PECTargetLux', 'bad'), ('LightLevelMarginGroupLevelStore', 2),
                ('BankSwitchThresholdBehaviour', 4), ('BankSwitchGroupUsed', []),
                ('BankSwitchGroupUsed', [1] * 7), ('BankSwitchGroupUsed', [1] * 9),
                ('BankSwitchGroupUsed', [True] * 8), ('BankSwitchGroupUsed', [2] * 8)):
            values = {**self.spec.defaults(), name: value}
            before = copy.deepcopy(values)
            with self.subTest(name=name, value=value), self.assertRaisesRegex(SensorError, name):
                self.surface.view(values, identity=IDENTITY)
            self.assertEqual(values, before)

    def test_raw_numeric_spellings_preserve_the_original_consumed_values(self):
        result = self.view(PECTargetLux='0x28', PECMarginLux='$8', BankSwitchThresholdBehaviour='0b11',
                           BankSwitchThresholdGroup='31', BankSwitchGroupUsed='1 0 1 0 0 0 0 0')
        self.assertEqual(result['expected']['PECTargetLux'], [40])
        self.assertEqual(result['expected']['PECMarginLux'], [8])
        self.assertEqual(result['expected']['BankSwitchThresholdBehaviour'], [3])
        self.assertEqual(result['component_overlay']['BankSwitchThresholdBehaviour'], [2])

    def test_raw_unsigned_domain_survives_permissive_schema_ranges(self):
        for name, parameter in self.spec.parameters.items():
            permissive = replace(parameter, fields={**parameter.fields, 'MinValue': '-128', 'MaxValue': '4095'})
            spec = replace(self.spec, parameters={**self.spec.parameters, name: permissive})
            surface = SENLLASurface(spec)
            for number in (-1, 1 << parameter.bit_size):
                values = {**self.spec.defaults(), name: [number] * parameter.array_size}
                before = copy.deepcopy(values)
                with self.subTest(name=name, number=number), self.assertRaisesRegex(SensorError, name):
                    surface.view(values, identity=IDENTITY)
                self.assertEqual(values, before)

    def test_target_group_precedes_margin_group_and_copies_target_power(self):
        result = self.view(LightLevelTargetGroup='7', LightLevelMarginGroup='9',
                           LightLevelTargetGroupLevelStore='1', LightLevelMarginGroupLevelStore='0')
        loaded = result['loaded']
        self.assertEqual((loaded['target_group'], loaded['using_target_group'], loaded['target_byte']), (7, True, 45))
        self.assertEqual((loaded['margin_group'], loaded['using_margin_group'], loaded['margin_percent']), (255, False, 20))
        self.assertEqual(loaded['power_up']['margin'], {'state': 0, 'preset_level': 89})
        self.assertEqual(result['component_overlay'], {
            'LightLevelMarginGroup': [7], 'PECTargetLux': [200], 'PECMarginLux': [40],
            'LightLevelMarginGroupLevelStore': [1], 'PowerUpMarginGroupLevel': [13],
        })
        self.assertEqual(result['expected']['LightLevelMarginGroup'], [9])

    def test_independent_margin_group_loads_nine_and_serializes_target_byte(self):
        result = self.view(LightLevelMarginGroup='9', LightLevelMarginGroupLevelStore='1')
        self.assertEqual((result['loaded']['target_byte'], result['loaded']['margin_percent']), (40, 9))
        self.assertFalse(result['loaded']['using_target_group'])
        self.assertTrue(result['loaded']['using_margin_group'])
        self.assertEqual(result['component_overlay'], {'PECMarginLux': [40]})
        self.assertEqual(result['component_parameters']['PowerUpMarginGroupLevel'], [89])

    def test_unused_groups_clear_store_flags_but_preserve_all_presets(self):
        result = self.view(LightLevelTargetGroupLevelStore='1', LightLevelMarginGroupLevelStore='1',
                           BankSwitchGroupLevelStore='1')
        self.assertEqual(result['component_overlay'], {
            'LightLevelTargetGroupLevelStore': [0], 'LightLevelMarginGroupLevelStore': [0],
            'BankSwitchGroupLevelStore': [0],
        })
        self.assertEqual(result['loaded']['power_up'], {
            'target': {'state': 1, 'preset_level': 13},
            'margin': {'state': 1, 'preset_level': 89},
            'bank': {'state': 1, 'preset_level': 231},
        })
        for name, literal in (('PowerUpTargetGroupLevel', [13]), ('PowerUpMarginGroupLevel', [89]),
                              ('PowerUpBankSwitchGroupLevel', [231])):
            self.assertEqual(result['component_parameters'][name], literal)

    def test_power_state_uses_original_group_before_margin_precedence(self):
        for group, store, state in ((255, 0, 1), (255, 1, 1), (9, 0, 0), (9, 1, 1)):
            with self.subTest(group=group, store=store):
                result = self.view(LightLevelTargetGroup='7', LightLevelMarginGroup=str(group),
                                   LightLevelMarginGroupLevelStore=str(store))
                self.assertEqual(result['loaded']['margin_group'], 255)
                self.assertEqual(result['loaded']['power_up']['margin']['state'], state)
                self.assertEqual(result['component_parameters']['LightLevelMarginGroupLevelStore'], [0])
                self.assertEqual(result['component_parameters']['PowerUpMarginGroupLevel'], [13])

    def test_fixed_margin_roundtrip_uses_x87_and_all_raw_target_byte_values(self):
        for target, margin, percent, saved in ((0, 255, 0, 0), (3, 1, 33, 1), (40, 8, 20, 8),
                                               (50, 30, 60, 30), (75, 31, 41, 31),
                                               (150, 79, 53, 79), (190, 124, 65, 123),
                                               (255, 59, 23, 59)):
            with self.subTest(target=target, margin=margin):
                result = self.view(PECTargetLux=str(target), PECMarginLux=str(margin))
                self.assertEqual(result['loaded']['target_byte'], target)
                self.assertEqual(result['loaded']['margin_percent'], percent)
                self.assertEqual(result['component_parameters']['PECMarginLux'], [saved])
        # A component percentage above the form's usual100 is still admitted
        # when the source-derived serialized byte remains representable.
        result = self.view(LightLevelTargetGroup='7', PECTargetLux='4', PECMarginLux='5')
        self.assertEqual(result['loaded']['margin_percent'], 125)
        self.assertEqual(result['component_parameters']['PECMarginLux'], [250])

    def test_source_projection_outside_native_byte_refuses_without_clipping(self):
        for changes in ({'PECTargetLux': '200', 'PECMarginLux': '255'},
                        {'LightLevelTargetGroup': '7', 'PECTargetLux': '1', 'PECMarginLux': '255'}):
            values = {**self.spec.defaults(), **changes}
            before = copy.deepcopy(values)
            with self.subTest(changes=changes), self.assertRaisesRegex(SensorError, '0..255'):
                self.surface.view(values, identity=IDENTITY)
            self.assertEqual(values, before)

    def test_all_bank_behaviours_and_eight_usage_bits(self):
        for behaviour, low, high, saved in ((0, False, True, 2), (1, True, False, 1),
                                            (2, False, True, 2), (3, False, True, 2)):
            with self.subTest(behaviour=behaviour):
                result = self.view(BankSwitchThresholdBehaviour=str(behaviour), BankSwitchThresholdGroup='31',
                                   BankSwitchGroupUsed='1 0 1 0 0 0 0 0', BankSwitchGroupLevelStore='1')
                self.assertEqual(result['loaded']['use_low'], [low, False, low, False, False, False, False, False])
                self.assertEqual(result['loaded']['use_high'], [high, False, high, False, False, False, False, False])
                self.assertEqual(result['component_parameters']['BankSwitchThresholdBehaviour'], [saved])
                self.assertEqual(result['component_parameters']['BankSwitchThresholdGroup'], [31])
                self.assertEqual(result['component_parameters']['BankSwitchGroupUsed'], [1, 0, 1, 0, 0, 0, 0, 0])
                self.assertEqual(result['component_parameters']['BankSwitchGroupLevelStore'], [1])

    def test_unused_bank_group_or_no_usage_clears_usage_and_behaviour(self):
        for group, used in ((255, '1 1 1 1 1 1 1 1'), (31, '0 0 0 0 0 0 0 0')):
            with self.subTest(group=group):
                result = self.view(BankSwitchThresholdBehaviour='1', BankSwitchThresholdGroup=str(group),
                                   BankSwitchGroupUsed=used, BankSwitchGroupLevelStore='1')
                self.assertEqual(result['component_parameters']['BankSwitchThresholdBehaviour'], [0])
                self.assertEqual(result['component_parameters']['BankSwitchThresholdGroup'], [255])
                self.assertEqual(result['component_parameters']['BankSwitchGroupUsed'], [0] * 8)
                self.assertEqual(result['component_parameters']['BankSwitchGroupLevelStore'], [0])

    def test_bank_usage_does_not_consume_block_switch_active(self):
        current = {**self.spec.defaults(), 'BankSwitchThresholdGroup': '31', 'BankSwitchThresholdBehaviour': '3',
                   'BankSwitchGroupUsed': '1 0 1 0 0 0 0 0', 'BlockBankSwitchActive': '0 0 0 0 0 0 0 0'}
        before = copy.deepcopy(current)
        result = self.surface.view(current, identity=IDENTITY).as_dict()
        self.assertEqual(result['loaded']['use_high'], [True, False, True, False, False, False, False, False])
        self.assertEqual(current, before)
        self.assertNotIn('BlockBankSwitchActive', result['expected'])

    def test_logical_bank_serializer_low_then_high_precedence(self):
        low = [False, False, True, False, False, False, False, False]
        high = [False, False, False, False, True, False, False, False]
        values = logical_bank_usage_parameters(low_group=31, high_group=32, use_low=low, use_high=high)
        self.assertEqual(values, {'BankSwitchThresholdGroup': (32,), 'BankSwitchThresholdBehaviour': (2,),
                                  'BankSwitchGroupUsed': (0, 0, 1, 0, 1, 0, 0, 0)})
        for options in ({'low_group': 255}, {'high_group': 256}, {'use_low': low[:-1]}, {'use_high': [1] * 8}):
            with self.subTest(options=options), self.assertRaises(SensorError):
                logical_bank_usage_parameters(**{'low_group': 31, 'high_group': 32, 'use_low': low,
                                                   'use_high': high, **options})

    def test_logical_bank_level_vectors_are_explicit_and_independent_of_raw_loader(self):
        low = logical_bank_level_overlay(2, use_low=True, high_lux=1234)
        self.assertEqual(low['indexed_parameters'], {'LightLevelStore2': {2: 123}})
        high = logical_bank_level_overlay(2, use_high=True)
        self.assertEqual(high['indexed_parameters'], {'LightLevelStore1': {2: 255}})
        both = logical_bank_level_overlay(2, use_low=True, use_high=True, high_lux=1234)
        self.assertEqual(both['indexed_parameters'], {'LightLevelStore2': {2: 123}, 'LightLevelStore1': {2: 255}})
        for result in (low, high, both):
            self.assertTrue(result['logical_state_only'])
            self.assertFalse(result['raw_loader_binding_verified'] or result['complete_toolkit_save'] or result['saved'])
        for lux, byte in ((0, 0), (9, 0), (10, 1), (2550, 255)):
            with self.subTest(lux=lux):
                self.assertEqual(logical_bank_level_overlay(7, use_low=True, high_lux=lux)['indexed_parameters'],
                                 {'LightLevelStore2': {7: byte}})
        for index, options in ((-1, {}), (8, {}), (True, {}), (2, {'use_low': 1}),
                               (2, {'use_low': True}), (2, {'high_lux': 1234}),
                               (2, {'use_low': True, 'high_lux': -1}),
                               (2, {'use_low': True, 'high_lux': 2551}),
                               (2, {'use_low': True, 'high_lux': True})):
            with self.subTest(index=index, options=options), self.assertRaises(SensorError):
                logical_bank_level_overlay(index, **options)

    def test_current_level_display_literals_and_half_even_ties(self):
        for level, target, margin in ((0, 8, 0), (7, 62, 3), (23, 188, 9), (31, 250, 12),
                                      (95, 750, 38), (127, 1000, 50), (159, 1250, 62),
                                      (223, 1750, 88), (255, 2000, 100)):
            with self.subTest(level=level):
                self.assertEqual(display_target_lux(level), target)
                self.assertEqual(display_margin_percent(level), margin)
        for value in (-1, 256, True, 3.0, '3', None):
            for function in (display_target_lux, display_margin_percent):
                with self.subTest(value=value, function=function.__name__), self.assertRaises(SensorError):
                    function(value)

    def test_masked_component_bytes_preserve_unrelated_neighbours(self):
        result = self.surface.view({**self.spec.defaults(), 'LightLevelTargetGroup': '7',
                                   'LightLevelMarginGroup': '9', 'LightLevelTargetGroupLevelStore': '1',
                                   'BankSwitchThresholdBehaviour': '3', 'BankSwitchThresholdGroup': '31',
                                   'BankSwitchGroupUsed': '1 0 1 0 0 0 0 0'}, identity=IDENTITY)
        before = MemoryImage.from_bytes(b'\xc8' * 256)
        after = self.surface.codec.encode_many(result.component_overlay).apply(before)
        self.assertEqual(after.byte(22) & 0xc8, 0xc8)
        for address in (15, 23, 26, 29, 54, 66, 96, 104, 136, 152, 160, 162):
            self.assertEqual(after.byte(address), 0xc8, address)
        patch = self.surface.codec.encode_many({'BankSwitchGroupUsed': (1, 0, 1, 0, 0, 0, 0, 0)})
        result = patch.apply(MemoryImage.from_bytes(b'\xbf' * 256))
        self.assertEqual(result.read(72, 8), bytes([255, 191, 255, 191, 191, 191, 191, 191]))

    def test_eight_keys_scenes_global_and_all_unconsumed_inputs_are_untouched(self):
        current = {**self.spec.defaults(), 'LightLevelTargetGroup': '7', 'LightLevelMarginGroup': '9',
                   'JPCommand': [7, 13, 13, 13, 5, 5, 5, 5], 'SRCommand': [0, 7, 15, 15, 5, 5, 5, 5],
                   'LPCommand': [0, 7, 7, 0, 5, 5, 5, 5], 'LRCommand': [0, 0, 15, 15, 5, 5, 5, 5],
                   'BlockAllocation': [1, 2, 4, 8, 16, 32, 64, 128], 'SceneKeySelector': [1] * 8,
                   'SceneTablePointer': [0, 163, 163, 0, 255, 255, 255, 255],
                   'SceneTable': [20, 1, 20, 2, 255, 3, 30, 4] + [255] * 72,
                   'PatchEnable': [0, 0], 'StatusReportInterval': [0], 'opaque': {'data': ['retained']}}
        before = copy.deepcopy(current)
        result = self.surface.view(current, identity=IDENTITY).as_dict()
        self.assertEqual(current, before)
        self.assertEqual(set(result['expected']), set(LAYOUTS))
        self.assertEqual(result['runtime_input_key_count'], 8)
        self.assertEqual(result['consumed_parameter_count'], 13)
        self.assertFalse(result['complete_toolkit_save'] or result['saved'] or result['device_verified'])
        self.assertFalse(result['original_execution'] or result['physical_acceptance'])
        self.assertIn('global_initialization_and_save', result['excluded_pipelines'])
        self.assertTrue(result['read_only'])
        self.assertFalse(hasattr(self.surface, 'configure') or hasattr(self.surface, 'apply'))

    def test_view_is_deeply_detached_and_immutable(self):
        current = {**self.spec.defaults(), 'BankSwitchGroupUsed': [1, 0, 1, 0, 0, 0, 0, 0],
                   'BankSwitchThresholdGroup': [31]}
        view = self.surface.view(current, identity=IDENTITY)
        baseline = view.as_dict()
        current['BankSwitchGroupUsed'][0] = 0
        current['BankSwitchThresholdGroup'][0] = 32
        self.assertEqual(view.as_dict(), baseline)
        exported = view.as_dict()
        exported['expected']['BankSwitchGroupUsed'][0] = 0
        exported['loaded']['power_up']['target']['state'] = 0
        exported['component_parameters']['PECTargetLux'][0] = 100
        self.assertEqual(view.as_dict(), baseline)
        with self.assertRaises(TypeError):
            view.expected['PECTargetLux'] = (100,)
        with self.assertRaises(TypeError):
            view.loaded['power_up']['target']['state'] = 0
        with self.assertRaises(TypeError):
            view.loaded['use_high'][0] = False
        loaded = {'nested': {'flags': [True]}}
        detached = SurfaceView(IDENTITY, {'value': [1]}, loaded, {})
        loaded['nested']['flags'][0] = False
        self.assertEqual(detached.loaded['nested']['flags'], (True,))

    def test_schema_drift_after_construction_is_refused(self):
        self.spec.parameters['BankSwitchGroupUsed'].fields['BitAddress'] = '5'
        with self.assertRaisesRegex(SensorError, 'BankSwitchGroupUsed'):
            self.surface.view(self.spec.defaults(), identity=IDENTITY)


if __name__ == '__main__':
    unittest.main()
