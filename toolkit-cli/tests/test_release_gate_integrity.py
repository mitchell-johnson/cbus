"""Tampering and selection regressions for the provisioned release runner."""
from contextlib import redirect_stdout
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from research import release_gate


NODE = "tests/test_fixture.py::test_fixture"


def _xml(*, node=NODE, skipped=False, count=1, property_present=True):
    property_xml = (f'<properties><property name="cbus_release_gate_nodeid" '
                    f'value="{node}" /></properties>' if property_present else "")
    skipped_xml = '<skipped message="private endpoint details" />' if skipped else ""
    return (f'<testsuites><testsuite tests="{count}" failures="0" errors="0" '
            f'skipped="{int(skipped)}"><testcase classname="test_fixture" '
            f'name="test_fixture">{property_xml}{skipped_xml}</testcase>'
            '</testsuite></testsuites>')


class ReleaseGateIntegrityTests(unittest.TestCase):
    def fixture(self, root, *, selectors=None, requirements=None):
        tests = root / "tests"
        tests.mkdir()
        (tests / "test_fixture.py").write_text("def test_fixture(): pass\n")
        manifest = root / "private-gate.json"
        manifest.write_text(json.dumps({
            "format": release_gate.FORMAT, "gate": "hardware",
            "systems": ["SyntheticOS"],
            "tests": selectors or ["tests/test_fixture.py"],
            "required_environment": requirements or {
                "CBUS_HARDWARE_ACCEPTANCE": {"kind": "flag"}},
        }))
        return manifest

    def run_gate(self, root, manifest, *, collected=None, executed=None,
                 deselected=None, junit_node=NODE, skipped=False, create_junit=True,
                 mutate=None, environment=None):
        junit = root / "results/gate.xml"
        output = root / "results/gate.json"
        source_file = root / "tests/test_fixture.py"

        def source_snapshot(_selectors):
            return {"sha256": release_gate.digest(source_file), "files": 1,
                    "bytes": source_file.stat().st_size}

        def run_pytest(command, **kwargs):
            self.assertIn("research.release_gate_pytest", command)
            self.assertIn("--rootdir", command)
            self.assertIn("--confcutdir", command)
            self.assertEqual(kwargs["env"]["PYTHONPATH"], str(root / "tests"))
            self.assertEqual(kwargs["env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"], "1")
            trace = Path(command[command.index("--cbus-release-gate-trace") + 1])
            trace.write_text(json.dumps({
                "format": release_gate.TRACE_FORMAT,
                "collected": [NODE] if collected is None else collected,
                "executed": [NODE] if executed is None else executed,
                "deselected": [] if deselected is None else deselected,
                "session_exitstatus": 0,
            }))
            if create_junit:
                junit.write_text(_xml(node=junit_node, skipped=skipped))
            if mutate is not None:
                mutate()
            return subprocess.CompletedProcess(command, 0)

        arguments = ["release_gate", str(manifest), "--gate", "hardware",
                     "--junit", str(junit), "--output", str(output)]
        provided = {"CBUS_HARDWARE_ACCEPTANCE": "1"}
        provided.update(environment or {})
        with patch.object(release_gate, "ROOT", root), patch.object(
                release_gate.platform, "system", return_value="SyntheticOS"), patch.object(
                release_gate, "source_revision", return_value="a" * 40), patch.object(
                release_gate, "source_inputs", side_effect=source_snapshot), patch.object(
                release_gate, "installed_package", return_value={"sha256": "b" * 64,
                                                               "files": 1, "bytes": 2}), patch.object(
                release_gate, "wheel_package", return_value={"sha256": "c" * 64,
                                                            "package_members": 1}), patch.object(
                release_gate, "verify_test_import"), patch.object(
                release_gate.subprocess, "run", side_effect=run_pytest), patch.dict(
                os.environ, provided, clear=True), patch("sys.argv", arguments), \
                redirect_stdout(io.StringIO()):
            status = release_gate.main()
        return status, json.loads(output.read_text())

    def test_exact_execution_succeeds_with_hashed_sanitized_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = self.fixture(root)
            status, receipt = self.run_gate(root, manifest)
            self.assertEqual(status, 0)
            self.assertTrue(receipt["passed"])
            self.assertEqual(receipt["execution"], {
                "collected": 1, "executed": 1, "deselected": 0})
            self.assertEqual(len(receipt["junit_sha256"]), 64)
            self.assertEqual(len(receipt["trace_sha256"]), 64)
            self.assertNotIn(str(root), json.dumps(receipt))
            self.assertNotIn(NODE, json.dumps(receipt))

    def test_deselection_missing_execution_and_substituted_junit_fail(self):
        cases = [
            ({"deselected": ["tests/test_fixture.py::test_other"]}, "deselected"),
            ({"executed": []}, "did not execute"),
            ({"junit_node": "tests/test_other.py::test_other"}, "do not match"),
        ]
        for options, reason in cases:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                status, receipt = self.run_gate(root, self.fixture(root), **options)
                self.assertEqual(status, 1)
                self.assertFalse(receipt["passed"])
                self.assertIn(reason, receipt["error"])

    def test_selected_module_with_zero_collected_tests_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = self.fixture(root, selectors=["tests/test_fixture.py", "tests/test_other.py"])
            (root / "tests/test_other.py").write_text("def test_other(): pass\n")
            status, receipt = self.run_gate(root, manifest)
            self.assertEqual(status, 1)
            self.assertIn("collected zero tests", receipt["error"])

    def test_unselected_collected_node_fails_even_when_selected_node_executed(self):
        with tempfile.TemporaryDirectory() as folder:
            trace = Path(folder) / "trace.json"
            other = "tests/test_unselected.py::test_other"
            trace.write_text(json.dumps({
                "format": release_gate.TRACE_FORMAT,
                "collected": [NODE, other], "executed": [NODE, other],
                "deselected": [], "session_exitstatus": 0,
            }))
            with self.assertRaisesRegex(release_gate.GateError, "outside the declared selection"):
                release_gate.trace_result(trace, ["tests/test_fixture.py"],
                                          {"nodeids": [NODE, other]}, 0)

    def test_stale_junit_cannot_satisfy_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = self.fixture(root)
            stale = root / "results/gate.xml"
            stale.parent.mkdir(parents=True)
            stale.write_text(_xml())
            status, receipt = self.run_gate(root, manifest, create_junit=False)
            self.assertEqual(status, 1)
            self.assertIn("Cannot read pytest JUnit", receipt["error"])

    def test_mutated_source_provision_and_manifest_fail_without_path_leak(self):
        for target in ("source", "provision", "manifest"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                artifact = root / "private-artifact"
                artifact.write_text("before")
                manifest = self.fixture(root, requirements={
                    "CBUS_HARDWARE_ACCEPTANCE": {"kind": "flag"},
                    "CBUS_PRIVATE_FILE": {"kind": "file"},
                })
                changed = {"source": root / "tests/test_fixture.py",
                           "provision": artifact, "manifest": manifest}[target]
                status, receipt = self.run_gate(
                    root, manifest, mutate=lambda: changed.write_text("after"),
                    environment={"CBUS_PRIVATE_FILE": str(artifact)})
                self.assertEqual(status, 1)
                self.assertFalse(receipt["passed"])
                self.assertNotIn(str(artifact), json.dumps(receipt))
                self.assertNotIn(str(root), json.dumps(receipt))

    def test_inherited_pytest_selection_options_fail_before_execution(self):
        for name, value in (("PYTEST_ADDOPTS", "-k absent"),
                            ("PYTEST_PLUGINS", "untrusted_plugin")):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                status, receipt = self.run_gate(
                    root, self.fixture(root), environment={name: value})
                self.assertEqual(status, 1)
                self.assertIn("Inherited pytest options", receipt["error"])

    def test_junit_without_node_property_or_with_fake_count_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.xml"
            path.write_text(_xml(property_present=False))
            with self.assertRaisesRegex(release_gate.GateError, "node ID"):
                release_gate.junit_result(path)
            path.write_text(_xml(count=2))
            with self.assertRaisesRegex(release_gate.GateError, "test count"):
                release_gate.junit_result(path)

    def test_wheel_record_and_installed_bytes_are_bound(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            purelib = root / "site-packages"
            package = purelib / "cbus_toolkit"
            package.mkdir(parents=True)
            source = root / "src" / "cbus_toolkit"
            source.mkdir(parents=True)
            content = b"version = 1\n"
            (package / "__init__.py").write_bytes(content)
            (source / "__init__.py").write_bytes(content)
            encoded = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
            wheel = root / "cbus_toolkit_cli-0.1.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("cbus_toolkit/__init__.py", content)
                archive.writestr("cbus_toolkit_cli-0.1.0.dist-info/RECORD",
                                 f"cbus_toolkit/__init__.py,sha256={encoded},{len(content)}\n"
                                 "cbus_toolkit_cli-0.1.0.dist-info/RECORD,,\n")
            with patch.object(release_gate.sysconfig, "get_paths", return_value={
                    "purelib": str(purelib)}), patch.object(release_gate, "ROOT", root):
                first = release_gate.wheel_package({"CBUS_TOOLKIT_WHEEL": str(wheel)})
                self.assertEqual(first["sha256"], release_gate.digest(wheel))
                self.assertEqual(first["package_members"], 1)
                (package / "__init__.py").write_bytes(b"substituted\n")
                with self.assertRaisesRegex(release_gate.GateError, "differs from wheel"):
                    release_gate.wheel_package({"CBUS_TOOLKIT_WHEEL": str(wheel)})
                (package / "__init__.py").write_bytes(content)
                with self.assertRaisesRegex(release_gate.GateError, "missing"):
                    release_gate.wheel_package({})
                (source / "__init__.py").write_bytes(b"different source\n")
                with self.assertRaisesRegex(release_gate.GateError, "checkout source"):
                    release_gate.wheel_package({"CBUS_TOOLKIT_WHEEL": str(wheel)})
                (source / "__init__.py").write_bytes(content)
                with zipfile.ZipFile(wheel, "w") as archive:
                    archive.writestr("cbus_toolkit/__init__.py", b"substituted\n")
                    archive.writestr("cbus_toolkit_cli-0.1.0.dist-info/RECORD",
                                     f"cbus_toolkit/__init__.py,sha256={encoded},{len(content)}\n")
                with self.assertRaisesRegex(release_gate.GateError, "does not match RECORD"):
                    release_gate.wheel_package({"CBUS_TOOLKIT_WHEEL": str(wheel)})

    def test_directory_provision_rejects_symlinked_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            outside = root / "outside"
            outside.write_text("secret")
            directory = root / "private-provision"
            directory.mkdir()
            (directory / "inside").write_text("okay")
            (directory / "linked").symlink_to(outside)
            manifest = {"required_environment": {"CBUS_PRIVATE_DIR": {"kind": "directory"}}}
            with self.assertRaisesRegex(release_gate.GateError, "link"):
                release_gate.verify_provision(manifest, {"CBUS_PRIVATE_DIR": str(directory)})

    def test_source_revision_rejects_dirty_tracked_inputs(self):
        responses = [
            subprocess.CompletedProcess([], 0, "a" * 40 + "\n", ""),
            subprocess.CompletedProcess([], 0, " M tests/test_fixture.py\n", ""),
        ]
        with patch.object(release_gate.subprocess, "run", side_effect=responses):
            with self.assertRaisesRegex(release_gate.GateError, "differs from its revision"):
                release_gate.source_revision()

    def test_source_inventory_rejects_untracked_selected_or_gate_code(self):
        cases = [
            b"research/release_gate.py\0research/release_gate_pytest.py\0",
            b"tests/test_release_gate_integrity.py\0research/release_gate.py\0",
        ]
        for tracked in cases:
            with self.subTest(tracked=tracked):
                completed = subprocess.CompletedProcess([], 0, tracked, b"")
                with patch.object(release_gate.subprocess, "run", return_value=completed):
                    with self.assertRaisesRegex(release_gate.GateError, "must be tracked"):
                        release_gate.source_inputs(["tests/test_release_gate_integrity.py"])

    def test_untracked_conftest_executes_under_pytest_but_gate_rejects_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tests = root / "tests"
            research = root / "research"
            tests.mkdir()
            research.mkdir()
            (tests / "test_fixture.py").write_text(
                'def test_fixture(injected): assert injected == "untracked conftest ran"\n')
            (tests / "conftest.py").write_text(
                'import pytest\n@pytest.fixture\n'
                'def injected(): return "untracked conftest ran"\n')
            (research / "release_gate.py").write_text("# synthetic tracked runner\n")
            (research / "release_gate_pytest.py").write_text("# synthetic tracked plugin\n")
            config = root / "pytest.ini"
            config.write_text("[pytest]\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "tests/test_fixture.py", "research/release_gate.py",
                            "research/release_gate_pytest.py"], cwd=root, check=True,
                           capture_output=True)
            environment = os.environ.copy()
            environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
            environment.pop("PYTEST_ADDOPTS", None)
            environment.pop("PYTEST_PLUGINS", None)
            run = subprocess.run([
                sys.executable, "-m", "pytest", "-c", str(config),
                "--rootdir", str(root), "--confcutdir", str(root),
                "tests/test_fixture.py", "-q",
            ], cwd=root, env=environment, text=True, capture_output=True, check=False)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            with patch.object(release_gate, "ROOT", root), patch.object(
                    release_gate, "__file__", str(research / "release_gate.py")):
                with self.assertRaisesRegex(release_gate.GateError,
                                            "Untracked executable gate input"):
                    release_gate.source_inputs(["tests/test_fixture.py"])

    def test_file_mutation_while_hashing_fails(self):
        class ChangingFile:
            calls = 0

            def stat(self):
                self.calls += 1
                return SimpleNamespace(st_dev=1, st_ino=2, st_size=3,
                                       st_mtime_ns=self.calls, st_ctime_ns=1)

            def open(self, _mode):
                return io.BytesIO(b"abc")

        with self.assertRaisesRegex(release_gate.GateError, "changed while hashing"):
            release_gate.digest(ChangingFile())

    def test_real_pytest_plugin_records_execution_and_junit_node_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            config = root / "pytest.ini"
            config.write_text("[pytest]\n")
            trace = root / "trace.json"
            junit = root / "result.xml"
            project = Path(release_gate.__file__).resolve().parents[1]
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(project)
            environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
            environment.pop("PYTEST_ADDOPTS", None)
            environment.pop("PYTEST_PLUGINS", None)
            result = subprocess.run([
                sys.executable, "-m", "pytest", "-c", str(config), "--rootdir", str(root),
                "-p", "research.release_gate_pytest", "--cbus-release-gate-trace", str(trace),
                "tests/test_fixture.py", f"--junitxml={junit}", "-q",
            ], cwd=root, env=environment, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = release_gate.junit_result(junit)
            self.assertEqual(release_gate.trace_result(trace, ["tests/test_fixture.py"],
                                                       summary, 0),
                             {"collected": 1, "executed": 1, "deselected": 0})


if __name__ == "__main__":
    unittest.main()
