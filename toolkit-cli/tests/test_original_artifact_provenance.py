"""Portable guards for the private original-artifact provenance recipe."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile


SOURCE = Path(__file__).resolve().parents[1] / "research/pin_original_artifacts.py"
SPEC = importlib.util.spec_from_file_location("pin_original_artifacts", SOURCE)
assert SPEC and SPEC.loader
pin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pin)


class OriginalArtifactProvenanceTests(unittest.TestCase):
    def test_file_and_tree_pins_detect_changes_without_timestamp_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / "tree"
            tree.mkdir()
            (tree / "b.dll").write_bytes(b"b")
            (tree / "a.exe").write_bytes(b"a")
            (tree / "notes.txt").write_bytes(b"ignored by flat selector")
            first = pin._tree(tree, flat_binaries=True)
            self.assertEqual(first["file_count"], 2)
            (tree / "notes.txt").write_bytes(b"different ignored text")
            self.assertEqual(pin._tree(tree, flat_binaries=True), first)
            (tree / "a.exe").write_bytes(b"changed")
            self.assertNotEqual(pin._tree(tree, flat_binaries=True), first)
            self.assertNotEqual(pin._tree(tree), first)
            with self.assertRaises(pin.PinError):
                pin._member(root, "../outside", directory=False)

    def test_tree_rejects_symlink_even_when_not_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "file").write_bytes(b"safe")
            (root / "link").symlink_to(root / "file")
            with self.assertRaises(pin.PinError):
                pin._tree(root)
            with self.assertRaises(pin.PinError):
                pin._member(root, "link", directory=False)

    def test_tree_fails_if_a_subdirectory_cannot_be_enumerated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "visible.bin").write_bytes(b"visible")
            unreadable = root / "unreadable"
            unreadable.mkdir()
            (unreadable / "hidden.bin").write_bytes(b"hidden")
            self.assertEqual(pin._tree(root)["file_count"], 2)
            real_scandir = pin.os.scandir

            def guarded_scandir(path):
                if Path(path) == unreadable:
                    raise PermissionError("simulated unreadable subtree")
                return real_scandir(path)

            with mock.patch.object(pin.os, "scandir", side_effect=guarded_scandir):
                with self.assertRaisesRegex(pin.PinError, "Cannot enumerate"):
                    pin._tree(root)

    def test_fixed_recipe_checks_missing_and_changed_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "original.exe").write_bytes(b"original")
            (root / "specs").mkdir()
            (root / "specs/one.xml").write_bytes(b"one")
            roots = {"installer": root, "decoded_specs": root / "specs"}
            recipe = (("source", "installer", "original.exe", "file"),
                      ("decoded-specs", "decoded_specs", ".", "tree"))
            with mock.patch.object(pin, "ARTIFACTS", recipe), \
                 mock.patch.object(pin, "_versions", return_value=pin.EXPECTED_VERSIONS), \
                 mock.patch.object(pin, "_spec_alignment", return_value={"encrypted_count": 1, "decoded_count": 1, "names_match": True}):
                manifest = pin.collect(roots)
                pin.verify(manifest, roots)
                incomplete = json.loads(json.dumps(manifest))
                incomplete["artifacts"].pop()
                with self.assertRaisesRegex(pin.PinError, "incomplete"):
                    pin.verify(incomplete, roots)
                substituted = json.loads(json.dumps(manifest))
                substituted["artifacts"][0]["id"] = "not-the-source"
                with self.assertRaisesRegex(pin.PinError, "recipe changed"):
                    pin.verify(substituted, roots)
                substituted = json.loads(json.dumps(manifest))
                substituted["artifacts"][0]["path"] = "another.exe"
                with self.assertRaisesRegex(pin.PinError, "recipe changed"):
                    pin.verify(substituted, roots)
                (root / "original.exe").write_bytes(b"different")
                with self.assertRaisesRegex(pin.PinError, "source"):
                    pin.verify(manifest, roots)
                (root / "original.exe").unlink()
                with self.assertRaisesRegex(pin.PinError, "absent"):
                    pin.verify(manifest, roots)

    def test_manifest_json_rejects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text('{"format":"one","format":"two"}', encoding="utf-8")
            with self.assertRaisesRegex(pin.PinError, "Duplicate"):
                pin._strict_json(path)
            path.write_text('{"value":NaN}', encoding="utf-8")
            with self.assertRaisesRegex(pin.PinError, "Non-finite"):
                pin._strict_json(path)

    def test_version_sources_are_read_without_executing_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jar = root / "cgate.jar"
            with zipfile.ZipFile(jar, "w") as archive:
                archive.writestr("META-INF/MANIFEST.MF", "Implementation-Version: 3.4.0_\r\n 2001\r\nBuild-Number: 2001\r\n")
            self.assertEqual(pin._jar_manifest_version(jar), ("3.4.0_2001", "2001"))
            release = root / "release"
            release.write_text('JAVA_RUNTIME_VERSION="11.0.24+8"\nIMPLEMENTOR_VERSION="Temurin-11.0.24+8"\n', encoding="utf-8")
            self.assertEqual(pin._jre_version(release), ("11.0.24+8", "Temurin-11.0.24+8"))


if __name__ == "__main__":
    unittest.main()
