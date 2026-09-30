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

    def resume_selection(self, stack):
        stack.enter_context(patch.object(runner, 'load_journal', return_value=({}, None)))
        stack.enter_context(patch.object(runner, 'journal_plan_options', return_value={
            'variant': 'TivaPCI', 'force_font': False, 'identity': {'usb_serial': 'ABC123'}}))

    def invoke(self, action):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = cli.main(self.arguments(action))
        return status, out.getvalue(), err.getvalue()

    def assert_replacement_rejected(self, action):
        real_plan = updater.update_plan
        with ExitStack() as stack:
            self.resume_selection(stack)
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

    def test_update_resume_rejects_same_size_replacement_after_plan_before_archive_or_usb(self):
        self.assert_replacement_rejected('update-resume')

    def assert_validated_snapshot_used(self, action):
        real_snapshot = updater.open_package_snapshot
        real_load = updater.load_selected_images
        real_plan = updater.update_plan
        snapshots, loads = [], []
        with ExitStack() as stack:
            self.resume_selection(stack)
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
                plan = real_plan(*args, **kwargs)
                stack.enter_context(patch.object(updater, 'open_package_snapshot', side_effect=capture_then_replace))
                return plan

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
            self.assertNotEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),
                                hashlib.sha256(self.original_archive).hexdigest())

    def test_update_run_loads_exact_validated_snapshot_despite_later_path_replacement(self):
        self.assert_validated_snapshot_used('update-run')

    def test_update_resume_loads_exact_validated_snapshot_despite_later_path_replacement(self):
        self.assert_validated_snapshot_used('update-resume')


if __name__ == '__main__':
    unittest.main()
