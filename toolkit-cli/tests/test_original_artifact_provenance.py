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
                 mock.patch.object(pin, "_spec_alignment", return_value={"encrypted_count": 1, "decoded_count": 1, "names_match": True}), \
                 mock.patch.object(pin, "_spec_derivation", return_value={"byte_identical": True}):
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

    def test_link_tree_pins_literal_targets_without_following_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Versions/6.12.0"
            (root / "bin").mkdir(parents=True)
            (root / "bin/mono-sgen64").write_bytes(b"runtime")
            (root / "bin/mono64").symlink_to("mono-sgen64")
            (root / "share").symlink_to("/Library/Frameworks/Mono.framework/Versions/6.12.0/share")
            first = pin._tree(root, links=True)
            self.assertEqual((first["file_count"], first["link_count"]), (1, 2))
            with self.assertRaises(pin.PinError):
                pin._tree(root)
            (root / "bin/mono64").unlink()
            (root / "bin/mono64").symlink_to("/opt/other/mono")
            self.assertNotEqual(pin._tree(root, links=True), first)
            (root / "bin/mono64").unlink()
            (root / "bin/mono64").symlink_to("mono-sgen64")
            self.assertEqual(pin._tree(root, links=True), first)
            (root / "bin/mono-sgen64").write_bytes(b"patched")
            self.assertNotEqual(pin._tree(root, links=True), first)
            # Link-aware digests use a separate domain; link-free pins keep tree-v1.
            plain = Path(directory) / "plain"
            plain.mkdir()
            (plain / "one").write_bytes(b"1")
            self.assertNotEqual(pin._tree(plain)["sha256"], pin._tree(plain, links=True)["sha256"])
            self.assertNotIn("link_count", pin._tree(plain))

    def spec_roots(self, root: Path) -> dict[str, Path]:
        encrypted = root / "installer/cgate-extracted-20260926/app/unitspec"
        encrypted.mkdir(parents=True)
        decoded = root / "decoded"
        decoded.mkdir()
        for name, body in (("A.xml", b"<a/>"), ("B.xml", b"<b/>")):
            (encrypted / (name + ".es")).write_bytes(body[::-1])
            (decoded / name).write_bytes(body)
        (encrypted / "catalogue.txt").write_bytes(b"not a specification")
        # A synthetic stand-in with the decoder's CLI contract; the real
        # decoder needs vendor-format inputs that are never committed.
        decoder = root / "decode.py"
        decoder.write_text(
            "import sys\nfrom pathlib import Path\n"
            "source, output = Path(sys.argv[1]), Path(sys.argv[2])\n"
            "output.mkdir(parents=True)\n"
            "for item in sorted(source.glob('*.xml.es')):\n"
            "    data = item.read_bytes()[::-1]\n"
            "    if data == b'<bad/>': sys.exit('authentication failed')\n"
            "    (output / item.name[:-3]).write_bytes(data)\n",
            encoding="utf-8")
        return {"installer": root / "installer", "decoded_specs": decoded, "decoder": decoder}

    def test_specification_derivation_requires_a_byte_identical_fresh_decode(self):
        with tempfile.TemporaryDirectory() as directory:
            roots = self.spec_roots(Path(directory))
            with mock.patch.object(pin, "DECODER", roots.pop("decoder")):
                receipt = pin._spec_derivation(roots)
                self.assertEqual((receipt["decoded_count"], receipt["byte_identical"]), (2, True))
                self.assertNotIn("A.xml", json.dumps(receipt))
                self.assertEqual(pin._spec_derivation(roots), receipt)
                decoded = roots["decoded_specs"]
                encrypted = roots["installer"] / "cgate-extracted-20260926/app/unitspec"
                cases = (
                    (lambda: (decoded / "A.xml").write_bytes(b"<tampered/>"),
                     lambda: (decoded / "A.xml").write_bytes(b"<a/>"), "byte-identical"),
                    (lambda: (decoded / "A.xml").unlink(),
                     lambda: (decoded / "A.xml").write_bytes(b"<a/>"), "byte-identical"),
                    (lambda: (decoded / "C.xml").write_bytes(b"<c/>"),
                     lambda: (decoded / "C.xml").unlink(), "byte-identical"),
                    (lambda: (encrypted / "B.xml.es").write_bytes(b"<bad/>"[::-1]),
                     lambda: (encrypted / "B.xml.es").write_bytes(b"<b/>"[::-1]), "authenticate"),
                )
                for tamper, restore, message in cases:
                    tamper()
                    with self.assertRaisesRegex(pin.PinError, message):
                        pin._spec_derivation(roots)
                    restore()
                self.assertEqual(pin._spec_derivation(roots), receipt)

    def test_real_decoder_round_trips_synthetic_authenticated_input(self):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            self.skipTest("cryptography is installed only with the research extra")
        source = pin.DECODER.read_text(encoding="utf-8")
        key, nonce = (bytes.fromhex(value) for value in __import__("re").findall(r'fromhex\("([0-9a-f]+)"\)', source))
        with tempfile.TemporaryDirectory() as directory:
            roots = self.spec_roots(Path(directory))
            del roots["decoder"]
            encrypted = roots["installer"] / "cgate-extracted-20260926/app/unitspec"
            for name in ("A.xml", "B.xml"):
                body = (roots["decoded_specs"] / name).read_bytes()
                (encrypted / (name + ".es")).write_bytes(AESGCM(key).encrypt(nonce, body, None))
            self.assertTrue(pin._spec_derivation(roots)["byte_identical"])
            forged = bytearray((encrypted / "A.xml.es").read_bytes())
            forged[-1] ^= 1
            (encrypted / "A.xml.es").write_bytes(bytes(forged))
            with self.assertRaisesRegex(pin.PinError, "authenticate"):
                pin._spec_derivation(roots)

    def test_verify_names_a_changed_derivation_or_runtime_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "original.exe").write_bytes(b"original")
            roots = {"installer": root}
            recipe = (("source", "installer", "original.exe", "file"),)
            derivation = {"decoder": "research/decode_unitspec.py", "pairs_sha256": "a" * 64}
            with mock.patch.object(pin, "ARTIFACTS", recipe), \
                 mock.patch.object(pin, "_versions", return_value=pin.EXPECTED_VERSIONS), \
                 mock.patch.object(pin, "_spec_alignment", return_value={}), \
                 mock.patch.object(pin, "_spec_derivation", return_value=derivation):
                manifest = pin.collect(roots)
                pin.verify(manifest, roots)
                changed = json.loads(json.dumps(manifest))
                changed["specification_derivation"]["pairs_sha256"] = "b" * 64
                with self.assertRaisesRegex(pin.PinError, "mismatch: specification_derivation"):
                    pin.verify(changed, roots)
                changed = json.loads(json.dumps(manifest))
                del changed["specification_derivation"]
                with self.assertRaisesRegex(pin.PinError, "schema"):
                    pin.verify(changed, roots)
                changed = json.loads(json.dumps(manifest))
                changed["versions"]["native_jdk"]["value"] = "11.0.24+8"
                with self.assertRaisesRegex(pin.PinError, "mismatch: versions"):
                    pin.verify(changed, roots)

    def test_committed_manifest_pins_the_owned_native_runtimes(self):
        manifest = pin._strict_json(pin.MANIFEST)
        self.assertEqual([tuple(record[key] for key in ("id", "root", "path", "kind"))
                          for record in manifest["artifacts"]], list(pin.ARTIFACTS))
        self.assertEqual(manifest["versions"], pin.EXPECTED_VERSIONS)
        self.assertEqual(manifest["roots"], pin.ROOTS)
        self.assertEqual(manifest["specification_derivation"]["decoded_count"], 280)
        self.assertEqual(manifest["specification_derivation"]["decoder_sha256"],
                         pin._sha_file(pin.DECODER)[1],
                         "decode_unitspec.py changed; re-derive and repin the specifications")

    def test_reproduced_extraction_is_compared_record_by_record(self):
        source = Path(__file__).resolve().parents[1] / "research/reproduce_installer_extraction.py"
        spec = importlib.util.spec_from_file_location("reproduce_installer_extraction", source)
        assert spec and spec.loader
        reproduce = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reproduce)
        pins = reproduce.pin
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "setup.exe").write_bytes(b"setup")
            (root / "app").mkdir()
            (root / "app/one.dll").write_bytes(b"one")
            recipe = (("setup", "installer", "setup.exe", "file"),
                      ("app", "installer", "app", "tree"),
                      ("specs", "decoded_specs", ".", "tree"))
            roots = {"installer": root, "decoded_specs": root / "app"}
            with mock.patch.object(pins, "ARTIFACTS", recipe), \
                 mock.patch.object(pins, "_versions", return_value={}), \
                 mock.patch.object(pins, "_spec_alignment", return_value={}), \
                 mock.patch.object(pins, "_spec_derivation", return_value={}):
                manifest = pins.collect(roots)
            self.assertEqual(reproduce.compare(manifest, root), {"records": 2, "files": 2})
            (root / "app/two.dll").write_bytes(b"two")
            with self.assertRaisesRegex(pins.PinError, "differs from the pins: app"):
                reproduce.compare(manifest, root)
            (root / "app/two.dll").unlink()
            (root / "setup.exe").write_bytes(b"other")
            with self.assertRaisesRegex(pins.PinError, "differs from the pins: setup"):
                reproduce.compare(manifest, root)
            (root / "setup.exe").unlink()
            with self.assertRaisesRegex(pins.PinError, "absent"):
                reproduce.compare(manifest, root)
            with self.assertRaisesRegex(pins.PinError, "not the pinned"):
                reproduce.reproduce(root / "app/one.dll", root / "out", manifest)

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
