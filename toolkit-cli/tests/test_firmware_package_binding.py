"""Offline package substitutions and resource bounds; no device is opened."""
import copy
import hashlib
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile
import zlib

from cbus_toolkit import firmware_update_plan as api


def package(path, entries=None):
    if entries is None:
        entries = [('main_hwv2.bin', struct.pack('<II', 0x20008000, 0x4009) + b'\x42' * 24),
                   ('font.bin', b'\x12' * 32)]
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return path


def suffix_image(payload):
    data = payload + struct.pack('<HHHH3sB', 0x100, 0x501, 0x166a, 0x100, b'UFD', 16)
    return data + struct.pack('<I', zlib.crc32(data) ^ 0xffffffff)


class PackageBindingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = package(Path(self.directory.name, 'eDLTFirmware_1.7.0.zip'))

    def test_same_size_substitution_is_rejected_before_decryption(self):
        plan = api.update_plan(self.path, variant='TivaPCI')
        package(self.path, [('main_hwv2.bin', b'\x77' * 32), ('font.bin', b'\x12' * 32)])
        with patch.object(api, 'read_package_entries') as reader:
            with self.assertRaisesRegex(api.FirmwarePackageError, 'differ'):
                api.load_selected_images(self.path, plan, b'unused')
        reader.assert_not_called()

    def test_step_or_filename_version_substitution_is_rejected(self):
        plan = api.update_plan(self.path, variant='TivaPCI')
        changed = copy.deepcopy(plan)
        changed['dfuprog_steps'][-1]['address'] = 0x2000
        with self.assertRaisesRegex(api.FirmwarePackageError, 'differ'):
            api.load_selected_images(self.path, changed, b'unused')
        renamed = self.path.with_name('eDLTFirmware_1.8.0.zip')
        self.path.rename(renamed)
        with self.assertRaisesRegex(api.FirmwarePackageError, 'differ'):
            api.load_selected_images(renamed, plan, b'unused')

    def test_digest_is_checked_on_the_descriptor_before_entry_reads(self):
        with patch.object(zipfile.ZipFile, 'open', side_effect=AssertionError('decrypted')):
            with self.assertRaisesRegex(api.FirmwarePackageError, 'digest differs'):
                api.read_package_entries(self.path, b'unused', expected_sha256='0' * 64)

    def test_descriptor_digest_is_rechecked_after_entry_reads(self):
        real = api._package_digest
        calls = []

        def digest(stream):
            calls.append(stream.fileno())
            result = real(stream)
            return result if len(calls) == 1 else '0' * 64

        with patch.object(api, '_package_digest', side_effect=digest):
            with self.assertRaisesRegex(api.FirmwarePackageError, 'changed during'):
                api.read_package_entries(self.path, b'unused')
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])

    def test_mutate_then_restore_is_refused_even_with_unchanged_hash(self):
        original_digest = api._package_digest
        content = self.path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        initial = self.path.stat()

        def hash_and_restore(source):
            actual_digest = original_digest(source)
            with self.path.open('r+b') as output:
                output.seek(-1, 2)
                output.write(bytes([content[-1] ^ 1]))
                output.flush()
                output.seek(-1, 2)
                output.write(content[-1:])
            os.utime(self.path, ns=(initial.st_atime_ns, initial.st_mtime_ns))
            return actual_digest

        with patch.object(api, '_package_digest', new=hash_and_restore):
            with self.assertRaisesRegex(api.FirmwarePackageError, 'changed during'):
                api.read_package_entries(self.path, b'unused', expected_sha256=digest)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), digest)

    def test_inspection_is_bound_to_package_and_payload(self):
        plan = api.update_plan(self.path, variant='TivaPCI')
        inspection = api.inspect_package_images(self.path, b'unused')
        wrong = copy.deepcopy(inspection)
        wrong['sha256'] = '0' * 64
        with self.assertRaisesRegex(api.FirmwarePackageError, 'does not bind'):
            api.attach_image_inspection(plan, wrong)
        self.assertNotIn('image_inspection', plan)
        api.attach_image_inspection(plan, inspection)
        data = api.load_selected_images(self.path, plan, b'unused')
        self.assertEqual(list(data), ['main_hwv2.bin'])
        inspection['images'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(api.FirmwarePackageError, 'payload differs'):
            api.load_selected_images(self.path, plan, b'unused')

    def test_duplicate_entry_names_refused_before_any_plaintext_read(self):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            package(self.path, [('main_hwv2.bin', b'a'), ('main_hwv2.bin', b'b')])
        with patch.object(zipfile.ZipFile, 'open', side_effect=AssertionError('decrypted')):
            with self.assertRaisesRegex(api.FirmwarePackageError, 'Duplicate'):
                api.read_package_entries(self.path, b'unused')

    def test_missing_selection_and_aggregate_limit_precede_entry_reads(self):
        with patch.object(zipfile.ZipFile, 'open', side_effect=AssertionError('decrypted')):
            with self.assertRaisesRegex(api.FirmwarePackageError, 'missing'):
                api.read_package_entries(self.path, b'unused', names={'absent'})
            with patch.object(api, 'MAX_PACKAGE_PLAINTEXT', 63):
                with self.assertRaisesRegex(api.FirmwarePackageError, 'aggregate'):
                    api.read_package_entries(self.path, b'unused')
        with patch.object(api, 'MAX_PACKAGE_PLAINTEXT', 32):
            self.assertEqual(len(api.read_package_entries(self.path, b'unused', names={'font.bin'})['font.bin']), 32)

    def test_compressed_input_size_limit_and_special_file(self):
        with patch.object(api, 'MAX_PACKAGE_SIZE', 1):
            with self.assertRaisesRegex(api.FirmwarePackageError, 'input limit'):
                api.read_package_entries(self.path, b'unused')
        if hasattr(os, 'mkfifo'):
            fifo = self.path.with_name('fifo')
            os.mkfifo(fifo)
            with self.assertRaisesRegex(api.FirmwarePackageError, 'regular file'):
                api.read_package_entries(fifo, b'unused')

    def test_valid_container_is_offline_only_even_when_main_vectors_look_raw(self):
        raw = struct.pack('<II', 0x20008000, 0x4009) + b'\x42' * 24
        wrapped = suffix_image(raw)
        package(self.path, [('main_hwv2.bin', wrapped), ('font.bin', b'font')])
        plan = api.update_plan(self.path, variant='TivaPCI')
        with self.assertRaisesRegex(api.FirmwarePackageError, 'offline payload planner'):
            api.load_selected_images(self.path, plan, b'unused')
        images = api.load_selected_images(self.path, plan, b'unused', allow_containers=True)
        self.assertEqual(images['main_hwv2.bin'], wrapped)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), plan['package']['sha256'])

    def test_simulator_strips_suffix_and_uses_ti_override_address(self):
        raw = struct.pack('<II', 0x20008000, 0x5009) + b'\x42' * 24
        prefix = struct.pack('<BBHI', 1, 0, 0x5000 // 1024, len(raw))
        wrapped = suffix_image(prefix + raw)
        package(self.path, [('main_hwv2.bin', wrapped), ('font.bin', b'font')])
        plan = api.update_plan(self.path, variant='TivaPCI')
        images = api.load_selected_images(self.path, plan, b'unused', allow_containers=True)
        result = api.simulate_plan(plan, images)
        self.assertTrue(result['complete'])
        region = result['regions']['main-write']
        self.assertEqual((region['address'], region['bytes']), (0x5000, len(raw)))
        self.assertTrue(region['matches_payload'])
        self.assertFalse(region['matches_image'])
        self.assertEqual(region['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertFalse(result['physical_device_verified'])
        inspected = api.inspect_package_images(self.path, b'unused')
        self.assertTrue(inspected['images'][0]['cortex_m_vector_table']['reset_handler_in_image'])
        api.attach_image_inspection(plan, inspected)
        self.assertFalse(plan['supported'])

    def test_font_suffix_normalizes_but_prefix_internal_redirect_is_refused(self):
        raw = struct.pack('<II', 0x20008000, 0x4009) + b'\x42' * 24
        for prefix in (b'', struct.pack('<BBHI', 1, 0, 0, 4)):
            with self.subTest(prefixed=bool(prefix)):
                font = suffix_image(prefix + b'font')
                package(self.path, [('main_hwv2.bin', raw), ('font.bin', font)])
                plan = api.update_plan(self.path, variant='TivaPCI', force_font=True)
                images = api.load_selected_images(self.path, plan, b'unused', allow_containers=True)
                result = api.simulate_plan(plan, images)
                self.assertEqual(result['complete'], not bool(prefix))
                if prefix:
                    self.assertEqual(len(result['steps']), 3)
                    self.assertIn('internal flash', result['steps'][-1]['error'])
                    self.assertFalse(result['steps'][-1]['executed'])
                    self.assertEqual(result['regions'], {})
                else:
                    self.assertEqual(result['regions']['font-write']['sha256'], hashlib.sha256(b'font').hexdigest())
                    self.assertEqual(result['steps'][2]['outcome']['length'], 4)

    def test_simulator_rejects_size_substitution_before_peer_creation(self):
        plan = api.update_plan(self.path, variant='TivaPCI')
        with patch('cbus_toolkit.dfu_simulator.DFUSimulator', side_effect=AssertionError('peer created')):
            with self.assertRaisesRegex(ValueError, 'plan size'):
                api.simulate_plan(plan, {'main_hwv2.bin': b'short'})

    def test_simulator_rejects_same_size_substitution_against_inspection(self):
        plan = api.update_plan(self.path, variant='TivaPCI')
        api.attach_image_inspection(plan, api.inspect_package_images(self.path, b'unused'))
        with patch('cbus_toolkit.dfu_simulator.DFUSimulator', side_effect=AssertionError('peer created')):
            with self.assertRaisesRegex(api.FirmwarePackageError, 'payload differs'):
                api.simulate_plan(plan, {'main_hwv2.bin': b'x' * 32})

    def test_missing_inspection_entries_cannot_approve_plan(self):
        plan = api.update_plan(self.path, variant='TivaPCI')
        inspection = api.inspect_package_images(self.path, b'unused')
        inspection['images'].pop(0)
        with self.assertRaisesRegex(api.FirmwarePackageError, 'cover'):
            api.attach_image_inspection(plan, inspection)


if __name__ == '__main__':
    unittest.main()
