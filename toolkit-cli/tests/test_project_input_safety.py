"""Project inputs fail with bounded reads and ordinary structured errors."""
from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_BZIP2, ZIP_DEFLATED, ZIP_LZMA, ZIP_STORED
import zlib

from cbus_toolkit import cli
from cbus_toolkit.project import ProjectDocument, ProjectError, UnsupportedProjectFormat


class ProjectInputSafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def corrupt_archive(self):
        target = BytesIO()
        name = 'project.xml'
        with ZipFile(target, 'w', compression=ZIP_DEFLATED) as archive:
            archive.writestr(name, b'<Project><TagName>TEST</TagName></Project>')
        payload = bytearray(target.getvalue())
        # Fixed local header plus filename, then a reserved deflate block type.
        payload[30 + len(name)] = 7
        return bytes(payload)

    def test_corrupt_member_compression_is_a_project_error(self):
        with self.assertRaises(UnsupportedProjectFormat):
            ProjectDocument.from_snapshot(self.corrupt_archive())

    def test_corrupt_cbz_cli_returns_json_error_without_traceback(self):
        source = self.root / 'broken.cbz'
        source.write_bytes(self.corrupt_archive())
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            result = cli.main(['project', 'inspect', str(source)])
        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(json.loads(error.getvalue())['type'], 'UnsupportedProjectFormat')

    def test_forged_member_size_cannot_expand_an_unbounded_deflate_block(self):
        target = BytesIO()
        with ZipFile(target, 'w', compression=ZIP_DEFLATED) as archive:
            archive.writestr('project.xml', b'<Project/>')
            archive.writestr('data.bin', b'Z' * (1024 * 1024))
        payload = bytearray(target.getvalue())
        local = payload.index(b'PK\x03\x04', 1)
        central = payload.index(b'PK\x01\x02')
        central = payload.index(b'PK\x01\x02', central + 1)
        # ZIP's decoder trusts the header's size and clips its output to it.
        # Make the retained prefix valid while its actual block is much larger.
        for offset in (local + 14, central + 16):
            struct.pack_into('<I', payload, offset, zlib.crc32(b'Z'))
        for offset in (local + 22, central + 24):
            struct.pack_into('<I', payload, offset, 1)
        original = zlib.decompressobj
        expansions = []

        class TrackedInflater:
            def __init__(self, *args, **kwargs):
                self.inner = original(*args, **kwargs)
            def decompress(self, *args, **kwargs):
                result = self.inner.decompress(*args, **kwargs)
                expansions.append(len(result))
                return result
            def __getattr__(self, name): return getattr(self.inner, name)

        with patch('cbus_toolkit.project.MAX_DOCUMENT_BYTES', 4096), \
                patch('zipfile.zlib.decompressobj', TrackedInflater):
            ProjectDocument.from_snapshot(bytes(payload))
        self.assertTrue(expansions)
        # ZipExtFile has a 4 KiB minimum chunk even for a 1-byte entry.
        self.assertLessEqual(max(expansions), 4096)

    def test_stored_and_deflated_cbz_members_keep_their_payload_and_codec(self):
        for method in (ZIP_STORED, ZIP_DEFLATED):
            with self.subTest(method=method):
                target = BytesIO()
                with ZipFile(target, 'w', compression=method) as archive:
                    archive.writestr('project.xml', b'<Project><TagName>TEST</TagName></Project>')
                    archive.writestr('data.bin', b'\x00\xffattachment')
                document = ProjectDocument.from_snapshot(target.getvalue())
                document.set_field('/', 'Description', 'Updated')
                path = self.root / f'saved-{method}.cbz'
                document.save(path)
                with ZipFile(path) as saved:
                    self.assertEqual(saved.read('data.bin'), b'\x00\xffattachment')
                    self.assertIn(b'<Description>Updated</Description>', saved.read('project.xml'))
                    self.assertEqual([info.compress_type for info in saved.infolist()], [method, method])

    def test_unsupported_zip_codecs_are_rejected_before_any_member_is_decoded(self):
        for method in (ZIP_BZIP2, ZIP_LZMA):
            with self.subTest(method=method):
                target = BytesIO()
                with ZipFile(target, 'w', compression=ZIP_DEFLATED) as archive:
                    archive.writestr('project.xml', b'<Project/>')
                    archive.writestr('data.bin', b'attachment', compress_type=method)
                with patch.object(ZipFile, 'open', side_effect=AssertionError('member decoding started')):
                    with self.assertRaisesRegex(UnsupportedProjectFormat, 'stored or deflate'):
                        ProjectDocument.from_snapshot(target.getvalue())

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO guard')
    def test_fifo_is_refused_without_opening(self):
        source = self.root / 'project.xml'
        os.mkfifo(source)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('unbounded FIFO read')):
            with self.assertRaisesRegex(ProjectError, 'regular file'):
                ProjectDocument.load(source)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO substitution guard')
    def test_fifo_substituted_after_stat_is_refused_without_reading(self):
        source = self.root / 'project.xml'
        source.write_bytes(b'<Project/>')
        before = source.stat()
        source.unlink()
        os.mkfifo(source)
        with patch.object(Path, 'stat', return_value=before), \
                patch.object(Path, 'read_bytes', side_effect=AssertionError('unbounded FIFO read')):
            with self.assertRaisesRegex(ProjectError, 'regular file'):
                ProjectDocument.load(source)

    def test_file_growth_cannot_turn_the_bounded_load_into_an_unbounded_read(self):
        source = self.root / 'project.xml'
        source.write_bytes(b'<Project/>')
        fstat = os.fstat
        reads = []
        fdopen = os.fdopen

        class TrackedStream:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *args): return self.stream.__exit__(*args)
            def fileno(self): return self.stream.fileno()
            def read(self, count=-1):
                reads.append(count)
                return self.stream.read(count)

        def grow_after_descriptor_stat(descriptor):
            result = fstat(descriptor)
            self.assertTrue(stat.S_ISREG(result.st_mode))
            with source.open('ab') as stream:
                stream.write(b' ' * 1024)
            return result

        with patch('cbus_toolkit.project.MAX_DOCUMENT_BYTES', 64), \
                patch('cbus_toolkit.project.os.fstat', side_effect=grow_after_descriptor_stat), \
                patch('cbus_toolkit.project.os.fdopen', side_effect=lambda *args: TrackedStream(fdopen(*args))):
            with self.assertRaisesRegex(ProjectError, 'size limit'):
                ProjectDocument.load(source)
        self.assertEqual(reads, [65])

    def test_regular_file_symlink_remains_readable(self):
        source = self.root / 'project.xml'
        source.write_bytes(b'<Project/>')
        link = self.root / 'link.xml'
        try:
            link.symlink_to(source)
        except OSError:
            self.skipTest('Symlink creation unavailable')
        self.assertEqual(ProjectDocument.load(link).to_xml_bytes(), b'<Project/>')


if __name__ == '__main__':
    unittest.main()
