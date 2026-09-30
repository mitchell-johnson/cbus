"""Acceptance producer integrity: retained failures and independent route scope."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from research.known_serial_journey_support import CLIRecorder, commissioning_fixture, digest
from tests.test_pci_selected_serial_routed import mmi, receipt, routed_co, routed_mmi_request
from tests.test_simulator_duplicate_addressing import A


class KnownSerialJourneyProducerTests(unittest.TestCase):
    def test_recorder_retains_exact_failed_command_before_raising(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = CLIRecorder('/explicit/python', Path(directory) / 'commands', cwd=directory,
                                   environment={'PINNED': 'value'})
            completed = subprocess.CompletedProcess([], 7, b'non-json\x00\xff\r\n', b'failure\r\n')
            with patch('research.known_serial_journey_support.subprocess.run', return_value=completed) as run:
                with self.assertRaisesRegex(AssertionError, 'returned 7'):
                    recorder.invoke(['serial-address', 'apply', 'plan.json'], expected=0, label='uncertain')
            run.assert_called_once_with(['/explicit/python', '-m', 'cbus_toolkit', 'serial-address', 'apply', 'plan.json'],
                                        cwd=Path(directory), env={'PINNED': 'value'}, capture_output=True, timeout=90)
            row = recorder.commands[0]
            self.assertEqual(bytes.fromhex(row['stdout_hex']), completed.stdout)
            self.assertEqual(Path(row['stdout']['path']).read_bytes(), completed.stdout)
            self.assertEqual(row['stdout']['sha256'], digest(row['stdout']['path']))
            self.assertEqual(Path(row['stderr']['path']).read_bytes(), completed.stderr)
            self.assertEqual(json.loads((Path(directory) / 'commands/000-command.json').read_text()), row)

    def test_recorder_retains_partial_timeout_outputs_and_no_success_status(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = CLIRecorder('/explicit/python', Path(directory) / 'commands', cwd=directory)
            failure = subprocess.TimeoutExpired(['command'], 2, output=b'partial stdout', stderr=b'partial stderr')
            with patch('research.known_serial_journey_support.subprocess.run', side_effect=failure):
                with self.assertRaisesRegex(AssertionError, 'returned None'):
                    recorder.invoke(['coverage'], timeout=2)
            self.assertIsNone(recorder.commands[0]['exit_status'])
            self.assertEqual(recorder.commands[0]['timeout_seconds'], 2)
            self.assertEqual(Path(recorder.commands[0]['stdout']['path']).read_bytes(), b'partial stdout')
            self.assertEqual(Path(recorder.commands[0]['stderr']['path']).read_bytes(), b'partial stderr')

    def test_routed_fixture_is_one_bridge252_single_address_and_bus_only(self):
        with tempfile.TemporaryDirectory() as directory:
            sim = commissioning_fixture('routed', directory)
            before = sim.snapshot()
            response, reason = sim._command(routed_mmi_request([252]).rstrip(b'\r'), {'header': None})
            self.assertEqual(response, b'g.' + mmi([252], {255: 2}))
            self.assertIsNone(reason)
            sim.acceptance_corrupt_receipt = True
            response, reason = sim._command(routed_co([252], A, 6).rstrip(b'\r'), {'header': None})
            self.assertEqual(response, b'g.' + receipt([252], 6, A) + b'XX\r\n')
            self.assertIsNone(reason)
            self.assertEqual(len(sim.co_operations), 1)
            self.assertEqual(sim.nodes[A].address, 6)
            self.assertEqual(sim.snapshot()['physical_nodes'][A]['parameters'], before['physical_nodes'][A]['parameters'])
            response, reason = sim._command(routed_co([253], A, 6).rstrip(b'\r'), {'header': None})
            self.assertEqual(response, b'g#')
            self.assertIsNotNone(reason)
            self.assertEqual(len(sim.co_operations), 1)
            self.assertEqual(sim._command(b'\\05FF002000g', {'header': None})[0], b'g#')


if __name__ == '__main__':
    unittest.main()
