"""Inherited SENLLA scalar literals; no owning unit, forms or device execution."""
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import unittest

from cbus_toolkit.senlla_st7_save import ST7SaveState
from cbus_toolkit.sensors import SensorError


SOURCE = Path(__file__).resolve().parents[1] / 'research/fixtures/senlla-inherited-scalars-source.json'


def load(levels=None, **changes):
    return ST7SaveState.load(list(range(10)) if levels is None else levels,
                            **{'pec_level_store': 0, 'pir_level_store': 0,
                               'pec_enable_off': 0, 'pir_enable_off': 0,
                               'broadcast_mode': 0, **changes})


class SENLLAST7SaveTests(unittest.TestCase):
    def test_independent_power_literals_for_both_slots(self):
        source = json.loads(SOURCE.read_text())
        self.assertEqual(len(source['method_pins']), 50)
        self.assertEqual(len(source['decoded_effective_layouts']), 93)
        for channel, index in (('pec', 9), ('pir', 8)):
            for vector in source['power_literals']:
                with self.subTest(channel=channel, vector=vector):
                    levels = list(range(10))
                    levels[index] = vector['raw_level']
                    loaded = load(levels, **{channel + '_level_store': int(vector['raw_store']),
                                           channel + '_enable_off': int(vector['raw_off'])})
                    state = loaded.light_power_state if channel == 'pec' else loaded.occupancy_power_state
                    self.assertEqual(state, vector['loaded_state'])
                    saved = loaded.parameters(**{'pec_enable_off': 0, 'pir_enable_off': 0,
                                                 channel + '_enable_off': int(vector['save_off'])})
                    self.assertEqual(saved['LightLevel'][index], vector['saved_level'])
                    self.assertEqual(saved['PECLevelStore' if channel == 'pec' else 'PIRLevelStore'],
                                     [int(vector['saved_store'])])

    def test_all_raw_levels_and_boolean_flags_capture_native_power_state(self):
        for level in range(256):
            for off in (0, 1):
                for store in (0, 1):
                    levels = [level] * 10
                    loaded = load(levels, pec_level_store=store, pir_level_store=store,
                                  pec_enable_off=off, pir_enable_off=off)
                    expected = 2 if store else (1 - off if level == 255 else off)
                    self.assertEqual((loaded.light_power_state, loaded.occupancy_power_state), (expected, expected))

    def test_captured_occupancy_state_survives_fresh_enable_off_clear(self):
        loaded = load([0] * 10, pir_enable_off=1)
        self.assertEqual(loaded.occupancy_power_state, 1)
        result = loaded.parameters(pec_enable_off=0, pir_enable_off=0)
        self.assertEqual(result['LightLevel'][8], 255)
        self.assertEqual(result['PIRLevelStore'], [0])
        self.assertEqual(loaded.light_levels[8], 0)

    def test_resume_preserves_each_raw_slot_independently(self):
        levels = [11, 22, 33, 44, 55, 66, 77, 88, 42, 123]
        loaded = load(levels, pec_level_store=1, pir_level_store=1,
                      pec_enable_off=1, pir_enable_off=1)
        result = loaded.parameters(pec_enable_off=0, pir_enable_off=0)
        self.assertEqual(result['LightLevel'], levels)
        self.assertEqual(result['PECLevelStore'], [1])
        self.assertEqual(result['PIRLevelStore'], [1])

    def test_eight_broadcast_modes_normalize_and_normal_save_clears_b_bank_flag(self):
        for vector in json.loads(SOURCE.read_text())['broadcast_literals']:
            with self.subTest(raw=vector['raw']):
                loaded = load(broadcast_mode=vector['raw'])
                self.assertEqual(loaded.broadcast_active, vector['loaded'])
                result = loaded.parameters(pec_enable_off=0, pir_enable_off=0)
                self.assertEqual(result['BroadcastActive'], [vector['saved']])
                self.assertEqual(result['PotentiometerBBankSwitchEnable'], [0])

    def test_arrays_are_detached_and_state_is_immutable(self):
        levels = list(range(10))
        loaded = load(levels)
        levels[0] = 255
        result = loaded.parameters(pec_enable_off=0, pir_enable_off=0)
        self.assertEqual(result['LightLevel'][:8], list(range(8)))
        result['LightLevel'][0] = 255
        self.assertEqual(loaded.light_levels[0], 0)
        with self.assertRaises(FrozenInstanceError):
            loaded.light_power_state = 2

    def test_invalid_raw_arrays_and_flag_domains_refuse(self):
        for levels in (None, [0] * 9, [0] * 11, [True] * 10, [-1] * 10, [256] * 10):
            with self.subTest(levels=levels), self.assertRaises(SensorError):
                ST7SaveState.load(levels, pec_level_store=0, pir_level_store=0,
                                  pec_enable_off=0, pir_enable_off=0, broadcast_mode=0)
        for name in ('pec_level_store', 'pir_level_store', 'pec_enable_off', 'pir_enable_off'):
            for value in (True, -1, 2):
                with self.subTest(name=name, value=value), self.assertRaises(SensorError):
                    load(**{name: value})
        for value in (True, -1, 8):
            with self.subTest(broadcast=value), self.assertRaises(SensorError):
                load(broadcast_mode=value)

    def test_invalid_explicit_states_and_current_logic_refuse(self):
        for values in ((True, 0, False), (3, 0, False), (0, -1, False), (0, 0, 1)):
            with self.subTest(values=values), self.assertRaises(SensorError):
                ST7SaveState([0] * 10, *values)
        loaded = load()
        for value in (True, -1, 2):
            for name in ('pec_enable_off', 'pir_enable_off'):
                with self.subTest(name=name, value=value), self.assertRaises(SensorError):
                    loaded.parameters(**{'pec_enable_off': 0, 'pir_enable_off': 0, name: value})


if __name__ == '__main__':
    unittest.main()
