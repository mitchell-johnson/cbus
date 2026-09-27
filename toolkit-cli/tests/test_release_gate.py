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
