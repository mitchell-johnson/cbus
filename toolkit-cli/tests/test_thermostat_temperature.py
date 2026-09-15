import decimal
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.thermostat_temperature import METHODS, convert_temperature

ROOT = Path(__file__).resolve().parents[1]


class ThermostatTemperatureTests(unittest.TestCase):
    def check_rows(self, key, count):
        vectors = json.loads((ROOT / 'research/fixtures/thermostat-temperature-vectors.json').read_text())
        self.assertEqual(tuple(vectors['methods']), METHODS)
        self.assertEqual(len(vectors[key]), count)
        for index, fahrenheit, value, expected in vectors[key]:
            actual = convert_temperature(METHODS[index], value, units='fahrenheit' if fahrenheit else 'celsius')
            if actual != expected:
                self.fail(str((METHODS[index], fahrenheit, value, actual, expected)))

    def test_all_1176_native_windows_original_values(self):
        self.check_rows('native_windows_original', 1176)

    def test_all_28840_extended_original_instruction_values(self):
        self.check_rows('extended_original_emulator', 28840)

    def test_original_integer_wrap_clamps_and_rounding_remain_visible(self):
        cases = [
            ('CGateTempToUnitTemp', 0, 'celsius', 20),
            ('CGateTempToUnitTemp', 0, 'fahrenheit', 68),
            ('UnitTempToCGateTemp', 20, 'celsius', 0),
            ('UnitTempToCGateTemp', -100, 'celsius', -127),
            ('WholeDegreesTempToCGateTemp', 1073741824, 'celsius', 0),
            ('QuarterDegreesTempOffsetToCGateTemp', 32, 'celsius', 127),
            ('QuarterDegreesTempOffsetToCGateTemp', 64, 'celsius', 255),
            ('QuarterDegreesTempOffsetToCGateTemp', -32, 'celsius', -127),
            ('CGateTempToWholeDegreesTemp', 2, 'celsius', 0),
            ('CGateTempToWholeDegreesTemp', 6, 'celsius', 2),
            ('CGateTempToWholeDegreesTemp', -6, 'celsius', -2),
        ]
        for method, value, units, expected in cases:
            with self.subTest(method=method, value=value):
                self.assertEqual(convert_temperature(method, value, units=units), expected)

    def test_exact_types_units_names_and_Int32_domain(self):
        class Integer(int): pass
        class Text(str): pass
        for value in (True, False, Integer(1), 1.0, '1', None, -(1 << 31)-1, 1 << 31, 10**1000):
            with self.assertRaises(ValueError):
                convert_temperature(METHODS[0], value, units='celsius')
        for method in (None, 0, Text(METHODS[0]), METHODS[0].lower(), 'missing', '', 'x'*100000):
            with self.assertRaises(ValueError):
                convert_temperature(method, 0, units='celsius')
        for units in (None, True, 0, Text('celsius'), 'C', 'F', 'Celsius', ''):
            with self.assertRaises(ValueError):
                convert_temperature(METHODS[0], 0, units=units)
        with self.assertRaises(TypeError):
            convert_temperature(METHODS[0], 0)

    def test_decimal_context_and_locale_or_IO_are_irrelevant(self):
        def forbidden(*args, **kwargs): raise AssertionError('Unexpected external access')
        with decimal.localcontext() as context:
            context.prec = 1
            context.rounding = decimal.ROUND_UP
            context.traps[decimal.Inexact] = True
            with patch('locale.localeconv', side_effect=forbidden), patch('builtins.open', side_effect=forbidden), \
                    patch('socket.create_connection', side_effect=forbidden), patch('os.getenv', side_effect=forbidden):
                self.assertEqual(convert_temperature('CGateTempToUnitTemp', 0, units='fahrenheit'), 68)
                self.assertEqual(convert_temperature('UnitTempToCGateTemp', 68, units='fahrenheit'), 0)

    def test_portable_module_runs_without_original_or_research_dependencies(self):
        import cbus_toolkit.thermostat_temperature as module
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / 'cbus_toolkit'; package.mkdir()
            (package / '__init__.py').write_text('')
            (package / 'thermostat_temperature.py').write_bytes(Path(module.__file__).read_bytes())
            script = ('import sys;sys.path.insert(0,sys.argv[1]);'
                      'from cbus_toolkit.thermostat_temperature import convert_temperature;'
                      'assert convert_temperature("CGateTempToUnitTemp",0,units="fahrenheit")==68;'
                      'assert not any(n.startswith(("research","unicorn","pefile")) for n in sys.modules)')
            result = subprocess.run([sys.executable, '-I', '-S', '-c', script, folder], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__': unittest.main()
