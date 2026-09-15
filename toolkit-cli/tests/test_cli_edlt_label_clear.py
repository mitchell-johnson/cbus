"""CLI request intent, durable plan ordering and honest clear outcomes."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from cbus_toolkit import cli
from cbus_toolkit.cgate import CGateClient, CGateError
from tests.test_edlt_label_clear import ClearClient, NET, reply


class ContextClient(ClearClient):
    _close_preserving = CGateClient._close_preserving
    __exit__ = CGateClient.__exit__

    def __init__(self):
        super().__init__(); self.close_error = None

    def __enter__(self): return self

    def close(self):
        self.connected = False
        if self.close_error is not None: raise self.close_error


class LabelClearCLITests(unittest.TestCase):
    def invoke(self, args, status=0):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error): actual = cli.main(list(map(str, args)))
        self.assertEqual(actual, status, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def args(self, action='request', *extra):
        return ('cgate', 'edlt-label-clear', action, NET + '/p/5', '--serial', '101183.1666', *extra)

    def test_plan_only_refreshes_and_request_flushes_exclusive_plan_before_one_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            plan_path = Path(directory) / 'plan.json'; client = ContextClient()
            with patch('cbus_toolkit.cgate.CGateClient', return_value=client):
                plan = self.invoke(self.args('plan', '--plan-output', plan_path))
            self.assertEqual(json.loads(plan_path.read_text()), plan)
            self.assertFalse(plan['request_attempted']); self.assertTrue(any(c.startswith('NET SYNC ') for c in client.commands))
            self.assertFalse(any(c.startswith('LABEL ') for c in client.commands))
            request_path = Path(directory) / 'request.json'; client = ContextClient(); command = client.command; fsynced = []
            original_fsync = os.fsync
            def sync(descriptor):
                original_fsync(descriptor); fsynced.append(True)
            def request(text):
                if text.startswith('LABEL '):
                    self.assertTrue(fsynced)
                    self.assertEqual(json.loads(request_path.read_text())['native_command'], text)
                    self.assertFalse(json.loads(request_path.read_text())['request_attempted'])
                return command(text)
            client.command = request
            with patch('cbus_toolkit.cgate.CGateClient', return_value=client), patch.object(cli.os, 'fsync', side_effect=sync):
                result = self.invoke(self.args('request', '--plan-output', request_path))
            self.assertEqual(result['outcome'], 'native_accepted'); self.assertFalse(result['labels_cleared_verified'])
            self.assertEqual(sum(c.startswith('LABEL ') for c in client.commands), 1)
            self.assertEqual(client.commands[-1], 'LABEL CLEAREDLT ' + NET + '/p/5')

    def test_invalid_target_unknown_serial_and_output_preflight_do_not_connect(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Preflight must precede connection')):
            path = Path(directory) / 'exists'; path.write_text('original')
            self.assertIn('already exists', self.invoke(self.args('request', '--plan-output', path), status=1)['error'])
            self.assertEqual(path.read_text(), 'original')
            link = Path(directory) / 'broken'; link.symlink_to(Path(directory) / 'absent')
            self.assertIn('already exists', self.invoke(self.args('request', '--plan-output', link), status=1)['error'])
            self.assertIn('parent', self.invoke(self.args('request', '--plan-output', Path(directory) / 'missing' / 'plan'), status=1)['error'])
            self.assertIn('//PROJECT/NETWORK/p/UNIT', self.invoke(('cgate', 'edlt-label-clear', 'request', '/db' + NET + '/p/5', '--serial', '101183.1666'), status=1)['error'])
            self.assertIn('known', self.invoke(('cgate', 'edlt-label-clear', 'request', NET + '/p/5', '--serial', '0.0'), status=1)['error'])

    def test_plan_write_failure_does_not_attempt_clear(self):
        client = ContextClient()
        with tempfile.TemporaryDirectory() as directory, patch('cbus_toolkit.cgate.CGateClient', return_value=client), \
                patch.object(cli.os, 'fsync', side_effect=OSError('plan flush failed')):
            result = self.invoke(self.args('request', '--plan-output', Path(directory) / 'plan'), status=1)
        self.assertEqual(result['error'], 'plan flush failed')
        self.assertFalse(any(c.startswith('LABEL ') for c in client.commands))

    def test_native_rejection_and_lost_response_have_distinct_nonzero_outcomes(self):
        for failure, outcome in ((CGateError(reply('408 Control failed')), 'native_rejected'),
                                 (ConnectionError('lost clear reply'), 'outcome_uncertain')):
            client = ContextClient(); client.clear_exception = failure
            with patch('cbus_toolkit.cgate.CGateClient', return_value=client): result = self.invoke(self.args(), status=1)
            self.assertEqual(result['outcome'], outcome); self.assertTrue(result['device_side_effect_possible'])
            self.assertFalse(result['labels_cleared_verified']); self.assertFalse(result['database_updated'])
            self.assertEqual(client.commands[-1], 'LABEL CLEAREDLT ' + NET + '/p/5')
            self.assertEqual(sum(c.startswith('LABEL ') for c in client.commands), 1)
        failure = RuntimeError('C-Gate transport failed; connection closed; outcome may be unknown')
        failure.cgate_cleanup_errors = (KeyboardInterrupt('secondary transport close'),)
        client = ContextClient(); client.clear_exception = failure
        with patch('cbus_toolkit.cgate.CGateClient', return_value=client): result = self.invoke(self.args(), status=1)
        self.assertEqual(result['outcome'], 'outcome_uncertain'); self.assertEqual(result['cause'], str(failure))
        self.assertEqual(result['cgate_cleanup_errors'], [{'type': 'KeyboardInterrupt', 'error': 'secondary transport close'}])
        self.assertEqual(sum(c.startswith('LABEL ') for c in client.commands), 1)

    def test_first_interruption_and_secondary_close_retained_without_replay(self):
        client = ContextClient(); client.clear_exception = KeyboardInterrupt('first clear interruption')
        client.close_error = KeyboardInterrupt('secondary close interruption')
        with patch('cbus_toolkit.cgate.CGateClient', return_value=client): result = self.invoke(self.args(), status=130)
        evidence = result['edlt_label_clear_evidence']
        self.assertEqual(evidence['cause'], 'first clear interruption'); self.assertEqual(evidence['outcome'], 'outcome_uncertain')
        self.assertTrue(evidence['request_attempted']); self.assertEqual(evidence['automatic_retries'], 0)
        self.assertEqual(result['cgate_cleanup_errors'], [{'type': 'KeyboardInterrupt', 'error': 'secondary close interruption'}])
        self.assertEqual(client.commands[-1], 'LABEL CLEAREDLT ' + NET + '/p/5')
        self.assertEqual(sum(c.startswith('LABEL ') for c in client.commands), 1)

    def test_close_failure_after_native_acceptance_keeps_response_evidence(self):
        for failure, status in ((OSError('close failed'), 1), (KeyboardInterrupt('close interrupted'), 130)):
            client = ContextClient(); client.close_error = failure
            with patch('cbus_toolkit.cgate.CGateClient', return_value=client): result = self.invoke(self.args(), status=status)
            evidence = result['edlt_label_clear_evidence']
            self.assertEqual(evidence['outcome'], 'native_accepted'); self.assertEqual(evidence['reply'], ['200 OK.'])
            self.assertFalse(evidence['labels_cleared_verified']); self.assertFalse(evidence['label_persistence_verified'])
            self.assertEqual(sum(c.startswith('LABEL ') for c in client.commands), 1)

    @unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST'), 'Set isolated native C-Gate for label-clear CLI acceptance')
    def test_native_plan_request_receipt_separate_from_fixture_state(self):
        from cbus_toolkit.native import NativeDatabase, NativeProjects
        from cbus_toolkit.networks import NativeNetworks
        from cbus_toolkit.simulator_edlt_labels import EdltLabelClearFixture, LabelClearFault
        from tests.test_simulator_edlt_labels import fixture
        project = 'EL' + uuid4().hex[:6].upper(); network = '//' + project + '/254'; source = network + '/p/5'
        host = os.environ['CBUS_CGATE_TEST_HOST']; port = int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023'))
        def run(action, *extra, status=0):
            result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', 'cgate', '--host', host, '--port', str(port),
                '--timeout', '30', 'edlt-label-clear', action, source, '--serial', '101183.1666', *map(str, extra)],
                capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, status, result.stdout + result.stderr)
            return json.loads(result.stdout or result.stderr)
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'labels.json'; sim = fixture(state_path=state, response_delay=.01)
            with sim.running('0.0.0.0', 0) as (_, sim_port), CGateClient(host, port, timeout=30) as client:
                projects, database, networks = NativeProjects(client), NativeDatabase(client), NativeNetworks(client)
                projects.operation('new', project)
                try:
                    database.create_network(project, 254, 'Clear_CLI', 'Cni',
                        os.environ.get('CBUS_CGATE_SIMULATOR_HOST', 'host.docker.internal') + ':' + str(sim_port))
                    projects.operation('save', project); client.command('NET LOAD DB ' + project)
                    networks.open(network); networks.wait_ready(network, timeout=30)
                    for name, value in (('Retries', '0'), ('AutoUnravel', 'no'), ('AutoUpdate', 'no')):
                        client.command('SET ' + network + ' ' + name + ' ' + value)
                    before = sim.snapshot(); plan_path = Path(directory) / 'plan.json'
                    plan = run('plan', '--plan-output', plan_path)
                    self.assertEqual(json.loads(plan_path.read_text()), plan); self.assertEqual(sim.clear_operations, [])
                    for clear, response, status in ((False, 'ack', 0), (True, 'ack', 0), (False, 'negative', 1)):
                        sim.fault = LabelClearFault(clear, response); count = len(sim.clear_operations)
                        result = run('request', status=status)
                        self.assertEqual(result['outcome'], 'native_rejected' if status else 'native_accepted')
                        self.assertFalse(result['labels_cleared_verified']); self.assertFalse(result['strict_receipt_correlation_verified'])
                        self.assertEqual(len(sim.clear_operations), count + 1)
                        self.assertEqual(sim.unit_labels[5]['labels'], [] if clear else before['unit_labels']['5']['labels'])
                        self.assertEqual(sim.unit_labels[4], before['unit_labels']['4'])
                        self.assertEqual(EdltLabelClearFixture.from_state(state).snapshot(), sim.snapshot())
                        before = sim.snapshot()
                    runtime = Path(__file__).resolve().parents[1] / 'research/runtime'; runtime.mkdir(exist_ok=True)
                    (runtime / 'edlt-label-clear-cli-report.json').write_text(json.dumps({'passed': True,
                        'plan_persisted_before_request': True, 'native_ack_without_clear_observed': True,
                        'native_ack_with_fixture_clear_observed': True, 'native_rejection_exit_one': True,
                        'other_unit_unchanged': True, 'fixture_restart_equal': True,
                        'physical_device_verified': False, 'labels_cleared_verified': False}, indent=2) + '\n')
                finally:
                    if client.connected:
                        networks.close(network); projects.operation('close', project); projects.operation('delete', project)


if __name__ == '__main__': unittest.main()
