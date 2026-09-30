"""Regular-file and snapshot bounds before package metadata can approve a plan."""
import hashlib
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from cbus_toolkit import firmware_diagnostics as api


class FirmwarePackageMetadataInputTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name, 'eDLTFirmware_1.7.0.zip')
        with zipfile.ZipFile(self.path, 'w') as archive:
            for name in ('main_hwv1.bin', 'main_hwv2_font.bin', 'main_hwv2_next.bin', 'font.bin', 'MAIN_hwv1.bin'):
                archive.writestr(name, b'synthetic')

    def test_metadata_selection_and_hash_remain_native_without_plaintext_reads(self):
        with patch.object(zipfile.ZipFile, 'open', side_effect=AssertionError('plaintext read')):
            result = api.inspect_package(self.path)
        self.assertEqual(result['sha256'], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(result['image_candidates']['TivaPCI'], ['main_hwv2_font.bin', 'main_hwv2_next.bin'])
        self.assertEqual(result['font_candidates'], ['font.bin'])
        self.assertEqual(result['unknown_entries'], ['MAIN_hwv1.bin'])
        self.assertEqual(result['version'], '1.7.0')
        self.assertFalse(result['archive_extracted'])

    def test_hashes_and_zip_directory_use_one_descriptor(self):
        observed = []
        digest, archive = api._metadata_digest, zipfile.ZipFile

        def tracked_digest(source):
            observed.append(('hash', source.fileno()))
            return digest(source)

        def tracked_archive(source):
            observed.append(('directory', source.fileno()))
            return archive(source)

        with patch.object(api, '_metadata_digest', side_effect=tracked_digest), \
                patch.object(api.zipfile, 'ZipFile', side_effect=tracked_archive):
            api.inspect_package(self.path)
        self.assertEqual([kind for kind, _ in observed], ['hash', 'directory', 'hash'])
        self.assertEqual(len({descriptor for _, descriptor in observed}), 1)

    @unittest.skipUnless(hasattr(os, 'mkfifo') and hasattr(os, 'O_NONBLOCK'), 'requires nonblocking FIFO support')
    def test_fifo_is_refused_before_any_blocking_read(self):
        fifo = self.path.with_name('fifo')
        os.mkfifo(fifo)
        with patch.object(api, '_metadata_digest', side_effect=AssertionError('read special file')):
            with self.assertRaisesRegex(ValueError, 'regular file'):
                api.inspect_package(fifo)

    @unittest.skipUnless(hasattr(os, 'O_NOFOLLOW'), 'requires no-follow file support')
    def test_symlink_is_refused_before_hashing(self):
        link = self.path.with_name('symlink.zip')
        link.symlink_to(self.path)
        with patch.object(api, '_metadata_digest', side_effect=AssertionError('read symlink')):
            with self.assertRaisesRegex(ValueError, 'regular file'):
                api.inspect_package(link)

    def test_initial_and_streaming_byte_limits_are_both_bounded(self):
        with patch.object(api, 'MAX_PACKAGE_METADATA_SIZE', 8):
            with self.assertRaisesRegex(ValueError, 'inspection limit'):
                api.inspect_package(self.path)
            with self.assertRaisesRegex(ValueError, 'inspection limit'):
                api._metadata_digest(io.BytesIO(b'A' * 9))
            self.assertEqual(api._metadata_digest(io.BytesIO(b'A' * 8)), hashlib.sha256(b'A' * 8).hexdigest())

    def test_substituted_second_hash_is_refused(self):
        with patch.object(api, '_metadata_digest', side_effect=['1' * 64, '2' * 64]):
            with self.assertRaisesRegex(ValueError, 'changed during'):
                api.inspect_package(self.path)

    def test_restored_bytes_with_changed_timestamp_are_refused(self):
        original = os.fstat
        calls = []

        def changed_stat(descriptor):
            value = original(descriptor)
            calls.append(descriptor)
            if len(calls) == 1:
                return value
            names = ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
            values = {name: getattr(value, name) for name in names}
            values['st_ctime_ns'] += 1
            return SimpleNamespace(**values)

        with patch.object(api.os, 'fstat', side_effect=changed_stat):
            with self.assertRaisesRegex(ValueError, 'changed during'):
                api.inspect_package(self.path)

    def test_invalid_zip_still_reports_bounded_metadata_error(self):
        self.path.write_bytes(b'not a zip')
        with self.assertRaisesRegex(ValueError, 'not a valid ZIP archive'):
            api.inspect_package(self.path)


if __name__ == '__main__':
    unittest.main()
