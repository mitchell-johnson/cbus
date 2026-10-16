import json
import unittest
from dataclasses import FrozenInstanceError, astuple, replace
from pathlib import Path

from cbus_toolkit.senlla_banks import BankState
from cbus_toolkit.senlla_surface_banks import SurfaceBankResult, fresh_surface_banks
from cbus_toolkit.sensors import SensorError


def facts():
    path = Path(__file__).resolve().parents[1] / 'research/fixtures/senlla-surface-bank-source.json'
    return json.loads(path.read_text())


def banks():
    return [BankState(500, 100, True, True, False, 50, 10) for _ in range(8)]


def flags(*indices):
    return [index in indices for index in range(8)]


def literal_bank(vector):
    active, allowed, low, high, low_lux, high_lux, enable_off = vector
    return BankState(high_lux, low_lux, active, allowed, enable_off,
                     high_lux // 10, low_lux // 10), low, high


def literal_state(result, index):
    bank = result.banks[index]
    return [bank.switch_active, bank.switch_allowed, result.use_low[index], result.use_high[index],
            bank.low_lux, bank.high_lux, bank.enable_group_off]


class SurfaceBanksTest(unittest.TestCase):
    def test_source_receipt_is_numeric_and_static_only(self):
        source = facts()
        self.assertEqual(source['method_count'], 60)
        self.assertEqual(len(source['method_pins']), 60)
        self.assertEqual(source['source_receipts'], {
            'senlla-fresh-bank-frame-derived.json':
                '65f265670e210a8a4f427f451e61ddeab55f3cb03ee6ebaeac3eaa780290c6e1',
            'senlla-fresh-bank-layouts-derived.json':
                '95c1fe5cda6f4346dba620ec47e8c8fa93138cebb7ef927d3acc6b73aff07f63'})
        self.assertFalse(source['authority']['original_instruction_execution'])
        self.assertFalse(source['authority']['native_form_verified'])
        self.assertFalse(source['authority']['physical_acceptance'])
        self.assertFalse(source['frame']['actual_model_normalization']
                         ['fresh_surface_sets_Active_Allowed_or_maintenance_block'])
        self.assertFalse(source['frame']['maintenance_observer_admission']
                         ['actual_surface_maint_active_or_block_links_installed'])

    def test_exact_usage_and_radio_layouts(self):
        layouts = facts()['layouts']['decoded_effective_layouts']
        self.assertEqual(layouts['BankSwitchGroupUsed'], {
            'address': 72, 'array_size': 8, 'array_skip': 0, 'bit_address': 6, 'bit_size': 1})
        self.assertEqual(layouts['BlockGroupLogic'], {
            'address': 72, 'array_size': 8, 'array_skip': 0, 'bit_address': 4, 'bit_size': 1})
        self.assertEqual(layouts['BankSwitchThresholdBehaviour'], {
            'address': 22, 'array_size': 1, 'array_skip': 0, 'bit_address': 4, 'bit_size': 2})

    def test_four_independent_native_component_vectors(self):
        vectors = facts()['frame']['literal_vectors']
        self.assertEqual(len(vectors), 4)
        for vector in vectors:
            with self.subTest(vector=vector['id']):
                before, low, high = banks(), flags(), flags()
                supplied = vector.get('before_banks12', [vector.get('before_bank')])
                for index, raw in enumerate(supplied):
                    before[index], low[index], high[index] = literal_bank(raw)
                result = fresh_surface_banks(before, use_low=low, use_high=high)
                expected = vector.get('after_banks12', [vector.get('after_bank')])
                self.assertEqual([literal_state(result, i) for i in range(len(expected))], expected)
                self.assertEqual(result.banks[len(expected):], tuple(before[len(expected):]))

    def test_all_pair_positions_preserve_ascending_inactive_binding_order(self):
        for earlier in range(7):
            for later in range(earlier + 1, 8):
                with self.subTest(earlier=earlier, later=later):
                    before = banks()
                    before[earlier] = replace(before[earlier], switch_active=False)
                    before[later] = replace(before[later], switch_active=False)
                    result = fresh_surface_banks(before, use_low=flags(earlier, later),
                                                 use_high=flags(earlier, later))
                    self.assertEqual((result.banks[earlier].high_lux,
                                      result.banks[earlier].low_lux), (500, 100))
                    self.assertEqual((result.banks[later].high_lux,
                                      result.banks[later].low_lux), (2550, 0))
                    self.assertEqual((result.banks[later].store1,
                                      result.banks[later].store2), (255, 0))
                    self.assertEqual(result.use_low, (False,) * 8)
                    self.assertEqual(result.use_high, (False,) * 8)

    def test_allowed_false_preserves_active_and_use_flags(self):
        before = banks()
        before[0] = replace(before[0], switch_allowed=False, enable_group_off=True)
        result = fresh_surface_banks(before, use_low=flags(0), use_high=flags(0))
        self.assertEqual(astuple(result.banks[0]), (2550, 0, True, False, True, 255, 0))
        self.assertTrue(result.use_low[0])
        self.assertTrue(result.use_high[0])

    def test_final_global_pass_normalizes_all_active_used_rows(self):
        result = fresh_surface_banks(banks(), use_low=flags(0, 7), use_high=flags(1, 7))
        self.assertEqual([(result.banks[i].high_lux, result.banks[i].low_lux)
                          for i in (0, 1, 7)], [(2550, 100), (500, 0), (2550, 0)])
        self.assertEqual(result.banks[2:7], tuple(banks()[2:7]))

    def test_enable_group_off_is_preserved_without_radio_polarity_inversion(self):
        before = [replace(bank, enable_group_off=bool(i % 2)) for i, bank in enumerate(banks())]
        result = fresh_surface_banks(before, use_low=flags(0, 2), use_high=flags(1, 3))
        self.assertEqual([bank.enable_group_off for bank in result.banks],
                         [False, True, False, True, False, True, False, True])
        self.assertEqual(result.parameters()['BlockGroupLogic'], [0, 1, 0, 1, 0, 1, 0, 1])

    def test_equal_high_setter_preserves_explicit_stored_byte(self):
        before = banks()
        before[0] = replace(before[0], high_lux=2550, store1=17)
        result = fresh_surface_banks(before, use_low=flags(0), use_high=flags())
        self.assertIs(result.banks[0], before[0])
        self.assertEqual(result.parameters()['LightLevelStore1'][0], 17)
        self.assertEqual(result.save_overlay()['indexed_parameters'], {'LightLevelStore2': {0: 255}})

    def test_equal_low_setter_preserves_explicit_stored_byte(self):
        before = banks()
        before[0] = replace(before[0], low_lux=0, store2=99)
        result = fresh_surface_banks(before, use_low=flags(), use_high=flags(0))
        self.assertIs(result.banks[0], before[0])
        self.assertEqual(result.parameters()['LightLevelStore2'][0], 99)
        self.assertEqual(result.save_overlay()['indexed_parameters'], {'LightLevelStore1': {0: 255}})

    def test_unequal_setter_updates_only_corresponding_stored_byte(self):
        before = banks()
        before[0] = replace(before[0], store1=17, store2=99)
        result = fresh_surface_banks(before, use_low=flags(0), use_high=flags())
        self.assertEqual((result.banks[0].store1, result.banks[0].store2), (255, 99))

    def test_unused_inactive_banks_keep_all_supplied_state(self):
        before = [replace(bank, switch_active=False, switch_allowed=False,
                          store1=17, store2=99) for bank in banks()]
        result = fresh_surface_banks(before, use_low=flags(), use_high=flags())
        self.assertEqual(result.banks, tuple(before))
        self.assertTrue(all(actual is original for actual, original in zip(result.banks, before)))
        self.assertEqual(result.save_overlay()['indexed_parameters'], {})

    def test_literal_low_group_save_writes_high_lux_not_frame_low(self):
        before = banks()
        before[0] = replace(before[0], low_lux=0, store2=0)
        result = fresh_surface_banks(before, use_low=flags(0), use_high=flags())
        expected = facts()['literal_save_vectors'][0]
        self.assertEqual(result.parameters()['LightLevelStore1'],
                         expected['frame_parameters']['LightLevelStore1'])
        self.assertEqual(result.parameters()['LightLevelStore2'],
                         expected['frame_parameters']['LightLevelStore2'])
        self.assertEqual(result.banks[0].low_lux, 0)
        self.assertEqual(result.save_overlay()['indexed_parameters'], {'LightLevelStore2': {0: 255}})

    def test_literal_high_group_save_writes_255_at_only_used_index(self):
        result = fresh_surface_banks(banks(), use_low=flags(), use_high=flags(1))
        expected = facts()['literal_save_vectors'][1]
        self.assertEqual(result.parameters()['LightLevelStore1'],
                         expected['frame_parameters']['LightLevelStore1'])
        self.assertEqual(result.parameters()['LightLevelStore2'],
                         expected['frame_parameters']['LightLevelStore2'])
        self.assertEqual(result.save_overlay()['indexed_parameters'], {'LightLevelStore1': {1: 255}})

    def test_both_groups_produce_separate_indexed_save_writes(self):
        result = fresh_surface_banks(banks(), use_low=flags(7), use_high=flags(7))
        self.assertEqual((result.banks[7].high_lux, result.banks[7].low_lux), (2550, 0))
        self.assertEqual(result.save_overlay()['indexed_parameters'],
                         {'LightLevelStore2': {7: 255}, 'LightLevelStore1': {7: 255}})

    def test_usage_is_eight_bit_elements_and_global_group_behavior_are_excluded(self):
        result = fresh_surface_banks(banks(), use_low=flags(0, 7), use_high=flags(1, 7))
        parameters = result.parameters()
        self.assertEqual(parameters['BankSwitchGroupUsed'], [1, 1, 0, 0, 0, 0, 0, 1])
        self.assertEqual(set(parameters), {'LightLevelStore1', 'LightLevelStore2',
                                          'BlockBankSwitchActive', 'BlockGroupLogic',
                                          'BankSwitchGroupUsed'})
        self.assertFalse(result.as_dict()['complete_toolkit_save'])
        self.assertFalse(result.as_dict()['saved'])
        self.assertFalse(result.save_overlay()['raw_loader_binding_verified'])

    def test_inputs_and_nested_outputs_are_detached(self):
        before, low, high = banks(), flags(0), flags(1)
        result = fresh_surface_banks(before, use_low=low, use_high=high)
        before[0] = banks()[0]
        low[0] = False
        high[1] = False
        view = result.as_dict()
        view['banks'][0]['store1'] = 0
        view['use_low'][0] = False
        view['parameters']['BankSwitchGroupUsed'][0] = 0
        view['save_overlay']['indexed_parameters']['LightLevelStore2'][0] = 0
        self.assertEqual(result.banks[0].store1, 255)
        self.assertTrue(result.use_low[0])
        self.assertTrue(result.use_high[1])
        self.assertEqual(result.parameters()['BankSwitchGroupUsed'][0], 1)
        self.assertEqual(result.save_overlay()['indexed_parameters']['LightLevelStore2'][0], 255)
        with self.assertRaises(FrozenInstanceError):
            result.use_low = (False,) * 8

    def test_bank_count_type_and_byte_derived_lux_are_strict(self):
        for supplied in ([], banks()[:7], banks() + banks()[:1], [None] * 8, iter(banks())):
            with self.subTest(supplied=type(supplied).__name__), self.assertRaises(SensorError):
                fresh_surface_banks(supplied, use_low=flags(), use_high=flags())
        for name, value in (('high_lux', 501), ('low_lux', 101)):
            before = banks()
            before[0] = replace(before[0], **{name: value})
            with self.subTest(name=name), self.assertRaisesRegex(SensorError, 'multiples of ten'):
                fresh_surface_banks(before, use_low=flags(), use_high=flags())

    def test_boolean_array_domains_and_counts_are_strict(self):
        for name in ('use_low', 'use_high'):
            for supplied in ([], flags()[:7], flags() + [False], [0] * 8,
                             [1] * 8, ['false'] * 8, iter(flags())):
                options = {'use_low': flags(), 'use_high': flags(), name: supplied}
                with self.subTest(name=name, supplied=type(supplied).__name__), \
                        self.assertRaises(SensorError):
                    fresh_surface_banks(banks(), **options)

    def test_result_requires_immutable_tuple_boundaries(self):
        for index in range(3):
            values = [tuple(banks()), tuple(flags()), tuple(flags())]
            values[index] = list(values[index])
            with self.subTest(index=index), self.assertRaisesRegex(SensorError, 'immutable tuples'):
                SurfaceBankResult(*values)


if __name__ == '__main__':
    unittest.main()
