"""Tiny synthetic ZIP headers prove admission precedes opening/decompression."""
from contextlib import ExitStack
import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib
from cbus_toolkit import firmware_update_plan as api
try:
    import pyzipper
except ImportError:
    pyzipper = None
PASSWORD = b'synthetic-test-password'
PAYLOAD = b'tiny synthetic firmware'


def fixture(method=0, *, aes=False, two=False):
    stream = io.BytesIO()
    writer = pyzipper.AESZipFile if aes else zipfile.ZipFile
    options = {'compression': method}
    if aes:
        options['encryption'] = pyzipper.WZ_AES
    with writer(stream, 'w', **options) as archive:
        if aes:
            archive.setpassword(PASSWORD)
        archive.writestr('main.bin', PAYLOAD)
        if two:
            archive.writestr('font.bin', b'tiny font')
    return stream.getvalue()


def mutate(data, method, *, aes=False, last=False, declared_size=None):
    data = bytearray(data)
    for signature, method_offset, name_offset, extra_offset, header_size in (
            (b'PK\x03\x04', 8, 26, 28, 30), (b'PK\x01\x02', 10, 28, 30, 46)):
        positions = []
        pos = data.find(signature)
        while pos >= 0:
            positions.append(pos)
            pos = data.find(signature, pos + 4)
        for pos in positions[-1:] if last else positions:
            if not aes:
                struct.pack_into('<H', data, pos + method_offset, method)
                if declared_size is not None:
                    size_offset, crc_offset = (22, 14) if header_size == 30 else (24, 16)
                    struct.pack_into('<I', data, pos + size_offset, declared_size)
                    struct.pack_into('<I', data, pos + crc_offset, zlib.crc32(PAYLOAD[:declared_size]))
                continue
            cursor = pos + header_size + struct.unpack_from('<H', data, pos + name_offset)[0]
            end = cursor + struct.unpack_from('<H', data, pos + extra_offset)[0]
            found = False
            while cursor < end:
                tag, size = struct.unpack_from('<HH', data, cursor)
                if tag == 0x9901:
                    struct.pack_into('<H', data, cursor + 9, method)
                    found = True
                cursor += 4 + size
            assert found, 'synthetic AES extra missing'
    return bytes(data)


class FirmwarePackageCodecTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name, 'synthetic.zip')

    def read(self, data, **options):
        self.path.write_bytes(data)
        return api.read_package_entries(self.path, PASSWORD, **options)

    def refused(self, data, *, fallback=False, message='compression|codec|method'):
        self.path.write_bytes(data)
        with ExitStack() as stack:
            if fallback:
                stack.enter_context(patch.dict(sys.modules, {'pyzipper': None}))
            mocks = [stack.enter_context(patch.object(zipfile.ZipFile, 'open', side_effect=AssertionError('entry opened'))),
                     stack.enter_context(patch.object(zipfile, '_get_decompressor', side_effect=AssertionError('decompressor initialized')))]
            if pyzipper:
                mocks += [stack.enter_context(patch.object(pyzipper.AESZipFile, 'open', side_effect=AssertionError('AES entry opened'))),
                          stack.enter_context(patch.object(pyzipper.zipfile.ZipExtFile, 'get_decompressor', side_effect=AssertionError('AES decompressor initialized')))]
            with self.assertRaisesRegex(api.FirmwarePackageError, message):
                api.read_package_entries(self.path, PASSWORD)
            for mocked in mocks:
                mocked.assert_not_called()

    def test_standard_stored_deflated_both_readers(self):
        for method in (0, 8):
            for fallback in (False, True):
                with self.subTest(method=method, fallback=fallback), ExitStack() as stack:
                    if fallback:
                        stack.enter_context(patch.dict(sys.modules, {'pyzipper': None}))
                    self.assertEqual(self.read(fixture(method)), {'main.bin': PAYLOAD})

    def test_unsafe_standard_headers_refused_before_open_both_readers(self):
        for method in (12, 14, 31337):
            for fallback in (False, True):
                with self.subTest(method=method, fallback=fallback):
                    # The declared one-byte size passes every output-size
                    # limit; rejection must still precede decoder creation.
                    self.refused(mutate(fixture(), method, declared_size=1), fallback=fallback)

    def test_all_selected_headers_checked_before_first_open(self):
        for fallback in (False, True):
            with self.subTest(fallback=fallback):
                self.refused(mutate(fixture(two=True), 14, last=True), fallback=fallback)

    def test_unselected_unsafe_header_allows_safe_selection(self):
        data = mutate(fixture(two=True), 12, last=True)
        for fallback in (False, True):
            with self.subTest(fallback=fallback), ExitStack() as stack:
                if fallback:
                    stack.enter_context(patch.dict(sys.modules, {'pyzipper': None}))
                self.assertEqual(self.read(data, names={'main.bin'}), {'main.bin': PAYLOAD})

    @unittest.skipIf(pyzipper is None, 'optional pyzipper unavailable')
    def test_aes_stored_deflated_normalized_methods_admitted(self):
        for method in (0, 8):
            with self.subTest(method=method):
                data = fixture(method, aes=True)
                with pyzipper.AESZipFile(io.BytesIO(data)) as archive:
                    self.assertEqual(archive.infolist()[0].compress_type, method)
                self.assertEqual(self.read(data), {'main.bin': PAYLOAD})

    @unittest.skipIf(pyzipper is None, 'optional pyzipper unavailable')
    def test_aes_unsafe_inner_methods_refused_before_open(self):
        for method in (12, 14, 31337):
            with self.subTest(method=method):
                self.refused(mutate(fixture(aes=True), method, aes=True))

    @unittest.skipIf(pyzipper is None, 'optional pyzipper unavailable')
    def test_all_aes_selected_headers_checked_before_first_decryption(self):
        self.refused(mutate(fixture(aes=True, two=True), 14, aes=True, last=True))

    @unittest.skipIf(pyzipper is None, 'optional pyzipper unavailable')
    def test_aes_stdlib_fallback_retains_optional_extra_refusal(self):
        for method in (0, 8, 12, 14):
            with self.subTest(method=method):
                self.refused(mutate(fixture(aes=True), method, aes=True), fallback=True,
                             message='optional firmware extra.*pyzipper')


if __name__ == '__main__':
    unittest.main()
