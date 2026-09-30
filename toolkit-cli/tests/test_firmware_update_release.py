"""Release faults must stop a journaled update without discarding verified images.

Real PyUSB runs only against the existing fake backend and synthetic memory peer.
No physical USB enumeration, device, vendor payload or network is used.
"""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import firmware_update_run as run
from cbus_toolkit.cli import main
from cbus_toolkit.dfu_simulator import FaultInjectingPeer, SimulatedProcessDeath
from tests.test_firmware_update_faults import (
    api, device, images, plan, sha, DESCRIPTOR, ERASE, EXTERNAL, FLASH, PACKAGE,
    PROGRAM, ReenumeratingBackend,
)
from tests.test_firmware_update_plan import PASSWORD

RELEASE_ERROR = 'injected interface release failure'


class ReleaseFaultTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.journal = self.folder / 'update.journal'
        self.clock = api._VirtualClock()

    def rig(self, release_number, *, cleanup_error=None, **fault):
        self.peer = device()
        self.faulty = FaultInjectingPeer(self.peer, **(fault or {
            'trigger': 'program-data', 'effect': 'disconnect', 'offset': 10**9}))
        self.backend = ReenumeratingBackend.create(self.faulty)
        release = self.backend.release_interface

        def fail_release(handle, interface):
            release(handle, interface)
            if self.backend.release_count == release_number:
                raise cleanup_error if cleanup_error is not None else OSError(RELEASE_ERROR)

        self.backend.release_interface = fail_release
        self.opener = run.USBDeviceOpener(bus=1, address=7, expected_serial='ABC123',
            descriptor=DESCRIPTOR, release_policy='reset-first-alternate', backend=self.backend)

    def options(self):
        return dict(opener=self.opener, clock=self.clock, sleep=self.clock.sleep)

    def update(self):
        return run.run_update(plan(), images(), journal_path=self.journal,
                              flash_size=FLASH, external_size=EXTERNAL, **self.options())

    def resume(self):
        return run.resume_update(self.journal, plan(), images(), **self.options())

    def counts(self):
        return (self.faulty.commands.get(ERASE, 0), self.faulty.commands.get(PROGRAM, 0))

    def test_acquisition_cleanup_failure_is_retained_in_initial_refusal_and_verifier(self):
        for operation in ('run', 'verify'):
            with self.subTest(operation=operation):
                self.rig(1)
                self.backend.alternate = 1  # Rejected after claim, before any DFU operation.
                before = (sha(self.peer.internal), sha(self.peer.external))
                result = (self.update() if operation == 'run' else
                          run.verify_device(plan(), images(), flash_size=FLASH,
                                            external_size=EXTERNAL, **self.options()))
                self.assertFalse(result['complete'])
                self.assertEqual(result['refusal_kind'], 'device-unavailable')
                self.assertFalse(result['cleanup_complete'])
                self.assertIn(RELEASE_ERROR, result['cleanup_error'])
                self.assertEqual(len(result['releases']), 1)
                self.assertFalse(result['releases'][0]['complete'])
                self.assertEqual((self.backend.release_count, self.backend.close_count), (1, 1))
                self.assertEqual(self.counts(), (0, 0))
                self.assertEqual((sha(self.peer.internal), sha(self.peer.external)), before)
                self.assertFalse(self.journal.exists())

    def test_later_acquisition_cleanup_failure_is_journaled_without_next_operation(self):
        self.rig(3)
        original = self.opener.open
        def fail_third_acquisition():
            if self.opener.opens == 2:
                self.backend.alternate = 1
            return original()
        self.opener.open = fail_third_acquisition
        result = self.update()
        self.assertFalse(result['complete'])
        self.assertFalse(result['cleanup_complete'])
        self.assertIn(RELEASE_ERROR, result['cleanup_error'])
        self.assertEqual(len(result['releases']), 3)
        self.assertEqual(self.counts(), (0, 0))
        self.assertEqual((self.backend.release_count, self.backend.close_count), (3, 3))
        doc, _ = run.load_journal(self.journal)
        self.assertEqual(doc['status'], 'interrupted')
        self.assertEqual(doc['stages'], {'font': 'erase-sent', 'main': 'pending'})
        self.assertIn(RELEASE_ERROR, doc['history'][-1]['detail']['cleanup_error'])
        self.assertFalse(doc['replay_authorized'])

    def test_resume_acquisition_cleanup_failure_preserves_verified_stages(self):
        self.rig(6)
        self.update()
        before = self.counts()
        original = self.backend.release_interface
        def fail_resume_acquisition_release(handle, interface):
            original(handle, interface)
            if self.backend.release_count == 7:
                raise OSError('resume ' + RELEASE_ERROR)
        self.backend.release_interface = fail_resume_acquisition_release
        self.backend.alternate = 1
        result = self.resume()
        self.assertFalse(result['complete'])
        self.assertEqual(result['refusal_kind'], 'device-unavailable')
        self.assertFalse(result['cleanup_complete'])
        self.assertIn('resume ' + RELEASE_ERROR, result['cleanup_error'])
        self.assertEqual(result['stages'], {'font': 'verified', 'main': 'verified'})
        self.assertEqual(self.counts(), before)
        self.assertEqual(len(result['releases']), 1)
        doc, _ = run.load_journal(self.journal)
        self.assertEqual(doc['stages'], result['stages'])
        self.assertIn('resume ' + RELEASE_ERROR, doc['history'][-1]['detail']['cleanup_error'])

    def test_acquisition_refusal_with_successful_cleanup_keeps_complete_receipt(self):
        self.rig(100)
        self.backend.alternate = 1
        result = self.update()
        self.assertFalse(result['complete'])
        self.assertEqual(result['refusal_kind'], 'device-unavailable')
        self.assertTrue(result['cleanup_complete'])
        self.assertIsNone(result['cleanup_error'])
        self.assertEqual(len(result['releases']), 1)
        self.assertTrue(result['releases'][0]['complete'])
        self.assertEqual(self.counts(), (0, 0))

    def test_final_release_failure_retains_verified_images_and_resume_only_reads(self):
        self.rig(6)
        result = self.update()
        self.assertFalse(result['complete'])
        self.assertFalse(result['cleanup_complete'])
        self.assertTrue(result['images_verified'])
        self.assertIn(RELEASE_ERROR, result['error'])
        self.assertIn(RELEASE_ERROR, result['cleanup_error'])
        self.assertEqual(result['status'], 'interrupted')
        self.assertEqual((result['failed_stage'], result['failed_phase']), ('main', 'verified'))
        self.assertEqual(result['stages'], {'font': 'verified', 'main': 'verified'})
        self.assertTrue(result['resume_required'])
        self.assertIn('readback', result['next_action'])
        self.assertTrue(result['operations'][-1]['complete'])  # Transfer evidence survives cleanup.
        self.assertFalse(result['operations'][-1]['release_complete'])
        self.assertTrue(result['releases'][-1]['state_after_release_unknown'])
        doc, _ = run.load_journal(self.journal)
        self.assertEqual((doc['status'], doc['stages']), ('interrupted', result['stages']))
        self.assertIn(RELEASE_ERROR, doc['history'][-1]['detail']['cleanup_error'])
        self.assertFalse(doc['replay_authorized'])
        before = (self.counts(), sha(self.peer.internal), sha(self.peer.external))
        resumed = self.resume()
        self.assertTrue(resumed['complete'], resumed['error'])
        self.assertTrue(resumed['cleanup_complete'])
        self.assertIsNone(resumed['restarted_stage'])
        self.assertEqual([row['operation'] for row in resumed['operations']],
                         ['inspect', 'inspect', 'verify', 'verify'])
        self.assertEqual((self.counts(), sha(self.peer.internal), sha(self.peer.external)), before)

    def test_each_earlier_release_failure_stops_before_the_next_operation(self):
        cases = [
            (1, (0, 0), {'font': 'pending', 'main': 'pending'}),
            (2, (0, 0), {'font': 'pending', 'main': 'pending'}),
            (3, (1, 0), {'font': 'erased', 'main': 'pending'}),
            (4, (1, 1), {'font': 'verified', 'main': 'pending'}),
            (5, (2, 1), {'font': 'verified', 'main': 'erased'}),
        ]
        for number, counts, stages in cases:
            with self.subTest(release=number):
                self.journal = self.folder / f'update-{number}.journal'
                self.rig(number)
                before = (sha(self.peer.internal), sha(self.peer.external))
                result = self.update()
                self.assertFalse(result['complete'])
                self.assertFalse(result['cleanup_complete'])
                self.assertIn(RELEASE_ERROR, result['error'])
                self.assertEqual(result['stages'], stages)
                self.assertEqual(self.counts(), counts)
                self.assertEqual(self.backend.release_count, number)
                self.assertEqual(len(result['operations']), number)
                self.assertEqual(result['journal_created'], number > 2)
                self.assertEqual(self.journal.exists(), number > 2)
                if number <= 2:
                    self.assertEqual(result['refusal_kind'], 'release-failed')
                    self.assertEqual((sha(self.peer.internal), sha(self.peer.external)), before)
                    self.assertFalse(result['resume_required'])
                else:
                    self.assertEqual(result['status'], 'interrupted')
                    self.assertEqual(run.load_journal(self.journal)[0]['stages'], stages)
                    resumed = self.resume()
                    self.assertTrue(resumed['complete'], resumed['error'])
                    # Erased-only images restart from erase; verified font is retained.
                    added = (2, 2) if number == 3 else (1, 1)
                    self.assertEqual(self.counts(), tuple(a + b for a, b in zip(counts, added)))

    def test_resume_release_failure_stops_inspection_and_reverification(self):
        for resume_release in (1, 2, 3, 4):
            with self.subTest(resume_release=resume_release):
                self.journal = self.folder / f'resume-{resume_release}.journal'
                self.rig(6)
                self.update()
                release = self.backend.release_interface

                def fail_resume(handle, interface):
                    release(handle, interface)
                    if self.backend.release_count == 6 + resume_release:
                        raise OSError('resume ' + RELEASE_ERROR)

                self.backend.release_interface = fail_resume
                before = self.counts()
                result = self.resume()
                self.assertFalse(result['complete'])
                self.assertEqual(result['refusal_kind'], 'release-failed')
                self.assertIn('resume ' + RELEASE_ERROR, result['error'])
                self.assertEqual(self.counts(), before)
                self.assertEqual(len(result['operations']), resume_release)
                self.assertEqual(result['stages'], {'font': 'verified', 'main': 'verified'})
                self.assertEqual(run.load_journal(self.journal)[0]['status'], 'interrupted')

    def test_read_only_verifier_reports_and_stops_on_release_failure(self):
        for release_number in (1, 3, 4):
            with self.subTest(release=release_number):
                self.journal = self.folder / f'verify-{release_number}.journal'
                self.rig(6 + release_number)
                self.assertTrue(self.update()['complete'])
                before = self.counts()
                result = run.verify_device(plan(), images(), flash_size=FLASH,
                                           external_size=EXTERNAL, **self.options())
                self.assertFalse(result['complete'])
                self.assertIn(RELEASE_ERROR, result['error'])
                self.assertFalse(result['cleanup_complete'])
                self.assertEqual(len(result['operations']), release_number)
                self.assertFalse(result['releases'][-1]['complete'])
                self.assertEqual(self.counts(), before)

    def test_resume_records_mismatch_even_when_reverify_release_fails(self):
        self.rig(6)
        self.update()
        self.peer.external[5] ^= 0xff
        release = self.backend.release_interface

        def fail_reverify(handle, interface):
            release(handle, interface)
            if self.backend.release_count == 9:
                raise OSError(RELEASE_ERROR)

        self.backend.release_interface = fail_reverify
        before = self.counts()
        result = self.resume()
        self.assertFalse(result['complete'])
        self.assertFalse(result['images_verified'])
        self.assertIn('mismatch', result['error'])  # Readback remains the primary failure.
        self.assertIn(RELEASE_ERROR, result['cleanup_error'])
        self.assertEqual(result['stages'], {'font': 'pending', 'main': 'verified'})
        self.assertEqual(run.load_journal(self.journal)[0]['stages'], result['stages'])
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.backend.release_count, 9)

    def test_transfer_error_remains_primary_when_release_also_fails(self):
        self.rig(3, trigger='erase', effect='hang', external=True)
        result = self.update()
        self.assertFalse(result['complete'])
        self.assertNotIn(RELEASE_ERROR, result['error'])
        self.assertIn(RELEASE_ERROR, result['cleanup_error'])
        self.assertEqual(result['error'], result['operations'][-1]['error'])
        self.assertEqual((result['failed_stage'], result['failed_phase']), ('font', 'erase-sent'))
        self.assertEqual(self.counts(), (1, 0))

    def test_primary_process_interruption_survives_cleanup_interruption(self):
        self.rig(6, cleanup_error=KeyboardInterrupt('cleanup interrupted'),
                 trigger='program-data', effect='crash', external=False, offset=10)
        with self.assertRaises(SimulatedProcessDeath) as caught:
            self.update()
        evidence = caught.exception.firmware_update_evidence
        self.assertEqual(evidence['release']['release_error'], 'cleanup interrupted')
        self.assertFalse(evidence['release']['complete'])
        self.assertEqual(self.backend.release_count, 6)
        doc, _ = run.load_journal(self.journal)
        self.assertEqual((doc['status'], doc['stages']['main']), ('in-progress', 'write-sent'))

    def test_cleanup_only_interruption_preserves_final_verification_for_resume(self):
        interruption = KeyboardInterrupt('cleanup interrupted')
        self.rig(6, cleanup_error=interruption)
        with self.assertRaises(KeyboardInterrupt) as caught:
            self.update()
        self.assertIs(caught.exception, interruption)
        self.assertTrue(interruption.firmware_update_evidence['transfer']['complete'])
        doc, _ = run.load_journal(self.journal)
        self.assertEqual(doc['status'], 'interrupted')
        self.assertEqual(doc['stages'], {'font': 'verified', 'main': 'verified'})
        before = self.counts()
        result = self.resume()
        self.assertTrue(result['complete'], result['error'])
        self.assertEqual(self.counts(), before)
        self.assertIsNone(result['restarted_stage'])

    def test_endpoint_failure_remains_primary_when_cleanup_interrupts(self):
        primary = RuntimeError('endpoint unavailable')
        self.rig(1, cleanup_error=SystemExit('cleanup interrupted'))
        with patch('cbus_toolkit.usb_dfu.ClaimedUSBSession.endpoint', side_effect=primary):
            with self.assertRaises(RuntimeError) as caught:
                self.update()
        self.assertIs(caught.exception, primary)
        self.assertEqual(primary.usb_release['release_error'], 'cleanup interrupted')
        self.assertFalse(primary.usb_release['complete'])
        self.assertEqual(self.backend.release_count, 1)
        self.assertEqual(self.counts(), (0, 0))
        self.assertFalse(self.journal.exists())

    def test_cli_returns_nonzero_for_final_release_failure(self):
        self.rig(6)
        (self.folder / 'password').write_bytes(PASSWORD)
        (self.folder / 'device.bin').write_bytes(api.SIMULATOR_DEVICE_DESCRIPTOR)
        (self.folder / 'config.bin').write_bytes(api.SIMULATOR_CONFIGURATION_DESCRIPTOR)
        argv = ['firmware', 'update-run', str(PACKAGE), '--journal', str(self.journal),
                '--package-password-file', str(self.folder / 'password'), '--bus', '1', '--address', '7',
                '--expected-serial', 'ABC123', '--device-descriptor', str(self.folder / 'device.bin'),
                '--configuration-descriptor', str(self.folder / 'config.bin'),
                '--release-policy', 'reset-first-alternate', '--variant', 'TivaPCI',
                '--flash-size', str(FLASH), '--external-size', str(EXTERNAL)]
        out, err = io.StringIO(), io.StringIO()
        with patch('usb.backend.libusb1.get_backend', return_value=self.backend), \
                redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
        self.assertEqual(code, 1, out.getvalue() + err.getvalue())
        result = json.loads(out.getvalue() or err.getvalue())
        self.assertFalse(result['complete'])
        self.assertTrue(result['images_verified'])
        self.assertIn(RELEASE_ERROR, result['error'])
        self.assertNotIn(PASSWORD.decode(), out.getvalue() + err.getvalue())


if __name__ == '__main__':
    unittest.main()
