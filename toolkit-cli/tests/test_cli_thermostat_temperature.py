from contextlib import redirect_stdout, redirect_stderr
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cbus_toolkit import cli, thermostat_temperature_cli as boundary
from cbus_toolkit.thermostat_temperature import METHODS


class ThermostatTemperatureCLITests(unittest.TestCase):
    def execute(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), patch('socket.create_connection', side_effect=AssertionError('Unexpected network')):
            code = cli.main(['thermostat-temperature', *args])
        return code, json.loads(stdout.getvalue() or stderr.getvalue())

    def test_method_listing_and_explicit_units_are_registered(self):
        code, result = self.execute(['methods'])
        self.assertEqual(code, 0); self.assertEqual(result['methods'], list(METHODS))
        for units, expected in (('celsius', 20), ('fahrenheit', 68)):
            code, result = self.execute(['convert', 'CGateTempToUnitTemp', '0', '--units', units])
            self.assertEqual(code, 0); self.assertEqual(result['result'], expected)
            self.assertEqual(result['units'], units); self.assertEqual(result['input'], 0)
            self.assertIn('scalar arithmetic only', result['scope'])

    def test_signed_bounds_and_preserved_original_wrap(self):
        for value in ('-2147483648', '2147483647', '-0', '0000000001'):
            code, result = self.execute(['convert', 'SimpleCGateTempToUnitTemp', value, '--units', 'celsius'])
            self.assertEqual(code, 0); self.assertEqual(result['result'], int(value))
        code, result = self.execute(['convert', 'WholeDegreesTempToCGateTemp', '1073741824', '--units', 'celsius'])
        self.assertEqual(code, 0); self.assertEqual(result['result'], 0)

    def test_invalid_grammar_missing_units_and_names_reject_before_conversion(self):
        wrong = [["convert", 'missing', '0', '--units', 'celsius'],
                 ['convert', METHODS[0], '0'], ['convert', METHODS[0], '0', '--units', 'C']]
        wrong += [['convert', METHODS[0], value, '--units', 'celsius'] for value in
                  ('2147483648', '-2147483649', '+1', '1.0', '1e2', '0x10', '１', '١', '1_0', ' 1', '1\n', '9'*10000)]
        for args in wrong:
            with redirect_stderr(io.StringIO()), patch.object(boundary, 'convert_temperature') as convert:
                with self.assertRaises(SystemExit) as error: cli.main(['thermostat-temperature', *args])
                self.assertEqual(error.exception.code, 2); convert.assert_not_called()

    def test_direct_boundary_validation_and_first_interruption(self):
        with self.assertRaises(ValueError): boundary.run(SimpleNamespace(area='wrong', action='methods'))
        with self.assertRaises(ValueError): boundary.run(SimpleNamespace(area='thermostat-temperature', action='wrong'))
        with patch.object(boundary, 'convert_temperature', side_effect=ValueError('input rejected')):
            code, result = self.execute(['convert', METHODS[0], '0', '--units', 'celsius'])
            self.assertEqual(code, 1); self.assertIn('input rejected', str(result))
        first = KeyboardInterrupt('interrupted')
        with patch.object(boundary, 'convert_temperature', side_effect=first):
            code, result = self.execute(['convert', METHODS[0], '0', '--units', 'celsius'])
            self.assertEqual(code, 130)


if __name__ == '__main__': unittest.main()
