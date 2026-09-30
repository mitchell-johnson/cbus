"""CLI package admission binds immutable bytes before any USB construction."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from cbus_toolkit import cli
from cbus_toolkit import firmware_diagnostics as diagnostics
from cbus_toolkit import firmware_update_plan as updater
from cbus_toolkit import firmware_update_run as runner
from test_firmware_update_faults import Rig


class PackageExecutionBindingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.path = self.folder / 'eDLTFirmware_1.7.0.zip'
        self.original = struct.pack('<II', 0x20008000, 0x4009) + b'\x42' * 24
        self.replacement = struct.pack('<II', 0x20008000, 0x4009) + b'\x77' * 24
        self.write_package(self.original)
        self.original_archive = self.path.read_bytes()
        (self.folder / 'password').write_bytes(b'synthetic-password')
        (self.folder / 'device.bin').write_bytes(updater.SIMULATOR_DEVICE_DESCRIPTOR)
        (self.folder / 'config.bin').write_bytes(updater.SIMULATOR_CONFIGURATION_DESCRIPTOR)

    def write_package(self, image):
        # Stored entries guarantee equal archive size despite different payloads.
        with zipfile.ZipFile(self.path, 'w', zipfile.ZIP_STORED) as archive:
            archive.writestr('main_hwv2.bin', image)
            archive.writestr('font.bin', b'\x12' * 32)

    def arguments(self, action):
        common = ['firmware', action, str(self.path), '--journal', str(self.folder / 'update.journal'),
                  '--package-password-file', str(self.folder / 'password'), '--bus', '1', '--address', '7',
                  '--device-descriptor', str(self.folder / 'device.bin'),
                  '--configuration-descriptor', str(self.folder / 'config.bin'),
                  '--release-policy', 'reset-first-alternate']
        if action == 'update-run':
            common += ['--expected-serial', 'ABC123', '--variant', 'TivaPCI', '--flash-size', '65536']
        return common

    def seed_resume_journal(self):
        plan = updater.update_plan(self.path, variant='TivaPCI')
        rig = Rig(self.folder, trigger='erase', effect='disconnect', erase_fraction=0.5)
        result = rig.run(update_plan=plan, update_images={'main_hwv2.bin': self.original})
        self.assertTrue(result['journal_created'], result)
        self.assertFalse(result['complete'])
        doc, raw = runner.load_journal(self.folder / 'update.journal')
        self.assertEqual(doc['binding']['package']['sha256'], hashlib.sha256(self.original_archive).hexdigest())
        self.assertEqual(runner.journal_plan_options(doc)['identity']['usb_serial'], 'ABC123')
        return doc, raw

    def invoke(self, action):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = cli.main(self.arguments(action))
        return status, out.getvalue(), err.getvalue()

    def assert_replacement_rejected(self, action):
        real_plan = updater.update_plan
        with ExitStack() as stack:
            opener = stack.enter_context(patch.object(runner, 'USBDeviceOpener'))
            run = stack.enter_context(patch.object(runner, 'run_update'))
            resume = stack.enter_context(patch.object(runner, 'resume_update'))
            decrypt = stack.enter_context(patch.object(updater, 'read_package_entries'))
            archive_readers = []
            plans = []

            def plan_then_replace(*args, **kwargs):
                plan = real_plan(*args, **kwargs)
                self.assertTrue(plan['supported'], plan['issues'])
                plans.append(plan)
                self.write_package(self.replacement)
                self.assertEqual(len(self.path.read_bytes()), len(self.original_archive))
                self.assertNotEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), plan['package']['sha256'])
                # Admission must compare the digest before directory parsing or decryption.
                archive_readers.append(stack.enter_context(patch.object(
                    diagnostics.zipfile, 'ZipFile', side_effect=AssertionError('archive initialized before admission'))))
                return plan

            stack.enter_context(patch.object(updater, 'update_plan', side_effect=plan_then_replace))
            status, output, error = self.invoke(action)
            self.assertNotEqual(status, 0, output + error)
            self.assertRegex(output + error, 'differ')
            self.assertEqual(len(plans), 1)
            decrypt.assert_not_called()
            for archive in archive_readers:
                archive.assert_not_called()
            opener.assert_not_called()
            run.assert_not_called()
            resume.assert_not_called()
            self.assertFalse((self.folder / 'update.journal').exists())

    def test_update_run_rejects_same_size_replacement_after_plan_before_archive_or_usb(self):
        self.assert_replacement_rejected('update-run')

    def assert_resume_admission_refused(self, digest_marker='unchanged', *, malformed_package=False, package_value=None):
        doc, _ = self.seed_resume_journal()
        if digest_marker == 'unchanged' and not malformed_package:
            self.write_package(self.replacement)
            self.assertEqual(len(self.path.read_bytes()), len(self.original_archive))
        else:
            if malformed_package:
                doc['binding']['package'] = package_value
            elif digest_marker is None:
                del doc['binding']['package']['sha256']
            else:
                doc['binding']['package']['sha256'] = digest_marker
            doc['attempt_id'] = runner.attempt_id(doc['binding'])
            (self.folder / 'update.journal').write_text(json.dumps(doc))
            runner.load_journal(self.folder / 'update.journal')
        before = (self.folder / 'update.journal').read_bytes()
        with ExitStack() as stack:
            guards = [stack.enter_context(patch.object(owner, name, side_effect=AssertionError(name + ' before admission')))
                      for owner, name in ((updater, 'update_plan'), (diagnostics.zipfile, 'ZipFile'),
                                          (updater, 'read_package_entries'), (runner, 'USBDeviceOpener'),
                                          (runner, 'resume_update'))]
            status, output, error = self.invoke('update-resume')
            self.assertNotEqual(status, 0, output + error)
            self.assertRegex(output + error, 'differ|digest|SHA|sha')
            for guard in guards:
                guard.assert_not_called()
        self.assertEqual((self.folder / 'update.journal').read_bytes(), before)

    def test_update_resume_rejects_same_size_package_changed_since_real_journal(self):
        self.assert_resume_admission_refused()

    def test_update_resume_rejects_missing_or_malformed_journal_digest_before_package_parser(self):
        for digest in (None, '', 'z' * 64, '0' * 63, 42):
            with self.subTest(digest=digest):
                journal = self.folder / 'update.journal'
                if journal.exists():
                    journal.unlink()
                self.assert_resume_admission_refused(digest)

    def test_update_resume_rejects_malformed_journal_package_before_package_parser(self):
        for package in (None, [], 'package', 42):
            with self.subTest(package=package):
                journal = self.folder / 'update.journal'
                if journal.exists():
                    journal.unlink()
                self.assert_resume_admission_refused(malformed_package=True, package_value=package)

    def assert_validated_snapshot_used(self, action, *, replace_path=True):
        if action == 'update-resume':
            self.seed_resume_journal()
        real_snapshot = updater.open_package_snapshot
        real_load = updater.load_selected_images
        real_plan = updater.update_plan
        snapshots, loads = [], []
        with ExitStack() as stack:
            opener = stack.enter_context(patch.object(runner, 'USBDeviceOpener'))
            run = stack.enter_context(patch.object(runner, 'run_update', return_value={'complete': True}))
            resume = stack.enter_context(patch.object(runner, 'resume_update', return_value={'complete': True}))

            def capture_then_replace(*args, **kwargs):
                if isinstance(args[0], diagnostics.PackageSnapshot):
                    snapshot = real_snapshot(*args, **kwargs)
                    self.assertIs(snapshot, snapshots[0])
                    return snapshot
                snapshot = real_snapshot(*args, **kwargs)
                self.assertEqual(kwargs['expected_sha256'], hashlib.sha256(self.original_archive).hexdigest())
                snapshots.append(snapshot)
                if replace_path:
                    self.write_package(self.replacement)
                return snapshot

            def load_snapshot(source, plan, password, **kwargs):
                self.assertIs(source, snapshots[0])
                self.assertIsInstance(source, diagnostics.PackageSnapshot)
                self.assertEqual(plan['package']['sha256'], hashlib.sha256(self.original_archive).hexdigest())
                images = real_load(source, plan, password, **kwargs)
                loads.append(images)
                return images

            def plan_then_arm_snapshot(*args, **kwargs):
                if action == 'update-resume':
                    self.assertIs(args[0], snapshots[0])
                plan = real_plan(*args, **kwargs)
                if action == 'update-run':
                    stack.enter_context(patch.object(updater, 'open_package_snapshot', side_effect=capture_then_replace))
                return plan

            if action == 'update-resume':
                stack.enter_context(patch.object(updater, 'open_package_snapshot', side_effect=capture_then_replace))

            stack.enter_context(patch.object(updater, 'update_plan', side_effect=plan_then_arm_snapshot))
            stack.enter_context(patch.object(updater, 'load_selected_images', side_effect=load_snapshot))
            status, output, error = self.invoke(action)
            self.assertEqual(status, 0, output + error)
            self.assertTrue(json.loads(output)['complete'])
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(loads, [{'main_hwv2.bin': self.original}])
            opener.assert_called_once()
            active, inactive = (run, resume) if action == 'update-run' else (resume, run)
            active.assert_called_once()
            inactive.assert_not_called()
            self.assertEqual(active.call_args.args[-1], loads[0])
            if replace_path:
                self.assertNotEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),
                                    hashlib.sha256(self.original_archive).hexdigest())
            else:
                self.assertEqual(self.path.read_bytes(), self.original_archive)

    def test_update_run_loads_exact_validated_snapshot_despite_later_path_replacement(self):
        self.assert_validated_snapshot_used('update-run')

    def test_update_resume_unchanged_package_uses_real_journal_selection_and_same_snapshot(self):
        self.assert_validated_snapshot_used('update-resume', replace_path=False)

    def test_update_resume_loads_exact_validated_snapshot_despite_later_path_replacement(self):
        self.assert_validated_snapshot_used('update-resume')


if __name__ == '__main__':
    unittest.main()
