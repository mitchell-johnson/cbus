"""Toolkit preference runtime effects honored by the CLI, and their denominator receipt."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit.thermostat_temperature import METHODS, convert_temperature
from cbus_toolkit.toolkit_preferences_effects import cgate_site, temperature_units
from cbus_toolkit.toolkit_preferences_initial_state import constructor_state
from cbus_toolkit.toolkit_preferences_store import PREFERENCE_DEFINITIONS

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / 'research/experiments/2026-09-30/preference-runtime-consumers.json'
SCRIPT = ROOT / 'research/preference_runtime_consumers_static.py'

try:
    from test_rust_cgate_interop import MOCK_BIN
except ImportError:  # pragma: no cover - direct module execution
    MOCK_BIN = None


def _state(directory, **values):
    state = constructor_state()
    state['values'].update(values)
    path = Path(directory) / 'preferences.json'
    path.write_text(json.dumps(state), encoding='utf-8')
    return path


def _main(argv):
    stdout, stderr = io.StringIO(), io.StringIO()
    guard = patch('socket.create_connection', side_effect=AssertionError('Unexpected network'))
    with redirect_stdout(stdout), redirect_stderr(stderr), guard:
        code = cli.main(argv)
    return code, json.loads(stdout.getvalue() or stderr.getvalue())


class ReceiptTests(unittest.TestCase):
    def test_receipt_is_the_forty_preference_denominator(self):
        receipt = json.loads(RECEIPT.read_text(encoding='utf-8'))
        self.assertEqual(receipt['format'], 'cbus-toolkit-preference-runtime-consumers-v1')
        self.assertFalse(receipt['original_executed'])
        self.assertEqual(receipt['script_sha256'], hashlib.sha256(SCRIPT.read_bytes()).hexdigest())
        rows = receipt['preferences']
        self.assertEqual([row['name'] for row in rows], [spec.name for spec in PREFERENCE_DEFINITIONS])
        self.assertEqual({row['name'] for row in rows if row['status'] == 'cli-honored'},
                         {'TemperatureUnit', 'Default Site'})
        self.assertEqual(receipt['status_counts'],
                         {'cli-honored': 2, 'gui-only': 12, 'no-runtime-consumer': 3, 'not-implemented': 23})
        for row in rows:
            self.assertEqual(row['status'] == 'no-runtime-consumer', not row['runtime_consumers'], row['name'])
            self.assertTrue(row['cli'], row['name'])
            # Outside unit initializers every consumer goes through a .data pointer slot.
            self.assertEqual(len(row['direct_reference_owners']), 1, row['name'])
        self.assertTrue(all(receipt['checks'].values()))
        thermostat = {site['function'].rsplit('.', 1)[1] for site in rows[2]['sites']
                      if 'TCBusThermostatCGateAgent' in site['function']}
        self.assertEqual(thermostat, set(METHODS))
        self.assertNotIn('\\Users\\', RECEIPT.read_text(encoding='utf-8'))


class TemperatureUnitTests(unittest.TestCase):
    def test_low_byte_selects_units(self):
        cases = {0: 'celsius', 1: 'fahrenheit', 2: 'fahrenheit', 255: 'fahrenheit', 256: 'celsius',
                 257: 'fahrenheit', -1: 'fahrenheit', -256: 'celsius', -(2**31): 'celsius'}
        for value, expected in cases.items():
            self.assertEqual(temperature_units({'TemperatureUnit': value}), expected, value)
        with self.assertRaises(ValueError):
            temperature_units({'TemperatureUnit': True})

    def test_cli_honors_preference_state(self):
        with tempfile.TemporaryDirectory() as directory:
            for stored, units in ((0, 'celsius'), (1, 'fahrenheit'), (256, 'celsius')):
                path = _state(directory, TemperatureUnit=stored)
                code, result = _main(['thermostat-temperature', 'convert', 'CGateTempToUnitTemp', '0',
                                      '--preferences', str(path)])
                self.assertEqual(code, 0)
                self.assertEqual(result['units'], units)
                self.assertEqual(result['units_source']['value'], stored)
                self.assertEqual(result['result'], convert_temperature('CGateTempToUnitTemp', 0, units=units))
            code, result = _main(['thermostat-temperature', 'convert', METHODS[0], '0', '--units', 'celsius'])
            self.assertEqual((code, result['units_source']), (0, 'argument'))
            with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                cli.main(['thermostat-temperature', 'convert', METHODS[0], '0', '--units', 'celsius',
                          '--preferences', str(path)])
            bad = Path(directory) / 'bad.json'
            bad.write_text('{"format": "other"}', encoding='utf-8')
            code, result = _main(['thermostat-temperature', 'convert', METHODS[0], '0', '--preferences', str(bad)])
            self.assertEqual(code, 1)


class DefaultSiteTests(unittest.TestCase):
    def test_site_resolution(self):
        for site in ('', 'LOCAL', 'local', 'LoCaL'):
            self.assertEqual(cgate_site({'Default Site': site})['host'], '127.0.0.1', site)
        self.assertEqual(cgate_site({'Default Site': ''})['selected_site'], 'LOCAL')
        # SysUtils.UpperCase folds ASCII only; other names need the unmodelled site list.
        for site in ('ｌocal', 'LOCALHOST', 'Site 1', ' LOCAL', '127.0.0.1'):
            with self.assertRaises(ValueError):
                cgate_site({'Default Site': site})

    def test_named_site_without_host_stops_before_connecting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _state(directory, **{'Default Site': 'Plant room'})
            code, result = _main(['cgate', '--preferences', str(path), 'exec', 'NOOP'])
            self.assertEqual(code, 1)
            self.assertIn('pass --host', json.dumps(result))
            bad = Path(directory) / 'bad.json'
            bad.write_text('[]', encoding='utf-8')
            code, _ = _main(['cgate', '--host', '127.0.0.1', '--preferences', str(bad), 'exec', 'NOOP'])
            self.assertEqual(code, 1)


@unittest.skipUnless(MOCK_BIN, 'cgate-mock binary is not built')
class DefaultSiteCGateMockTests(unittest.TestCase):
    def setUp(self):
        self.process = subprocess.Popen([MOCK_BIN, '--bind', '127.0.0.1:0'], stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True)
        self.addCleanup(self._stop)
        match = re.fullmatch(r'cgate-mock listening on 127\.0\.0\.1:(\d+)\s*', self.process.stdout.readline(512))
        self.assertIsNotNone(match)
        self.port = match[1]

    def _stop(self):
        self.process.kill()
        self.process.wait(timeout=10)
        self.process.stdout.close()

    def run_cli(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(['--compact', 'cgate', '--port', self.port, '--timeout', '10', *argv])
        return code, json.loads(stdout.getvalue() or stderr.getvalue())

    def test_local_default_site_reaches_loopback_cgate(self):
        with tempfile.TemporaryDirectory() as directory:
            for site in ('', 'local'):
                path = _state(directory, **{'Default Site': site})
                code, result = self.run_cli('--preferences', str(path), 'exec', 'NOOP')
                self.assertEqual(code, 0, result)
                self.assertIn('200', json.dumps(result))

    def test_explicit_host_overrides_named_site(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _state(directory, **{'Default Site': 'Plant room'})
            code, result = self.run_cli('--preferences', str(path), 'exec', 'NOOP')
            self.assertEqual(code, 1)
            code, result = self.run_cli('--host', '127.0.0.1', '--preferences', str(path), 'exec', 'NOOP')
            self.assertEqual(code, 0, result)
            self.assertIn('200', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
