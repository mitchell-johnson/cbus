"""Native clock/burden changes must agree with independent persisted PCI bytes."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import tempfile
import time
import unittest
from uuid import uuid4

from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.clocks import NativeClocks
from cbus_toolkit.cli import main
from cbus_toolkit.pci import PCIClient
from cbus_toolkit.programming import Programmer
from cbus_toolkit.simulator import PCISimulator

_spec = importlib.util.spec_from_file_location('clock_fixture', Path(__file__).resolve().parents[1] / 'research/clock_fixture.py')
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)


@unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST'), 'Set CBUS_CGATE_TEST_HOST for disposable native clock acceptance')
class NativeClockTests(unittest.TestCase):
    def test_clock_targets_burden_recovery_persistence_and_rejected_write(self):
        host = os.environ['CBUS_CGATE_TEST_HOST']
        port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        project = 'CLK' + uuid4().hex[:5].upper()
        network = f'//{project}/254'
        report = {'scope': 'Native clock and burden commissioning against explicit PCI.xml fixture; no electrical/arbitration claim',
                  'project': project, 'passed': False, 'commands': [], 'cli': [], 'cleanup_errors': []}
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'state.json'
                sim = _fixture.clock_simulator(state_path=path)
                with sim.running('0.0.0.0', 0) as (_, simulator_port), CGateClient(host, port, timeout=30) as client:
                    created = False
                    def command(text):
                        start = len(sim.wire_log)
                        try:
                            response = client.command(text)
                        except CGateError as error:
                            report['commands'].append({'command': text, 'lines': list(error.response.lines), 'wire_start': start, 'wire_end': len(sim.wire_log)})
                            raise
                        report['commands'].append({'command': text, 'lines': list(response.lines), 'wire_start': start, 'wire_end': len(sim.wire_log)})
                        return response
                    def cli(*args, expected=0):
                        output, errors = io.StringIO(), io.StringIO()
                        with redirect_stdout(output), redirect_stderr(errors):
                            result = main(['cgate', '--host', host, '--port', str(port), '--timeout', '30', *args])
                        report['cli'].append({'arguments': list(args), 'exit_status': result, 'output': output.getvalue(), 'errors': errors.getvalue()})
                        self.assertEqual(result, expected, errors.getvalue())
                        return json.loads(output.getvalue()) if output.getvalue() else None
                    def summary(expected):
                        reply = command('NET CLOCKS ' + network)
                        actual = {}
                        for line in reply.lines:
                            match = re.fullmatch(r'120-address=(\d+) output_units=1 clocks_enabled=(\d+) clocks_active=(\d+) burdens_enabled=(\d+)', line)
                            if match:
                                actual[int(match[1])] = tuple(int(match[i]) for i in (2, 3, 4))
                        self.assertEqual(actual, expected, reply.lines)
                        with PCIClient('127.0.0.1', simulator_port, local_unit=16) as peer:
                            for unit, (enabled, active, burden) in expected.items():
                                self.assertEqual(peer.recall(unit, 0x3e, 1), bytes([enabled | (burden << 6)]))
                                self.assertEqual(peer.identify(unit, 16)[0], enabled * 2 + active + burden * 128)
                        restored = PCISimulator(profile='synthetic', state_path=path)
                        self.assertEqual(restored.legacy_memory, sim.legacy_memory)
                    def set_field(unit, name, value):
                        cli('unit', '--lock-address', network, '--source', network + '/p/' + str(unit), 'set', name, str(value))
                        read = cli('unit', '--lock-address', network, '--source', network + '/p/' + str(unit), 'get', name)
                        self.assertEqual(read[name], str(value))
                    try:
                        command('PROJECT NEW ' + project); created = True
                        command('PROJECT USE ' + project)
                        command(f'DBSET //{project}/Project/Description cbus-toolkit-isolated-clock-acceptance-v1')
                        sim_host = os.environ.get('CBUS_CGATE_SIMULATOR_HOST', 'host.docker.internal')
                        command(f'DBCREATENET 254 Clocks Cni {sim_host}:{simulator_port}')
                        command('PROJECT SAVE ' + project)
                        command('NET LOAD DB ' + project)
                        command('NET OPEN ' + network)
                        deadline = time.monotonic() + 20
                        while not any('state=ok' in line for line in command('GET ' + network + ' state').lines):
                            self.assertLess(time.monotonic(), deadline, 'Clock fixture did not become healthy')
                            time.sleep(0.1)
                        summary({16: (1, 1, 0), 17: (0, 0, 0)})
                        changed = cli('network', 'clocks', network, '--target', '2')
                        self.assertTrue(changed['complete'])
                        self.assertEqual(changed['observed_enabled'], 2)
                        summary({16: (1, 1, 0), 17: (1, 0, 0)})
                        impossible = cli('network', 'clocks', network, '--target', '3', expected=1)
                        self.assertFalse(impossible['complete'])
                        self.assertEqual(impossible['observed_enabled'], 2)
                        summary({16: (1, 1, 0), 17: (1, 0, 0)})
                        cli('network', 'clocks', network, '--target', '1')
                        summary({16: (1, 1, 0), 17: (0, 0, 0)})
                        set_field(16, 'Burden', 1)
                        summary({16: (1, 1, 1), 17: (0, 0, 0)})
                        set_field(17, 'Burden', 1)
                        summary({16: (1, 1, 1), 17: (0, 0, 1)})
                        # Both enabled burdens remain visible; there is no
                        # invented firmware interlock or analogue load model.
                        set_field(17, 'Burden', 0)
                        set_field(16, 'ClockGenEnable', 0)
                        summary({16: (0, 0, 1), 17: (0, 0, 0)})
                        recovered = cli('network', 'clocks', network, '--recover')
                        self.assertTrue(recovered['complete'])
                        self.assertEqual(recovered['recovery_gateway'], 16)
                        self.assertIsNone(recovered['requested_enabled'])
                        summary({16: (1, 1, 1), 17: (0, 0, 0)})
                        set_field(16, 'Burden', 0)
                        # Native PP locks must prevent another field mutation.
                        lock = 'clocklock_' + uuid4().hex[:8]
                        programmer = Programmer(client)
                        programmer.lock(lock, network)
                        try:
                            cli('unit', '--lock-address', network, '--source', network + '/p/17', 'set', 'Burden', '1', expected=1)
                        finally:
                            programmer.unlock(lock)
                        summary({16: (1, 1, 0), 17: (0, 0, 0)})
                        # Force a real per-unit STORE rejection, preserving
                        # enabled state and proving final200 can hide failure.
                        sim.legacy_writable[17] = set()
                        before = len(sim.wire_log)
                        class RecordedClient:
                            def command(self, text):
                                return command(text)
                        outcome = NativeClocks(RecordedClient()).configure(network, 2)
                        reply = outcome.action_response
                        self.assertEqual(reply.code, 200)
                        self.assertTrue(any('could NOT be enabled' in line for line in reply.lines), reply.lines)
                        self.assertFalse(outcome.complete)
                        self.assertEqual(outcome.observed_enabled, 1)
                        rejected_cli = cli('network', 'clocks', network, '--target', '2', expected=1)
                        self.assertFalse(rejected_cli['complete'])
                        self.assertEqual(rejected_cli['observed_enabled'], 1)
                        rejected = [row for row in sim.wire_log[before:] if row.get('reason')]
                        self.assertTrue(rejected)
                        report['expected_rejections'] = rejected
                        sim.legacy_writable[17] = {0x3e}
                        sim._persist()
                        summary({16: (1, 1, 0), 17: (0, 0, 0)})
                        # All other requests in this bounded profile succeeded.
                        self.assertEqual([row for row in sim.wire_log if row.get('reason')], rejected)
                        report.update(passed=True, persisted=True, recovery_verified=True,
                                      burden_conflict_observable=True, programming_lock_conflict_rejected=True,
                                      final200_write_failure_observed=True, cli_rejected_native_partial_success=True,
                                      unachievable_clock_target_rejected=True)
                    finally:
                        report['wire'] = list(sim.wire_log)
                        if created:
                            for text in ('NET CLOSE ' + network, 'PROJECT CLOSE ' + project, 'PROJECT DELETE ' + project):
                                try:
                                    if not client.connected: client.connect()
                                    command(text)
                                except Exception as error:
                                    report['cleanup_errors'].append({'command': text, 'error': str(error)})
                            if report['passed']: self.assertEqual(report['cleanup_errors'], [])
        finally:
            if os.environ.get('CBUS_CLOCKS_REPORT'):
                target = Path(os.environ['CBUS_CLOCKS_REPORT'])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
