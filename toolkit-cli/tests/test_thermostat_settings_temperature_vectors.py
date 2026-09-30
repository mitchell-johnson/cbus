"""Independent original arithmetic composition for all thermostat temperature bytes.

Expected values join captured original conversion observations with casts and
call sites recovered by thermostat_settings_temperature_static.py. Neither the
production rule table nor production arithmetic generates these expectations.
"""
import hashlib
import json
from pathlib import Path
import unittest

from cbus_toolkit.thermostat_post_load import form_save_temperatures

FIXTURES = Path(__file__).resolve().parents[1] / 'research/fixtures'
SOURCE_SHA = '188050a51a4324b0039dba68383a66d528baabcfe88210b3634ba1f372fd31d0'
FIELD_NAMES = {
    'MaximumSetTemperature', 'MinimumSetTemperature', 'GuardUpperTemperature',
    'GuardMaximumUpperTemperature', 'GuardMinimumUpperTemperature', 'GuardLowerTemperature',
    'GuardMaximumLowerTemperature', 'GuardMinimumLowerTemperature', 'SetbackLevel',
    'EvapStartProportionalTemperature', 'EvapStopProportionalTemperature', 'TemperatureOffset',
    'TemperatureSendDifferential', 'EvapComfortStartTemp', 'EvapComfortStepSize',
}


class ThermostatSettingsTemperatureVectorsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vectors = json.loads((FIXTURES / 'thermostat-settings-temperature-roundtrip-vectors.json').read_bytes())

    def test_expected_matrix_is_composed_from_captured_original_rows(self):
        raw = (FIXTURES / 'thermostat-temperature-vectors.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), SOURCE_SHA)
        self.assertEqual(self.vectors['source_fixture_sha256'], SOURCE_SHA)
        self.assertFalse(self.vectors['production_conversion_oracle_used'])
        self.assertEqual(set(self.vectors['fields']), FIELD_NAMES)
        original = json.loads(raw)
        observed = {}
        for index, fahrenheit, value, expected in (
                original['extended_original_emulator'] + original['native_windows_original']):
            key = (original['methods'][index], fahrenheit, value)
            if key in observed:
                self.assertEqual(observed[key], expected)
            observed[key] = expected
        for name, profile in self.vectors['profiles'].items():
            with self.subTest(profile=name):
                self.assertEqual(len(profile['rows']), 512)
                self.assertEqual({(row[0], row[1]) for row in profile['rows']},
                                 {(fahrenheit, raw) for fahrenheit in (False, True) for raw in range(256)})
                for fahrenheit, raw, loaded, converted, stored in profile['rows']:
                    incoming = raw - 256 if profile['signed_input'] and raw >= 128 else raw
                    self.assertEqual(loaded, observed[profile['load_method'], fahrenheit, incoming])
                    self.assertEqual(converted, observed[profile['save_method'], fahrenheit, loaded])
                    expected = min(converted, 127) if profile['upper_127_cap_after_save_conversion'] else converted
                    if profile['save_encoding'] == 'low_unsigned_byte':
                        expected &= 255
                    self.assertEqual(stored, expected)

    def test_all_fifteen_fields_all_bytes_both_preferences(self):
        expected_by_profile = {
            name: {(fahrenheit, raw): saved for fahrenheit, raw, _model, _converted, saved in profile['rows']}
            for name, profile in self.vectors['profiles'].items()
        }
        compared = 0
        for fahrenheit, units in ((False, 'celsius'), (True, 'fahrenheit')):
            for raw in range(256):
                with self.subTest(units=units, raw=raw):
                    values = dict.fromkeys(FIELD_NAMES, raw)
                    expected = {field: expected_by_profile[profile][fahrenheit, raw]
                                for field, profile in self.vectors['fields'].items()}
                    self.assertEqual(form_save_temperatures(values, temperature_preference=units), expected)
                    compared += len(expected)
        self.assertEqual(compared, 7680)

    def test_literal_signed_clamps_and_unsigned_overflow(self):
        values = dict.fromkeys(FIELD_NAMES, 0) | {
            'TemperatureOffset': 128, 'TemperatureSendDifferential': 128,
            'GuardUpperTemperature': 127, 'GuardMinimumUpperTemperature': 127,
            'EvapComfortStartTemp': 255, 'EvapComfortStepSize': 255,
        }
        saved = form_save_temperatures(values, temperature_preference='celsius')
        self.assertEqual(saved['TemperatureOffset'], 129)  # signed -128 -> -127 -> byte 129
        self.assertEqual(saved['TemperatureSendDifferential'], 127)  # unsigned +128
        self.assertEqual(saved['GuardUpperTemperature'], 127)
        self.assertEqual(saved['GuardMinimumUpperTemperature'], 128)  # no extra upper guard cap
        self.assertEqual(saved['EvapComfortStartTemp'], 256)  # caller must reject unrepresentable PP value
        self.assertEqual(saved['EvapComfortStepSize'], 256)


if __name__ == '__main__':
    unittest.main()
