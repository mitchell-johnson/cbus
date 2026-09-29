"""Portable guards for the offline Authenticode consistency checker."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import struct
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "research/authenticode_check.py"


def load():
    try:
        import cryptography  # noqa: F401
    except ImportError:
        raise unittest.SkipTest("cryptography is installed only with the research extra")
    spec = importlib.util.spec_from_file_location("authenticode_check", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_pe(*, magic: int = 0x20B, table: int = 0, size: int = 0, trailer: bytes = b"") -> bytes:
    header = 0x80
    image = bytearray(0x200)
    image[:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, header)
    image[header:header + 4] = b"PE\0\0"
    optional = header + 24
    struct.pack_into("<H", image, optional, magic)
    directories = optional + (112 if magic == 0x20B else 96)
    struct.pack_into("<II", image, directories + 32, table, size)
    return bytes(image) + trailer


class AuthenticodeCheckTests(unittest.TestCase):
    def setUp(self):
        self.check = load()

    def test_der_and_oid_parsing(self):
        oid = bytes.fromhex("06092a864886f70d010702")
        tag, start, end, following = self.check._tlv(oid)
        self.assertEqual((tag, following), (0x06, len(oid)))
        self.assertEqual(self.check._oid(oid, start, end), self.check.OID_SIGNED_DATA)
        long_form = b"\x04\x81\x80" + b"x" * 0x80
        self.assertEqual(self.check._tlv(long_form)[1:3], (3, 3 + 0x80))
        for invalid in (b"\x04", b"\x04\x05abc", b"\x04\x80", b"\x04\x85" + b"\x00" * 5):
            with self.subTest(invalid=invalid), self.assertRaises(self.check.SignatureError):
                self.check._tlv(invalid)

    def test_image_digest_excludes_checksum_directory_entry_and_signature(self):
        signature = struct.pack("<IHH", 12, 0x200, 2) + b"SIGN"
        for magic, directories in ((0x20B, 0x80 + 24 + 112), (0x10B, 0x80 + 24 + 96)):
            with self.subTest(magic=magic):
                image = synthetic_pe(magic=magic, table=0x200, size=len(signature), trailer=signature)
                blob, ranges = self.check._signature_blob(image)
                self.assertEqual(blob, b"SIGN")
                checksum = 0x80 + 24 + 64
                self.assertEqual(ranges, [(0, checksum), (checksum + 4, directories + 32),
                                          (directories + 40, 0x200), (0x200 + len(signature), len(image))])

    def test_unsigned_or_malformed_images_are_rejected(self):
        cases = (
            (b"ZZ" + synthetic_pe()[2:], "Not a PE"),
            (synthetic_pe(), "no embedded"),
            (synthetic_pe(table=0x200, size=64), "no embedded"),
            (synthetic_pe(magic=0x999, table=0x200, size=8, trailer=b"\0" * 8), "optional header"),
            (synthetic_pe(table=0x200, size=8, trailer=struct.pack("<IHH", 8, 0x200, 1)), "WIN_CERTIFICATE"),
        )
        for image, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(self.check.SignatureError, message):
                self.check._signature_blob(image)


if __name__ == "__main__":
    unittest.main()
