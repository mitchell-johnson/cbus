"""Lifecycle failure JSON retains bounded recovery evidence through fake USB."""
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.cli import main
from cbus_toolkit.firmware_update_cli import error_payload
from cbus_toolkit import firmware_update_run as runner
from cbus_toolkit.dfu_simulator import SimulatedProcessDeath
from tests import test_firmware_update_release as release_fixtures
from tests.test_firmware_update_faults import api, EXTERNAL, FLASH, PACKAGE
from tests.test_firmware_update_plan import PASSWORD


class FirmwareErrorCLITests(unittest.TestCase):
    def setUp(self):
        # Compose the existing fake-backend rig without inheriting its test cases.
        self.rig = release_fixtures.ReleaseFaultTests(methodName='runTest')
        self.rig.setUp(); self.addCleanup(self.rig.doCleanups)
        folder = self.rig.folder
        (folder / 'password').write_bytes(PASSWORD)
        (folder / 'device.bin').write_bytes(api.SIMULATOR_DEVICE_DESCRIPTOR)
        (folder / 'config.bin').write_bytes(api.SIMULATOR_CONFIGURATION_DESCRIPTOR)
        self.argv = ['firmware', 'update-run', str(PACKAGE), '--journal', str(self.rig.journal),
            '--package-password-file', str(folder / 'password'), '--bus', '1', '--address', '7',
            '--expected-serial', 'ABC123', '--device-descriptor', str(folder / 'device.bin'),
            '--configuration-descriptor', str(folder / 'config.bin'), '--release-policy',
            'reset-first-alternate', '--variant', 'TivaPCI', '--flash-size', str(FLASH),
            '--external-size', str(EXTERNAL)]

    def cli(self, *, status):
        out, err = io.StringIO(), io.StringIO()
        with patch('usb.backend.libusb1.get_backend', return_value=self.rig.backend), \
                redirect_stdout(out), redirect_stderr(err):
            code = main(self.argv)
        self.assertEqual(code, status, out.getvalue() + err.getvalue())
        self.assertEqual(out.getvalue(), '')
        self.assertNotIn(PASSWORD.decode(), err.getvalue())
        self.assertNotIn(str(self.rig.folder), err.getvalue())
        return json.loads(err.getvalue())

    def test_cleanup_interruption_exports_verified_transfer_and_persisted_phases(self):
        self.rig.rig(6, cleanup_error=KeyboardInterrupt('cleanup interrupted'))
        result = self.cli(status=130)
        self.assertEqual(result['error'], 'Interrupted')
        evidence = result['firmware_update_evidence']
        self.assertFalse(evidence['complete'])
        self.assertEqual((evidence['operation'], evidence['stage']), ('program', 'main'))
        self.assertTrue(evidence['transfer']['complete'])
        self.assertTrue(evidence['transfer']['peer_verified'])
        self.assertEqual(evidence['transfer']['expected_sha256'], evidence['transfer']['readback_sha256'])
        self.assertFalse(evidence['release']['complete'])
        self.assertEqual(evidence['release']['release_error'], 'USB release failed')
        self.assertEqual(evidence['journal']['status'], 'interrupted')
        self.assertEqual(evidence['journal']['stages'], {'font': 'verified', 'main': 'verified'})
        self.assertTrue(evidence['journal']['snapshot_only'])
        self.assertFalse(evidence['replay_authorized'])
        self.assertEqual(self.rig.counts(), (2, 2))
        self.assertEqual(self.rig.backend.release_count, 6)

    def test_primary_transfer_interruption_and_cleanup_error_both_survive_cli(self):
        self.rig.rig(6, trigger='program-data', effect='crash', external=False, offset=10)
        control = self.rig.backend.ctrl_transfer

        def interrupt(*args):
            try:
                return control(*args)
            except SimulatedProcessDeath:
                raise KeyboardInterrupt('primary transfer interruption')

        self.rig.backend.ctrl_transfer = interrupt
        result = self.cli(status=130)
        self.assertEqual(result['error'], 'Interrupted')
        evidence = result['firmware_update_evidence']
        self.assertFalse(evidence['transfer']['complete'])
        self.assertEqual(evidence['transfer']['stage'], 'program-data')
        self.assertEqual(evidence['transfer']['error'], 'Operation failed')
        self.assertEqual(evidence['release']['release_error'], 'USB release failed')
        self.assertEqual(evidence['journal']['stages'], {'font': 'verified', 'main': 'write-sent'})
        self.assertEqual(self.rig.counts(), (2, 2))
        self.assertEqual(self.rig.backend.release_count, 6)

    def test_endpoint_runtime_error_keeps_primary_and_acquisition_cleanup_receipt(self):
        primary = RuntimeError('endpoint unavailable')
        self.rig.rig(1, cleanup_error=KeyboardInterrupt('cleanup interrupted'))
        with patch('cbus_toolkit.usb_dfu.ClaimedUSBSession.endpoint', side_effect=primary):
            result = self.cli(status=1)
        self.assertEqual((result['error'], result['type']), ('endpoint unavailable', 'RuntimeError'))
        self.assertFalse(result['usb_release']['complete'])
        self.assertEqual(result['usb_release']['release_error'], 'USB release failed')
        self.assertFalse(result['firmware_update_evidence']['journal']['snapshot_available'])
        self.assertIsNone(result['firmware_update_evidence'].get('transfer'))
        self.assertEqual(self.rig.counts(), (0, 0))
        self.assertEqual(self.rig.backend.release_count, 1)
        self.assertFalse(self.rig.journal.exists())
        self.assertEqual(primary.usb_release['release_error'], 'cleanup interrupted')

    def test_runtime_operation_error_keeps_lifecycle_receipt_and_uncertain_journal_phase(self):
        primary = RuntimeError('client construction failed')
        self.rig.rig(3)
        constructor = runner.DFUClient.__init__
        calls = 0

        def fail_third(*args, **kwargs):
            nonlocal calls
            if args[1] is not None:  # Exclude pure preflight constructor validation.
                calls += 1
            if calls == 3:
                raise primary
            return constructor(*args, **kwargs)

        with patch.object(runner.DFUClient, '__init__', fail_third):
            result = self.cli(status=1)
        self.assertEqual((result['error'], result['type']), ('client construction failed', 'RuntimeError'))
        evidence = result['firmware_update_evidence']
        self.assertEqual((evidence['operation'], evidence['stage']), ('erase', 'font'))
        self.assertIsNone(evidence['transfer'])
        self.assertEqual(evidence['release']['release_error'], 'USB release failed')
        self.assertEqual(evidence['journal']['stages'], {'font': 'erase-sent', 'main': 'pending'})
        self.assertEqual(self.rig.counts(), (0, 0))
        self.assertEqual(self.rig.backend.release_count, 3)

    def test_acquisition_interruption_exports_exact_release_dataclass(self):
        primary = KeyboardInterrupt('acquisition interrupted')
        self.rig.rig(1)

        def interrupt(backend, fixture, row, response):
            if row['bmRequestType'] == 0x81:
                raise primary
            return response

        self.rig.backend.fault = interrupt
        result = self.cli(status=130)
        self.assertEqual(result['error'], 'Interrupted')
        self.assertFalse(result['usb_release']['complete'])
        self.assertEqual(result['usb_release']['release_error'], 'USB release failed')
        self.assertFalse(primary.usb_release.complete)
        self.assertEqual(self.rig.counts(), (0, 0))
        self.assertEqual(self.rig.backend.release_count, 1)
        self.assertFalse(self.rig.journal.exists())

    def test_resume_error_exports_existing_journal_without_replaying(self):
        self.rig.rig(6)
        self.rig.update()
        before = self.rig.counts()
        primary = RuntimeError('resume endpoint unavailable')
        # Resume has no variant or geometry flags; they come from the journal.
        self.argv = self.argv[:]
        self.argv[1] = 'update-resume'
        self.argv = self.argv[:-6]
        with patch('cbus_toolkit.usb_dfu.ClaimedUSBSession.endpoint', side_effect=primary):
            result = self.cli(status=1)
        self.assertEqual(result['error'], 'resume endpoint unavailable')
        snapshot = result['firmware_update_evidence']['journal']
        self.assertTrue(snapshot['snapshot_available'])
        self.assertEqual(snapshot['stages'], {'font': 'verified', 'main': 'verified'})
        self.assertEqual(self.rig.counts(), before)
        self.assertEqual(self.rig.backend.release_count, 7)


class FirmwarePayloadBoundsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.args = Namespace(area='firmware', action='update-run', journal=self.folder / 'journal')

    def test_each_backend_error_field_exports_only_fixed_failure_labels(self):
        expected = {'error': 'Operation failed', 'release_error': 'USB release failed',
                    'close_error': 'USB close failed', 'timing_error': 'USB release timing failed'}
        secret = 'PRIVATE_PASSWORD_SERIAL_AND_PATH/' + '\u2603' * 100000
        for location, fields in (('transfer', ('error',)), ('release', tuple(expected)),
                                 ('usb_release', tuple(expected))):
            for field in fields:
                with self.subTest(location=location, field=field):
                    error = RuntimeError('primary remains unchanged')
                    receipt = {field: secret}
                    if location == 'usb_release':
                        error.usb_release = receipt
                    else:
                        error.firmware_update_evidence = {location: receipt}
                    result = error_payload(error, self.args)
                    projected = (result['usb_release'] if location == 'usb_release'
                                 else result['firmware_update_evidence'][location])
                    self.assertEqual(projected[field], expected[field])
                    self.assertNotIn('PRIVATE_PASSWORD_SERIAL_AND_PATH', json.dumps(result))
                    self.assertLess(len(json.dumps(result)), 4096)
                    self.assertEqual(receipt[field], secret)

    def test_unrelated_errors_and_commands_keep_existing_cli_error_shape(self):
        for error, code, expected in ((RuntimeError('plain failure'), 1,
                {'error': 'plain failure', 'type': 'RuntimeError'}),
                (KeyboardInterrupt('plain interrupt'), 130, {'error': 'Interrupted'})):
            with self.subTest(error=type(error).__name__):
                out, err = io.StringIO(), io.StringIO()
                with patch('cbus_toolkit.cli.run', side_effect=error), redirect_stdout(out), redirect_stderr(err):
                    status = main(['coverage'])
                self.assertEqual(status, code)
                self.assertEqual(json.loads(err.getvalue()), expected)
                self.assertEqual(error_payload(error, self.args), {})
        error.firmware_update_evidence = {'operation': 'program', 'stage': 'main'}
        with patch('cbus_toolkit.firmware_update_run.load_journal') as loader:
            self.assertEqual(error_payload(error, Namespace(area='coverage')), {})
            self.assertEqual(error_payload(error, Namespace(area='firmware', action='update-plan')), {})
            loader.assert_not_called()

    def test_projection_excludes_secrets_payloads_private_paths_and_large_values(self):
        error = RuntimeError('primary')
        secret = 'PRIVATE_PASSWORD_OR_HOST_COORDINATE'
        error.firmware_update_evidence = {'operation': 'program', 'stage': 'main', 'password': secret,
            'journal_error': secret, 'transfer': {'complete': True, 'operation': 'program',
                'stage': 'complete', 'payload_transferred': 1125, 'readback_bytes': 1125,
                'expected_sha256': 'a' * 64, 'readback_sha256': 'a' * 64,
                'trace': [secret] * 10000, 'payload': secret, 'serial': secret, 'host': secret,
                'error': 'x' * 100000, 'length': True, 'address': -1, 'trace_rows': 2**200,
                'first_mismatch': None},
            'release': {'complete': False, 'release_policy': 'reset-first-alternate',
                'release_error': 'y' * 100000, 'close_error': {'secret': secret},
                'timing_error': [secret], 'elapsed_seconds': float('inf'), 'path': secret,
                'state_after_release_unknown': True}}
        result = error_payload(error, self.args)
        encoded = json.dumps(result)
        self.assertNotIn(secret, encoded)
        self.assertLess(len(encoded), 4096)
        evidence = result['firmware_update_evidence']
        self.assertEqual(evidence['transfer']['error'], 'Operation failed')
        self.assertEqual(evidence['release']['release_error'], 'USB release failed')
        self.assertNotIn('length', evidence['transfer'])
        self.assertNotIn('address', evidence['transfer'])
        self.assertNotIn('trace_rows', evidence['transfer'])
        self.assertNotIn('close_error', evidence['release'])
        self.assertNotIn('elapsed_seconds', evidence['release'])
        self.assertEqual(evidence['journal_error'], 'Journal persistence failed')
        self.assertEqual(error.firmware_update_evidence['journal_error'], secret)

    def test_bad_receipt_types_never_invoke_arbitrary_serializers(self):
        class Poison:
            def as_dict(self):
                raise AssertionError('must not serialize unknown receipt')

        error = RuntimeError('primary')
        error.usb_release = Poison()
        self.assertEqual(error_payload(error, self.args), {})
        error.firmware_update_evidence = {'transfer': {'stage': 'foreign', 'operation': 'foreign',
            'expected_sha256': 'z' * 64}, 'release': []}
        result = error_payload(error, self.args)['firmware_update_evidence']
        self.assertEqual(result['transfer'], {})
        self.assertIsNone(result['release'])

    def test_snapshot_failure_never_masks_primary_or_blocks_on_special_files(self):
        error = KeyboardInterrupt('primary')
        error.firmware_update_evidence = {'operation': 'inspect', 'stage': None, 'transfer': None,
                                         'release': {'complete': False, 'release_error': 'cleanup'}}
        paths = [self.folder / 'missing', self.folder / 'malformed', self.folder / 'symlink']
        paths[1].write_bytes(b'not JSON')
        paths[2].symlink_to(paths[1])
        if hasattr(os, 'mkfifo'):
            fifo = self.folder / 'fifo'; os.mkfifo(fifo); paths.append(fifo)
        for path in paths:
            with self.subTest(kind=path.name):
                self.args.journal = path
                result = error_payload(error, self.args)['firmware_update_evidence']
                self.assertFalse(result['journal']['snapshot_available'])
                self.assertEqual(result['release']['release_error'], 'USB release failed')
                self.assertNotIn(str(self.folder), json.dumps(result))
        with patch('cbus_toolkit.firmware_update_run.load_journal', side_effect=KeyboardInterrupt('secondary')):
            self.assertFalse(error_payload(error, self.args)['firmware_update_evidence']['journal']['snapshot_available'])


if __name__ == '__main__':
    unittest.main()
