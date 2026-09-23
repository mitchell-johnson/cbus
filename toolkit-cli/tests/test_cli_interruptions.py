"""Cancellation after an observed fake move retains the saved CLI recovery plan."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.cli import main
from cbus_toolkit.physical_addressing import PhysicalAddressPlan
from tests.test_physical_addressing import NET, PhysicalClient


class InterruptedClient(PhysicalClient):
    def __init__(self, phase):
        super().__init__()
        self.phase = phase

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.connected = False

    def command(self, command):
        response = super().command(command)
        if ((self.phase == 'write' and command.startswith('SET ')) or
                (self.phase == 'preflight' and command == 'NET PINGU ' + NET)):
            raise KeyboardInterrupt
        return response


class CLIInterruptionTests(unittest.TestCase):
    def run_interrupted(self, client, path):
        out, err = io.StringIO(), io.StringIO()
        with patch('cbus_toolkit.cgate.CGateClient', return_value=client), redirect_stdout(out), redirect_stderr(err):
            status = main(['cgate', 'address', 'physical-readdress', NET + '/p/4', '6',
                           '--serial', '101136.1558', '--plan-output', str(path)])
        self.assertEqual(status, 130, out.getvalue() + err.getvalue())
        self.assertEqual(out.getvalue(), '')
        self.assertFalse(client.connected)
        return json.loads(err.getvalue())

    def test_interruption_after_write_keeps_saved_plan_and_emits_uncertain_evidence(self):
        client = InterruptedClient('write')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'recovery.json'
            result = self.run_interrupted(client, path)
            self.assertEqual(result['error'], 'Interrupted')
            self.assertEqual(result['outcome'], 'uncertain')
            self.assertTrue(result['write_attempted'])
            self.assertEqual(result['interruption_type'], 'KeyboardInterrupt')
            self.assertEqual(result['automatic_write_retries'], 0)
            self.assertEqual(json.loads(path.read_text()), result['plan'])
            self.assertEqual(PhysicalAddressPlan.from_dict(result['plan']).destination, NET + '/p/6')
        self.assertNotIn(4, client.units)
        self.assertEqual(client.units[6]['SerialNumber'], '101136.1558')
        self.assertEqual(sum(command.startswith('SET ') for command in client.commands), 1)
        self.assertEqual(client.commands[-1], 'SET ' + NET + '/p/4 Address 6')
        self.assertTrue(result['pre_write_mmi']['full_coverage'])

    def test_preflight_interruption_has_no_write_or_recovery_file(self):
        client = InterruptedClient('preflight')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'recovery.json'
            self.assertEqual(self.run_interrupted(client, path), {'error': 'Interrupted'})
            self.assertFalse(path.exists())
        self.assertIn(4, client.units)
        self.assertNotIn(6, client.units)
        self.assertFalse(any(command.startswith('SET ') for command in client.commands))


if __name__ == '__main__':
    unittest.main()
