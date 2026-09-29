"""Toolkit Diagnostics dialog sequence: native replay, display rules and failures."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.cli import main
from cbus_toolkit.simulator import net_voltage_text, with_net_voltage
from cbus_toolkit.unit_diagnostics import DiagnosticsError, NetworkDiagnostics

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / 'research/fixtures/native-unit-diagnostics.json').read_text())
NETWORK = '//DIAGNOSE/254'
SESSION = re.compile(r'cbus_cli_[0-9a-f]{16}')


def _normalize(text):
    return SESSION.sub('<session>', text)


def _response(lines):
    return CGateResponse(tuple(lines), lines[-1], int(lines[-1][:3]))


class ReplayClient:
    """Serve exactly the recorded command/reply sequence, in order."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.sent = []

    def command(self, text):
        self.sent.append(text)
        if not self.rows:
            raise AssertionError('Unexpected extra command: ' + text)
        row = self.rows.pop(0)
        if _normalize(text) != row['command']:
            raise AssertionError(f'Expected {row["command"]!r}, sent {text!r}')
        if row['lines'] is None:
            raise RuntimeError('recorded transport failure')
        response = _response(row['lines'])
        if response.status >= 400:
            raise CGateError(response)
        return response

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _xml(units):
    body = ''.join(f'<Unit><Address>{address}</Address>'
                   + (f'<UnitType>{unit_type}</UnitType>' if unit_type else '') + '</Unit>'
                   for address, unit_type in units)
    return {'command': f'DBGETXML {NETWORK}',
            'lines': ['347-<Network><Address>254</Address>' + body + '</Network>', '344 End XML snippet']}


def _pingu(*addresses):
    return {'command': f'NET PINGU {NETWORK}',
            'lines': ['302-Units=' + ', '.join(map(str, addresses)), '200 OK.']}


def _clock_session(address, get_lines, load_lines=('200 OK.',)):
    return [
        {'command': 'PROJECT USE DIAGNOSE', 'lines': ['200 OK.']},
        {'command': f'PP LOCK <session>_lock {NETWORK}', 'lines': ['200 OK.']},
        {'command': 'PP START <session> <session>_lock', 'lines': ['200 OK.']},
        {'command': f'PP LOAD <session> {NETWORK}/p/{address}', 'lines': list(load_lines)},
        *([{'command': 'PP GET <session> ClockGenEnable', 'lines': list(get_lines)}] if get_lines else []),
        {'command': 'PP END <session>', 'lines': ['200 OK.']},
        {'command': 'PP UNLOCK <session>_lock', 'lines': ['200 OK.']},
    ]


class NativeReplayTests(unittest.TestCase):
    def test_both_native_passes_reproduce_the_retained_cli_results(self):
        self.assertEqual([row['label'] for row in FIXTURE['passes']], ['all-present', 'unit-17-detached'])
        for recorded in FIXTURE['passes']:
            expected = recorded['result']
            client = ReplayClient(expected['commands'])
            result = NetworkDiagnostics(client).diagnose(NETWORK).as_dict()
            self.assertEqual(client.rows, [])
            result['commands'] = [{**row, 'command': _normalize(row['command'])} for row in result['commands']]
            self.assertEqual(result, expected)
            self.assertEqual(recorded['exit_status'], 1)

    def test_native_pass_values_and_unknowns(self):
        present, detached = (row['result'] for row in FIXTURE['passes'])
        by_address = {row['address']: row for row in present['units']}
        self.assertEqual({address: row['voltage'] for address, row in by_address.items()},
                         {4: 31.0, 5: 31.5, 16: 31.8, 17: 30.7, 99: 'unknown'})
        self.assertEqual(by_address[16]['clock'], 'enabled')
        self.assertEqual(by_address[17]['burden'], 'enabled')
        self.assertEqual(by_address[5]['burden_basis'], 'toolkit-unit-type-rule')
        self.assertEqual(by_address[4]['clock_basis'], 'no-clockgenenable-parameter')
        self.assertEqual(by_address[99]['found'], 'not-found')
        pulled = {row['address']: row for row in detached['units']}[17]
        self.assertEqual((pulled['found'], pulled['voltage'], pulled['burden'], pulled['clock']),
                         ('not-found', 'unknown', 'unknown', 'unknown'))
        # Native keeps stale cached values for a pulled unit and fails Psync;
        # the CLI's unknown comes from PINGU absence, never from those values.
        probes = {row['command']: row['lines'] for row in FIXTURE['probes']}
        self.assertEqual(probes[f'GET {NETWORK}/p/17 NetVoltage'], [f'300 {NETWORK}/p/17: NetVoltage=30.7'])
        self.assertEqual(probes[f'DO {NETWORK}/p/17 Psync'], [f'408 Operation failed: {NETWORK}/p/17 ()'])
        self.assertEqual(probes[f'DO {NETWORK}/p/99 Psync'],
                         [f'401 Bad object or device ID: {NETWORK}/p/99 (Unit not found)'])
        self.assertFalse(any(row['command'].startswith(('GET', 'DO', 'PP LOAD')) and '/p/99' in row['command']
                             for row in present['commands']))

    def test_voltage_formula_matches_native_texts(self):
        from research.unit_diagnostics_fixture import NET_VOLTAGE_RAW, NET_VOLTAGE_TEXT
        for address, raw in NET_VOLTAGE_RAW.items():
            self.assertEqual(net_voltage_text(with_net_voltage(bytes(12), raw)), NET_VOLTAGE_TEXT[address])
        # The existing captured default identities decode to native-observed text.
        self.assertEqual(net_voltage_text(bytes.fromhex('38FFFFFFFF18B10616A20005')), '26.3')
        self.assertEqual(net_voltage_text(bytes.fromhex('FFFFFF000018B3F682A40001')), '26.6')
        self.assertEqual(net_voltage_text(bytes(12)), '0.5')
        with self.assertRaises(ValueError):
            net_voltage_text(bytes(11))

    def test_fixture_units_carry_chosen_voltage_bytes_and_can_be_detached(self):
        from research.unit_diagnostics_fixture import NET_VOLTAGE_TEXT, diagnostics_simulator
        sim = diagnostics_simulator()
        self.assertEqual({address: net_voltage_text(unit.attributes[4]) for address, unit in sim.units.items()},
                         NET_VOLTAGE_TEXT)
        self.assertEqual(sim._output_summary(sim.units[17])[0] & 0x80, 0x80)
        sim.detach_unit(17)
        self.assertNotIn(17, sim.units)
        for address in (16, 17, 256):
            with self.assertRaises(ValueError):
                sim.detach_unit(address)


class RuleTests(unittest.TestCase):
    def run_rows(self, rows, **options):
        client = ReplayClient(rows)
        result = NetworkDiagnostics(client).diagnose(NETWORK, **options)
        self.assertEqual(client.rows, [], 'unused scripted replies')
        return result, client

    def test_failures_are_unknown_and_never_zero(self):
        rows = [
            _xml([(4, 'KEYE1'), (16, 'PC_CNIED'), (30, 'RELDN12')]), _pingu(4, 16, 30),
            {'command': f'GET {NETWORK}/p/4 NetVoltage', 'lines': [f'300 {NETWORK}/p/4: NetVoltage=0.0']},
            {'command': f'GET {NETWORK}/p/16 NetVoltage',
             'lines': [f'401 Bad object or device ID: {NETWORK}/p/16 (Unit not found)']},
            {'command': f'GET {NETWORK}/p/30 NetVoltage', 'lines': [f'300 {NETWORK}/p/30: NetVoltage=-1']},
            {'command': f'DO {NETWORK}/p/4 Psync', 'lines': [f'408 Operation failed: {NETWORK}/p/4 ()']},
            {'command': f'DO {NETWORK}/p/16 Psync', 'lines': [f'202 Done: {NETWORK}/p/16']},
            {'command': f'GET {NETWORK}/p/16 BurdenActive', 'lines': [f'300 {NETWORK}/p/16: BurdenActive=maybe']},
            {'command': f'DO {NETWORK}/p/30 Psync', 'lines': [f'202 Done: {NETWORK}/p/30']},
            {'command': f'GET {NETWORK}/p/30 BurdenActive', 'lines': [f'300 {NETWORK}/p/30: BurdenActive=no']},
            *_clock_session(4, None, ('408 Operation failed: No such address',)),
            *_clock_session(16, ['408 Operation failed: Read failed']),
            *_clock_session(30, ['120-read 12/12', '315 ClockGenEnable=7']),
        ]
        result, client = self.run_rows(rows)
        values = {row.address: (row.voltage, row.burden, row.clock) for row in result.units}
        self.assertEqual(values, {4: ('unknown', 'unknown', 'unknown'),
                                  16: ('unknown', 'unknown', 'unknown'),
                                  30: ('unknown', 'not-enabled', 'unknown')})
        # Psync failure suppresses the BurdenActive read, like the original.
        self.assertNotIn(f'GET {NETWORK}/p/4 BurdenActive', client.sent)
        self.assertFalse(result.complete)
        self.assertEqual([error['step'] for error in result.units[0].errors], ['voltage', 'burden', 'clock-load'])

    def test_type_rule_units_issue_no_burden_or_clock_requests(self):
        rows = [_xml([(5, 'KEYGL5'), (7, 'SENTEMP4')]), _pingu(5, 7)]
        result, client = self.run_rows(rows, voltage=False)
        for row in result.units:
            self.assertEqual((row.voltage, row.burden, row.clock, row.burden_basis),
                             (None, 'not-enabled', 'not-enabled', 'toolkit-unit-type-rule'))
        self.assertEqual(len(client.sent), 2)
        self.assertTrue(result.complete)

    def test_type_rule_is_case_sensitive_like_the_original(self):
        rows = [_xml([(5, 'keygl5')]), _pingu(5),
                {'command': f'DO {NETWORK}/p/5 Psync', 'lines': [f'202 Done: {NETWORK}/p/5']},
                {'command': f'GET {NETWORK}/p/5 BurdenActive', 'lines': [f'300 {NETWORK}/p/5: BurdenActive=yes']}]
        result, _client = self.run_rows(rows, voltage=False, clock=False)
        self.assertEqual((result.units[0].burden, result.units[0].burden_basis), ('enabled', 'native-burdenactive'))

    def test_rescan_rows_selection_and_all_not_found(self):
        rows = [_xml([(4, 'KEYE1'), (9, 'KEYE1')]), _pingu(12)]
        result, client = self.run_rows(rows, units=[9])
        self.assertEqual([(row.address, row.found, row.voltage) for row in result.units], [(9, 'not-found', 'unknown')])
        self.assertEqual([(row.address, row.found, row.unit_type, row.clock) for row in result.rescan],
                         [(12, 'rescan-network', None, 'unknown')])
        self.assertFalse(result.all_units_not_found)
        rows = [_xml([(4, 'KEYE1')]), {'command': f'NET PINGU {NETWORK}', 'lines': ['302-Units=', '200 OK.']}]
        result, _client = self.run_rows(rows)
        self.assertTrue(result.all_units_not_found)
        self.assertFalse(result.complete)

    def test_invalid_inputs_stop_before_pingu(self):
        client = ReplayClient([_xml([(4, 'KEYE1')])])
        with self.assertRaisesRegex(DiagnosticsError, 'not in the network database: 5') as caught:
            NetworkDiagnostics(client).diagnose(NETWORK, units=[5])
        self.assertEqual(client.sent, [f'DBGETXML {NETWORK}'])
        self.assertEqual(len(caught.exception.commands), 1)
        for units in ([], [4, 4], [256], [True]):
            with self.assertRaises(ValueError):
                NetworkDiagnostics(ReplayClient([])).diagnose(NETWORK, units=units)
        with self.assertRaises(ValueError):
            NetworkDiagnostics(ReplayClient([])).diagnose('//DIAGNOSE/254/p/4')

    def test_malformed_pingu_and_transport_failure_stop_io(self):
        for lines in (['302-Units=5, 4', '200 OK.'], ['302-Units=04', '200 OK.'], ['200 OK.']):
            client = ReplayClient([_xml([(4, 'KEYE1')]), {'command': f'NET PINGU {NETWORK}', 'lines': lines}])
            with self.assertRaises(DiagnosticsError):
                NetworkDiagnostics(client).diagnose(NETWORK)
        client = ReplayClient([_xml([(4, 'KEYE1')]), _pingu(4),
                               {'command': f'GET {NETWORK}/p/4 NetVoltage', 'lines': None}])
        with self.assertRaisesRegex(RuntimeError, 'transport'):
            NetworkDiagnostics(client).diagnose(NETWORK)
        self.assertEqual(len(client.sent), 3)

    def test_cli_reports_json_and_nonzero_when_incomplete(self):
        expected = FIXTURE['passes'][0]['result']
        client = ReplayClient(expected['commands'])
        output, errors = io.StringIO(), io.StringIO()
        with patch('cbus_toolkit.cgate.CGateClient', return_value=client), \
                redirect_stdout(output), redirect_stderr(errors):
            status = main(['cgate', '--host', '127.0.0.1', '--port', '1', 'network', 'diagnose', NETWORK])
        self.assertEqual(status, 1, errors.getvalue())
        value = json.loads(output.getvalue())
        self.assertEqual(value['units'], expected['units'])
        self.assertIs(value['electrical_measurement_verified'], False)
        client = ReplayClient([_xml([(16, 'PC_CNIED')]), _pingu(16),
                               {'command': f'GET {NETWORK}/p/16 NetVoltage',
                                'lines': [f'300 {NETWORK}/p/16: NetVoltage=31.8']}])
        output = io.StringIO()
        with patch('cbus_toolkit.cgate.CGateClient', return_value=client), \
                redirect_stdout(output), redirect_stderr(io.StringIO()):
            status = main(['cgate', '--host', '127.0.0.1', '--port', '1', 'network', 'diagnose', NETWORK,
                           '--unit', '16', '--no-burden', '--no-clock'])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())['units'][0]['voltage'], 31.8)


@unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST'), 'Set CBUS_CGATE_TEST_HOST for disposable native diagnostics')
class NativeDiagnosticsTests(unittest.TestCase):
    def test_native_capture_reproduces_the_committed_fixture(self):
        from research.unit_diagnostics_native import _sanitize, run
        report = run(os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')),
                     os.environ.get('CBUS_CGATE_SIMULATOR_HOST', '127.0.0.1'),
                     os.environ.get('CBUS_CGATE_SIMULATOR_BIND', '127.0.0.1'))
        report = _sanitize(report, report.pop('simulator_port'))
        self.assertEqual(report['cleanup_errors'], [])
        for key in ('setup', 'passes', 'probes'):
            self.assertEqual(report[key], FIXTURE[key], key)


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'), 'Set CBUS_TOOLKIT_EXE (and MAP) for the static receipt')
class StaticReceiptTests(unittest.TestCase):
    def test_static_receipt_reproduces_the_committed_fixture(self):
        from research.unit_diagnostics_static import inspect
        exe = Path(os.environ['CBUS_TOOLKIT_EXE'])
        map_path = Path(os.environ.get('CBUS_TOOLKIT_MAP', exe.with_suffix('.map')))
        committed = json.loads((ROOT / 'research/fixtures/unit-diagnostics-static.json').read_text())
        self.assertEqual(json.loads(json.dumps(inspect(exe, map_path))), committed)


if __name__ == '__main__':
    unittest.main()
