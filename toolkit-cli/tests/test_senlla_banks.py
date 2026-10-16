"""Literal static-source bank vectors; no original instructions or device I/O."""
from dataclasses import FrozenInstanceError, astuple
import json
from pathlib import Path
import unittest

from cbus_toolkit.senlla_banks import BankState, bank_parameters
from cbus_toolkit.sensors import SensorError


FIXTURE = Path(__file__).resolve().parents[1] / 'research/fixtures/senlla-bank-transition-source.json'


class SENLLABankTests(unittest.TestCase):
    def test_twelve_literal_transition_vectors(self):
        facts = json.loads(FIXTURE.read_text())
        self.assertEqual(len(facts['method_pins']), 22)
        self.assertEqual(len(facts['literal_vectors']), 12)
        for vector in facts['literal_vectors']:
            with self.subTest(vector=vector['id']):
                state = BankState(*vector['before'])
                for kind, *args in vector['operations']:
                    if kind == 'refresh':
                        state = state.refresh_block(*args[:2], allowed=args[2])
                    else:
                        method = {'active': 'set_active', 'allowed': 'set_allowed',
                                  'high': 'set_high_lux', 'low': 'set_low_lux',
                                  'raw': 'load_active_and_enable_off'}[kind]
                        state = getattr(state, method)(*args)
                self.assertEqual(list(astuple(state)), vector['after'])

    def test_store_byte_rounding_literals(self):
        initial = BankState(100, 50, False, True, False, 10, 5)
        for lux, byte in ((0, 0), (1, 1), (9, 1), (10, 1), (11, 2),
                          (109, 11), (2541, 255), (2549, 255), (2550, 255)):
            with self.subTest(lux=lux):
                self.assertEqual(initial.set_high_lux(lux).store1, byte)
                self.assertEqual(initial.set_low_lux(lux).store2, byte)

    def test_all_raw_byte_levels_load_without_clipping_or_scale(self):
        initial = BankState(0, 0, False, True, False, 0, 0)
        for byte in range(256):
            state = initial.refresh_block(byte, 255 - byte, allowed=True)
            self.assertEqual((state.high_lux, state.low_lux), (byte * 10, (255 - byte) * 10))
            self.assertEqual((state.store1, state.store2), (byte, 255 - byte))

    def test_same_false_allowed_does_not_repair_active_state(self):
        initial = BankState(50, 50, True, False, True, 5, 5)
        self.assertIs(initial.set_allowed(False), initial)
        self.assertTrue(initial.set_allowed(True).switch_active)
        self.assertFalse(initial.set_allowed(True).set_allowed(False).switch_active)

    def test_integer_noops_do_not_rewrite_existing_store_bytes(self):
        initial = BankState(100, 50, False, True, False, 7, 9)
        self.assertIs(initial.set_high_lux(100), initial)
        self.assertIs(initial.set_low_lux(50), initial)

    def test_refresh_false_allowed_noop_leaves_active_ordering_enabled(self):
        initial = BankState(100, 100, True, False, False, 10, 10)
        result = initial.refresh_block(5, 20, allowed=False)
        self.assertEqual(astuple(result), (200, 200, True, False, False, 20, 20))

    def test_parameters_are_exact_eight_block_detached_arrays(self):
        banks = [BankState(10 * index, 0, bool(index % 2), False,
                           bool(index % 3), index, 0) for index in range(8)]
        result = bank_parameters(banks)
        self.assertEqual(result, {
            'LightLevelStore1': [0, 1, 2, 3, 4, 5, 6, 7], 'LightLevelStore2': [0] * 8,
            'BlockBankSwitchActive': [0, 1, 0, 1, 0, 1, 0, 1],
            'BlockGroupLogic': [0, 1, 1, 0, 1, 1, 0, 1]})
        result['LightLevelStore1'][0] = 255
        self.assertEqual(bank_parameters(banks)['LightLevelStore1'][0], 0)
        with self.assertRaises(FrozenInstanceError):
            banks[0].store1 = 255

    def test_invalid_state_domains_and_boolean_coercions_refuse(self):
        values = [100, 50, False, True, False, 10, 5]
        for index, candidates in ((0, (-1, 2551, True, 1.0)), (1, (-1, 2551)),
                                  (2, (0, 'false')), (3, (1, None)), (4, (0,)),
                                  (5, (-1, 256)), (6, (True, 1.0))):
            for value in candidates:
                with self.subTest(index=index, value=value), self.assertRaises(SensorError):
                    BankState(*[value if position == index else item for position, item in enumerate(values)])

    def test_invalid_operations_and_bank_counts_refuse(self):
        initial = BankState(100, 50, False, True, False, 10, 5)
        for method, value in (('set_active', 1), ('set_allowed', 'false'),
                              ('set_high_lux', 2551), ('set_low_lux', -1)):
            with self.subTest(method=method), self.assertRaises(SensorError):
                getattr(initial, method)(value)
        for args in ((True, 5, True), (10, 256, True), (10, 5, 1)):
            with self.subTest(args=args), self.assertRaises(SensorError):
                initial.refresh_block(*args[:2], allowed=args[2])
        with self.assertRaises(SensorError):
            initial.load_active_and_enable_off(True, 1)
        for banks in (None, [initial] * 7, [initial] * 9, [initial] * 7 + [object()]):
            with self.assertRaises(SensorError):
                bank_parameters(banks)


if __name__ == '__main__':
    unittest.main()
