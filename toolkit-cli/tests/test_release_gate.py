"""Provisioned release gates fail closed and retain useful result evidence."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from research import release_gate


class ReleaseGateTests(unittest.TestCase):
    def fixture(self, root, *, gate="hardware", requirements=None, tests=None):
        tests = ["tests/test_fixture.py"] if tests is None else tests
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests/test_fixture.py").write_text("def test_fixture(): pass\n")
        manifest = root / "gate.json"
        manifest.write_text(json.dumps({
            "format": release_gate.FORMAT,
            "gate": gate,
            "systems": ["SyntheticOS"],
            "required_environment": requirements or {"CBUS_HARDWARE_ACCEPTANCE": {"kind": "flag"}},
            "tests": tests,
        }))
        return manifest

    def test_manifest_and_provision_are_exact_without_retaining_values(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            executable = root / "owned-tool"
            executable.write_text("synthetic executable\n")
            executable.chmod(0o700)
            vendor = root / "vendor"
            vendor.mkdir()
            (vendor / "cgate.jar").write_text("synthetic jar\n")
            manifest_path = self.fixture(root, requirements={
                "CBUS_CGATE_JAVA": {"kind": "executable"},
                "CBUS_LOCAL_CGATE_VENDOR": {"kind": "directory", "contains": ["cgate.jar"]},
            })
            with patch.object(release_gate, "ROOT", root), patch.object(release_gate.platform, "system", return_value="SyntheticOS"):
                manifest = release_gate.load_manifest(manifest_path, "hardware")
            verified = release_gate.verify_provision(manifest, {
                "CBUS_CGATE_JAVA": str(executable),
                "CBUS_LOCAL_CGATE_VENDOR": str(vendor),
            })
            self.assertEqual([entry["name"] for entry in verified],
                             ["CBUS_CGATE_JAVA", "CBUS_LOCAL_CGATE_VENDOR"])
            self.assertEqual(verified[0]["sha256"], release_gate.digest(executable))
            self.assertEqual(verified[1]["files"], 1)
            self.assertNotIn(str(executable), json.dumps(verified))
            executable.chmod(0o600)
            with self.assertRaisesRegex(release_gate.GateError, "not an executable"):
                release_gate.verify_provision(manifest, {
                    "CBUS_CGATE_JAVA": str(executable),
                    "CBUS_LOCAL_CGATE_VENDOR": str(vendor),
                })

    def test_value_provision_can_pin_an_exact_selector(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest_path = self.fixture(root, requirements={
                "CBUS_NATIVE_SERVICE_BACKEND": {"kind": "value", "equals": "local"},
                "CBUS_SCENE_NATIVE": {"kind": "flag"},
            })
            with patch.object(release_gate, "ROOT", root), patch.object(release_gate.platform, "system", return_value="SyntheticOS"):
                manifest = release_gate.load_manifest(manifest_path, "hardware")
            verified = release_gate.verify_provision(manifest, {
                "CBUS_NATIVE_SERVICE_BACKEND": "local", "CBUS_SCENE_NATIVE": "1"})
            self.assertEqual(verified[0], {"name": "CBUS_NATIVE_SERVICE_BACKEND", "kind": "value",
                                           "present": True, "equals": "local"})
            with self.assertRaisesRegex(release_gate.GateError, "must equal local"):
                release_gate.verify_provision(manifest, {
                    "CBUS_NATIVE_SERVICE_BACKEND": "docker", "CBUS_SCENE_NATIVE": "1"})
            for rule in ({"kind": "flag", "equals": "1"}, {"kind": "value", "equals": ""}):
                with self.subTest(rule=rule):
                    manifest_path = self.fixture(root, requirements={"CBUS_NATIVE_SERVICE_BACKEND": rule})
                    with patch.object(release_gate, "ROOT", root), \
                            patch.object(release_gate.platform, "system", return_value="SyntheticOS"):
                        with self.assertRaisesRegex(release_gate.GateError, "exact value"):
                            release_gate.load_manifest(manifest_path, "hardware")

    def pinned_runtime(self, root):
        home = root / "jdk/Contents/Home"
        (home / "bin").mkdir(parents=True)
        (home / "lib").mkdir()
        java = home / "bin/java"
        java.write_text("synthetic java launcher\n")
        java.chmod(0o700)
        (home / "lib/libjvm.dylib").write_text("synthetic jvm\n")
        (home / "release").write_text('JAVA_RUNTIME_VERSION="11.0.32.1+1"\n')
        pins = release_gate._pin_module()
        rule = {"kind": "executable", "sha256": release_gate.digest(java),
                "pinned_home": {"parent_levels": 2, **pins._tree(home)}}
        return home, java, rule

    def test_pinned_runtime_rejects_substituted_launcher_or_tampered_home(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            home, java, rule = self.pinned_runtime(root)
            manifest_path = self.fixture(root, requirements={"CBUS_CGATE_JAVA": rule})
            with patch.object(release_gate, "ROOT", root), patch.object(release_gate.platform, "system", return_value="SyntheticOS"):
                manifest = release_gate.load_manifest(manifest_path, "hardware")
            verified = release_gate.verify_provision(manifest, {"CBUS_CGATE_JAVA": str(java)})
            self.assertTrue(verified[0]["pinned"])
            self.assertEqual(verified[0]["pinned_home"]["file_count"], 3)
            self.assertNotIn(str(home), json.dumps(verified))
            with self.assertRaisesRegex(release_gate.GateError, "missing: CBUS_CGATE_JAVA"):
                release_gate.verify_provision(manifest, {})
            other = root / "other-java"
            other.write_text("an unpinned java launcher\n")
            other.chmod(0o700)
            with self.assertRaisesRegex(release_gate.GateError, "pinned SHA-256: CBUS_CGATE_JAVA"):
                release_gate.verify_provision(manifest, {"CBUS_CGATE_JAVA": str(other)})
            library = home / "lib/libjvm.dylib"
            for tamper, restore in (
                (lambda: library.write_text("patched jvm\n"), lambda: library.write_text("synthetic jvm\n")),
                (lambda: (home / "lib/extra.jar").write_text("x"), lambda: (home / "lib/extra.jar").unlink()),
                (lambda: library.unlink(), lambda: library.write_text("synthetic jvm\n")),
            ):
                tamper()
                with self.assertRaisesRegex(release_gate.GateError, "runtime home does not match"):
                    release_gate.verify_provision(manifest, {"CBUS_CGATE_JAVA": str(java)})
                restore()
            (home / "lib/link").symlink_to(library)
            with self.assertRaisesRegex(release_gate.GateError, "runtime home cannot be pinned"):
                release_gate.verify_provision(manifest, {"CBUS_CGATE_JAVA": str(java)})

    def test_manifest_rejects_malformed_or_misplaced_pins(self):
        home_pin = {"parent_levels": 2, "file_count": 1, "total_bytes": 1, "sha256": "a" * 64}
        cases = [
            {"kind": "directory", "sha256": "a" * 64},
            {"kind": "executable", "sha256": "A" * 64},
            {"kind": "executable", "sha256": "a" * 63},
            {"kind": "executable", "pinned_home": home_pin},
            {"kind": "executable", "sha256": "a" * 64, "pinned_home": {**home_pin, "parent_levels": 0}},
            {"kind": "executable", "sha256": "a" * 64, "pinned_home": {**home_pin, "extra": 1}},
            {"kind": "executable", "sha_256": "a" * 64},
        ]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for rule in cases:
                with self.subTest(rule=rule):
                    manifest = self.fixture(root, requirements={"CBUS_CGATE_JAVA": rule})
                    with patch.object(release_gate, "ROOT", root), \
                            patch.object(release_gate.platform, "system", return_value="SyntheticOS"):
                        with self.assertRaises(release_gate.GateError):
                            release_gate.load_manifest(manifest, "hardware")

    def test_native_gate_pins_match_the_owned_runtime_provenance(self):
        base = Path(release_gate.__file__).resolve().parent
        native = json.loads((base / "release-gates/native.json").read_text())
        provenance = json.loads((base / "original-artifact-provenance.json").read_text())
        records = {record["id"]: record for record in provenance["artifacts"]}
        home = records["native-jdk-home"]
        expected_home = {"parent_levels": 2, "file_count": home["file_count"],
                         "total_bytes": home["total_bytes"], "sha256": home["sha256"]}
        for name, artifact in (("CBUS_CGATE_JAVA", "native-jdk-java"),
                               ("CBUS_CGATE_JAVAC", "native-jdk-javac")):
            with self.subTest(name=name):
                self.assertEqual(records[artifact]["path"], "bin/" + name.rsplit("_", 1)[1].lower())
                self.assertEqual(native["required_environment"][name], {
                    "kind": "executable", "sha256": records[artifact]["sha256"],
                    "pinned_home": expected_home})

    def test_manifest_rejects_empty_duplicate_external_and_wrong_platform_selection(self):
        cases = [
            ([], "nonempty"),
            (["tests/test_fixture.py", "tests/test_fixture.py"], "unique"),
            (["../test_fixture.py"], "repository test modules"),
        ]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for tests, message in cases:
                with self.subTest(tests=tests):
                    manifest = self.fixture(root, tests=tests)
                    with patch.object(release_gate, "ROOT", root), patch.object(release_gate.platform, "system", return_value="SyntheticOS"):
                        with self.assertRaisesRegex(release_gate.GateError, message):
                            release_gate.load_manifest(manifest, "hardware")
            manifest = self.fixture(root)
            with patch.object(release_gate, "ROOT", root), patch.object(release_gate.platform, "system", return_value="DifferentOS"):
                with self.assertRaisesRegex(release_gate.GateError, "system requirements"):
                    release_gate.load_manifest(manifest, "hardware")

    def test_junit_records_skip_identity_and_cannot_pass_strict_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            result = Path(folder) / "result.xml"
            result.write_text(
                '<testsuites><testsuite tests="2" failures="0" errors="0" skipped="1">'
                '<testcase classname="tests.test_one" name="test_pass"><properties>'
                '<property name="cbus_release_gate_nodeid" value="tests/test_one.py::test_pass" />'
                '</properties></testcase>'
                '<testcase classname="tests.test_one" name="test_skip">'
                '<properties><property name="cbus_release_gate_nodeid" '
                'value="tests/test_one.py::test_skip" /></properties>'
                '<skipped message="missing fixture" /></testcase></testsuite></testsuites>'
            )
            self.assertEqual(release_gate.junit_result(result), {
                "tests": 2, "failures": 0, "errors": 0, "skipped": 1, "passed": 1,
                "nodeids": ["tests/test_one.py::test_pass", "tests/test_one.py::test_skip"],
            })

    def test_main_writes_failing_receipt_when_a_selected_test_skips(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = self.fixture(root)
            junit = root / "results/gate.xml"
            output = root / "results/gate.json"

            def run_pytest(command, **_kwargs):
                self.assertIn("tests/test_fixture.py", command)
                trace = Path(command[command.index("--cbus-release-gate-trace") + 1])
                trace.write_text(json.dumps({
                    "format": release_gate.TRACE_FORMAT,
                    "collected": ["tests/test_fixture.py::test_fixture"],
                    "executed": ["tests/test_fixture.py::test_fixture"],
                    "deselected": [], "session_exitstatus": 0,
                }))
                junit.parent.mkdir(parents=True, exist_ok=True)
                junit.write_text(
                    '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="1">'
                    '<testcase classname="test_fixture" name="test_fixture">'
                    '<properties><property name="cbus_release_gate_nodeid" '
                    'value="tests/test_fixture.py::test_fixture" /></properties>'
                    '<skipped message="missing hardware" /></testcase></testsuite></testsuites>'
                )
                return SimpleNamespace(returncode=0)

            arguments = ["release_gate", str(manifest), "--gate", "hardware",
                         "--junit", str(junit), "--output", str(output)]
            with patch.object(release_gate, "ROOT", root), \
                 patch.object(release_gate.platform, "system", return_value="SyntheticOS"), \
                 patch.object(release_gate, "source_revision", return_value="a" * 40), \
                 patch.object(release_gate, "source_inputs", return_value={"sha256": "b" * 64}), \
                 patch.object(release_gate, "installed_package", return_value={"sha256": "c" * 64}), \
                 patch.object(release_gate, "wheel_package", return_value={"sha256": "d" * 64}), \
                 patch.object(release_gate, "verify_test_import"), \
                 patch.object(release_gate.subprocess, "run", side_effect=run_pytest), \
                 patch.dict(os.environ, {"CBUS_HARDWARE_ACCEPTANCE": "1"}, clear=True), \
                 patch("sys.argv", arguments), redirect_stdout(io.StringIO()):
                self.assertEqual(release_gate.main(), 1)
            receipt = json.loads(output.read_text())
            self.assertFalse(receipt["passed"])
            self.assertEqual(receipt["result"]["skipped"], 1)
            self.assertIn("do not permit failed or skipped", receipt["error"])
            self.assertEqual(receipt["verified_provision"], [
                {"kind": "flag", "name": "CBUS_HARDWARE_ACCEPTANCE", "present": True}
            ])


if __name__ == "__main__":
    unittest.main()
