"""Adversarial local-file receipts against a selected catalogue descriptor."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.toolkit_update_package_file import inspect_update_package_file


NODE_ID = "selected-node"
FILE_ID = "package-1"
PACKAGE = b"owned synthetic installer bytes\x00\xff"


def body(*, package=PACKAGE):
    return {
        "success": True,
        "statusCode": 200,
        "data": [{
            "nodeId": NODE_ID,
            "nodeName": "Synthetic update",
            "data": {"type": "PackageData"},
            "files": [{
                "id": FILE_ID,
                "name": "synthetic.exe",
                "size": len(package),
                "url": "https://invalid.example/synthetic.exe",
                "security": {"sha1": hashlib.sha1(package).hexdigest().upper()},
                "metadata": {"architecture": "windows_x86_64", "mediatype": "singleFileExecutable"},
            }],
            "signatures": {},
        }],
    }


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class UpdatePackageFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.package = Path(self.tmp.name) / "package.exe"
        self.package.write_bytes(PACKAGE)

    def inspect(self, source=None, **kwargs):
        options = {"node_id": NODE_ID, "file_id": FILE_ID, "package_path": self.package}
        options.update(kwargs)
        return inspect_update_package_file(encode(body() if source is None else source), **options)

    def test_matching_bytes_have_exact_receipts_but_no_trust_claim(self):
        source = encode(body())
        report = self.inspect().as_dict()
        self.assertTrue(report["bytes_match_catalogue_descriptor"])
        self.assertEqual(report["catalogue_source_sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual(report["declared_sha1"], hashlib.sha1(PACKAGE).hexdigest())
        self.assertEqual(report["observed_sha256"], hashlib.sha256(PACKAGE).hexdigest())
        self.assertEqual(report["observed_size"], len(PACKAGE))
        for field in (
            "metadata_signature_verified", "publisher_trust_evaluated",
            "complete_revocation_status_evaluated", "package_applicability_evaluated",
            "install_permitted", "downloaded", "installed",
        ):
            self.assertFalse(report[field])
        self.assertNotIn("url", report)
        self.assertNotIn("package_path", report)

    def test_wrong_bytes_and_wrong_declared_size_return_negative_receipts(self):
        self.package.write_bytes(b"substituted bytes of same size".ljust(len(PACKAGE), b"!"))
        self.assertFalse(self.inspect().bytes_match_catalogue_descriptor)
        self.package.write_bytes(PACKAGE)
        source = body()
        source["data"][0]["files"][0]["size"] += 1
        report = self.inspect(source)
        self.assertEqual(report.observed_sha1, report.declared_sha1)
        self.assertFalse(report.bytes_match_catalogue_descriptor)

    def test_same_node_id_from_different_source_cannot_borrow_digest(self):
        source = body()
        source["data"][0]["files"][0]["security"]["sha1"] = "0" * 40
        self.assertFalse(self.inspect(source).bytes_match_catalogue_descriptor)
        source = body()
        source["data"][0]["files"][0]["url"] = "https://invalid.example/changed"
        self.assertNotEqual(
            self.inspect(source).catalogue_source_sha256,
            self.inspect().catalogue_source_sha256,
        )

    def test_success_and_status_code_are_type_exact(self):
        for key, value in (("success", 1), ("success", False), ("statusCode", True),
                           ("statusCode", 201)):
            source = body()
            source[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.inspect(source)

    def test_ambiguous_node_and_file_ids_are_rejected(self):
        source = body()
        source["data"].append(copy.deepcopy(source["data"][0]))
        with self.assertRaises(ValueError):
            self.inspect(source)
        source = body()
        source["data"][0]["files"].append(copy.deepcopy(source["data"][0]["files"][0]))
        with self.assertRaises(ValueError):
            self.inspect(source)
        with self.assertRaises(ValueError):
            self.inspect(file_id="other")

    def test_missing_or_malformed_sha1_fails_closed(self):
        for security in (None, {}, {"sha1": "g" * 40}, {"sha1": "0" * 39},
                         {"sha256": "0" * 64}):
            source = body()
            source["data"][0]["files"][0]["security"] = security
            with self.subTest(security=security), self.assertRaises(ValueError):
                self.inspect(source)

    def test_duplicate_json_key_fails_closed(self):
        source = encode(body()).replace(b'"success":true', b'"success":true,"success":true')
        with self.assertRaises(ValueError):
            inspect_update_package_file(
                source, node_id=NODE_ID, file_id=FILE_ID, package_path=self.package
            )

    def test_symlink_and_nonregular_file_are_rejected(self):
        link = Path(self.tmp.name) / "link.exe"
        link.symlink_to(self.package)
        with self.assertRaises(ValueError):
            self.inspect(package_path=link)
        if hasattr(os, "mkfifo"):
            fifo = Path(self.tmp.name) / "pipe"
            os.mkfifo(fifo)
            with self.assertRaises(ValueError):
                self.inspect(package_path=fifo)

    def test_file_replaced_between_stat_and_open_is_rejected(self):
        replacement = Path(self.tmp.name) / "replacement.exe"
        replacement.write_bytes(PACKAGE)
        original_open = os.open

        def swapped_open(path, flags):
            os.replace(replacement, self.package)
            return original_open(path, flags)

        with patch("cbus_toolkit.toolkit_update_package_file.os.open", side_effect=swapped_open):
            with self.assertRaisesRegex(ValueError, "changed before the file read"):
                self.inspect()

    def test_growth_during_read_is_rejected(self):
        original_read = os.read
        changed = False

        def growing_read(fd, count):
            nonlocal changed
            if not changed:
                changed = True
                with self.package.open("ab") as stream:
                    stream.write(b"!")
            return original_read(fd, count)

        with patch("cbus_toolkit.toolkit_update_package_file.os.read", side_effect=growing_read):
            with self.assertRaisesRegex(ValueError, "changed during the file read"):
                self.inspect()

    def test_declared_and_observed_byte_caps_fail_closed(self):
        with self.assertRaises(ValueError):
            self.inspect(max_package_bytes=len(PACKAGE) - 1)
        source = body(package=PACKAGE[:4])
        # The descriptor passes its own cap, but the file does not.
        with self.assertRaises(ValueError):
            self.inspect(source, max_package_bytes=4)
        with self.assertRaises(ValueError):
            self.inspect(max_package_bytes=True)

    def test_unsupported_signed_file_shape_is_rejected(self):
        source = body()
        source["data"][0]["files"][0]["security"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.inspect(source)

    def test_captured_original_descriptor_is_selected_without_a_download(self):
        fixture = Path(__file__).resolve().parents[1] / "research/fixtures/toolkit-update-metadata-vectors.json"
        fixture_bytes = fixture.read_bytes()
        self.assertEqual(
            hashlib.sha256(fixture_bytes).hexdigest(),
            "71a70a37288a6534299c3d609becb261f1f1e1a0bdadc6c2231c5c6071b4a04a",
        )
        captured = json.loads(fixture_bytes)
        source = captured["raw_catalogue_json"].encode()
        self.assertEqual(
            hashlib.sha256(source).hexdigest(),
            "4444edb826360c2909b740c6152bc2d9f76f6ce471400cda1bbaf49dfbe97ad9",
        )
        report = inspect_update_package_file(
            source,
            node_id="2398558e-aa7e-4777-b4a8-f1e8f21704ea",
            file_id="5",
            package_path=self.package,
        ).as_dict()
        self.assertEqual(report["catalogue_source_sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual(report["declared_size"], 176269496)
        self.assertEqual(report["declared_sha1"], "4e19dbe51d000718b92cf018f962eb6ee252022e")
        self.assertFalse(report["bytes_match_catalogue_descriptor"])
        self.assertFalse(report["install_permitted"])
        source = body()
        source["data"][0]["files"][0]["size"] = True
        with self.assertRaises(ValueError):
            self.inspect(source)


if __name__ == "__main__":
    unittest.main()
