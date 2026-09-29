#!/usr/bin/env python3
"""Run acceptance tests with a durable result; test success is not parity."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from importlib import resources
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import ssl
import stat
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _relative_test_path(path: Path) -> str:
    """Return a stable repository-relative test path for retained evidence."""
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return path.name


def _sanitized_nodeid(nodeid: str) -> str:
    """Keep pytest identities useful without retaining an absolute checkout."""
    root = str(ROOT.resolve())
    return nodeid.replace(root + os.sep, "").replace(root + "/", "")


def _sanitized_detail(value: object) -> str:
    """Remove the checkout and home paths from a retained pytest diagnostic."""
    detail = str(value)
    replacements = ((str(ROOT.resolve()), "<repository>"),
                    (str(Path.home().resolve()), "<home>"))
    for source, replacement in replacements:
        if source:
            detail = detail.replace(source, replacement)
    return detail


@dataclass
class PytestOutcome:
    """Structured pytest result used by the JSON acceptance receipt."""

    exit_code: int
    tests_run: int
    failures: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    expected_failures: list[str] = field(default_factory=list)
    unexpected_successes: list[str] = field(default_factory=list)
    collected_by_file: dict[str, int] = field(default_factory=dict)
    uncollected_test_files: list[str] = field(default_factory=list)

    def was_successful(self) -> bool:
        return (self.exit_code == int(pytest.ExitCode.OK) and not self.failures
                and not self.errors and not self.unexpected_successes)


class _AcceptancePlugin:
    """Collect stable pytest outcomes without depending on terminal text."""

    def __init__(self, selected: list[Path]):
        self.selected = {path.resolve(): _relative_test_path(path) for path in selected}
        self.collected_by_path = {path: 0 for path in self.selected}
        self.nonempty = {path.resolve() for path in selected if path.stat().st_size}
        self.nodeids: list[str] = []
        self.executed_nodeids: set[str] = set()
        self.deselected_nodeids: list[str] = []
        self.failures: list[dict[str, str]] = []
        self.errors: list[dict[str, str]] = []
        self.skipped: list[dict[str, str]] = []
        self.expected_failures: list[str] = []
        self.unexpected_successes: list[str] = []
        self._skipped_nodeids: set[str] = set()
        self._expected_failure_nodeids: set[str] = set()
        self._unexpected_success_nodeids: set[str] = set()

    def pytest_collection_modifyitems(self, items):
        for item in items:
            nodeid = _sanitized_nodeid(item.nodeid)
            self.nodeids.append(nodeid)
            path = Path(str(item.path)).resolve()
            if path in self.collected_by_path:
                self.collected_by_path[path] += 1

    def pytest_collectreport(self, report):
        if report.failed:
            self.errors.append({
                "test": _sanitized_nodeid(report.nodeid),
                "traceback": _sanitized_detail(report.longrepr),
            })

    def pytest_deselected(self, items):
        self.deselected_nodeids.extend(_sanitized_nodeid(item.nodeid) for item in items)

    def pytest_internalerror(self, excrepr):
        self.errors.append({
            "test": "pytest-internal-error",
            "traceback": _sanitized_detail(excrepr),
        })

    def pytest_runtest_logreport(self, report):
        nodeid = _sanitized_nodeid(report.nodeid)
        if report.when == "call" or (
            report.when == "setup" and (report.failed or report.skipped)
        ):
            self.executed_nodeids.add(nodeid)
        was_xfail = getattr(report, "wasxfail", None)
        if was_xfail is not None and report.skipped:
            if nodeid not in self._expected_failure_nodeids:
                self.expected_failures.append(nodeid)
                self._expected_failure_nodeids.add(nodeid)
            return
        if was_xfail is not None and report.passed:
            if nodeid not in self._unexpected_success_nodeids:
                self.unexpected_successes.append(nodeid)
                self._unexpected_success_nodeids.add(nodeid)
            return
        if report.skipped:
            if nodeid not in self._skipped_nodeids:
                reason = report.longrepr[-1] if isinstance(report.longrepr, tuple) else report.longrepr
                self.skipped.append({"test": nodeid, "reason": _sanitized_detail(reason)})
                self._skipped_nodeids.add(nodeid)
            return
        if not report.failed:
            return
        target = self.failures if report.when == "call" else self.errors
        target.append({"test": nodeid, "traceback": _sanitized_detail(report.longrepr)})

    def outcome(self, selected: list[Path], exit_code: int) -> PytestOutcome:
        uncollected = []
        for path in selected:
            resolved = path.resolve()
            if resolved in self.nonempty and self.collected_by_path.get(resolved, 0) == 0:
                relative = self.selected[resolved]
                uncollected.append(relative)
                self.errors.append({
                    "test": relative,
                    "traceback": "Selected nonempty test module collected zero tests",
                })
        if self.deselected_nodeids:
            self.errors.append({
                "test": "pytest-selection",
                "traceback": (
                    f"{len(self.deselected_nodeids)} selected tests were deselected"
                ),
            })
        unexecuted = sorted(set(self.nodeids) - self.executed_nodeids)
        if unexecuted:
            preview = ", ".join(unexecuted[:10])
            suffix = "" if len(unexecuted) <= 10 else f" (+{len(unexecuted) - 10} more)"
            self.errors.append({
                "test": "pytest-execution",
                "traceback": (
                    f"{len(unexecuted)} collected tests produced no execution result: "
                    f"{preview}{suffix}"
                ),
            })
        return PytestOutcome(
            exit_code=exit_code,
            tests_run=len(self.executed_nodeids),
            failures=self.failures,
            errors=self.errors,
            skipped=self.skipped,
            expected_failures=self.expected_failures,
            unexpected_successes=self.unexpected_successes,
            collected_by_file={self.selected[path]: self.collected_by_path[path]
                               for path in sorted(self.selected, key=lambda item: self.selected[item])},
            uncollected_test_files=sorted(uncollected),
        )


def run_pytest(selected: list[Path], *, verbose: bool) -> PytestOutcome:
    """Run exactly the selected modules and return a structured result.

    Pytest is invoked in-process so imported package module hashes still describe
    the code exercised by this acceptance process. Third-party plugin autoload is
    disabled to keep the selected runner independent of the host environment.
    """
    plugin = _AcceptancePlugin(selected)
    arguments = [str(path.resolve()) for path in selected]
    arguments.extend(("-p", "no:cacheprovider", "-o", "addopts=", "--color=no", "--tb=short",
                      "-vv" if verbose else "-q"))
    controlled_environment = (
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
    )
    previous_environment = {name: os.environ.get(name) for name in controlled_environment}
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ.pop("PYTEST_ADDOPTS", None)
    os.environ.pop("PYTEST_PLUGINS", None)
    try:
        # The historical runner wrote test progress to stderr and reserved stdout
        # for its machine-readable one-line summary.
        with redirect_stdout(sys.stderr):
            exit_code = int(pytest.main(arguments, plugins=[plugin]))
    finally:
        for name, previous in previous_environment.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
    return plugin.outcome(selected, exit_code)


def hashes(paths):
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def evidence_artifact_files():
    """Return every declared parity artifact under this source/snapshot root.

    The same set feeds acceptance's before/after hashes and the installed-wheel
    snapshot manifest. A new evidence record must not silently refer to an
    artifact that was absent from the tested, copied inputs.
    """
    root = ROOT.resolve()
    bundle = ROOT / "src/cbus_toolkit/parity-evidence.json"
    if not bundle.is_file():
        if (bundle.exists() or bundle.is_symlink()
                or (ROOT / "src/cbus_toolkit/parity-obligations.json").exists()):
            raise ValueError("Parity evidence bundle is missing")
        # Historical/minimal acceptance fixtures can predate the register.
        return set()
    if not bundle.resolve(strict=True).is_relative_to(root):
        raise ValueError("Parity evidence bundle escapes its root")

    from cbus_toolkit.parity import parse_json_document

    document = parse_json_document(bundle.read_bytes(), context="parity-evidence.json")
    records = document.get("records") if isinstance(document, dict) else None
    if not isinstance(records, list):
        raise ValueError("Parity evidence bundle requires a records array")
    names = []
    for record in records:
        artifacts = record.get("artifacts") if isinstance(record, dict) else None
        if not isinstance(artifacts, list):
            raise ValueError("Parity evidence record requires an artifacts array")
        names.extend(artifact.get("path") if isinstance(artifact, dict) else None
                     for artifact in artifacts)
    # Closure receipts are verified against the same trusted root, so their
    # artifacts must be copied with the evidence they close.
    register = ROOT / "src/cbus_toolkit/parity-obligations.json"
    if register.is_file():
        receipts = parse_json_document(
            register.read_bytes(), context="parity-obligations.json").get("closure_receipts", [])
        if not isinstance(receipts, list):
            raise ValueError("Parity register closure_receipts must be an array")
        names.extend((receipt.get("receipt_artifact") or {}).get("path") if isinstance(receipt, dict) else None
                     for receipt in receipts)
    paths = set()
    for name in names:
        if not isinstance(name, str) or not name or "\\" in name or any(ord(c) < 32 for c in name):
            raise ValueError("Parity evidence has an unsafe artifact path")
        relative = PurePosixPath(name)
        if (relative.is_absolute() or relative.as_posix() != name
                or ".." in relative.parts or PureWindowsPath(name).drive):
            raise ValueError("Parity evidence has an unsafe artifact path: " + name)
        candidate = ROOT.joinpath(*relative.parts)
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise ValueError("Parity evidence artifact is missing: " + name) from error
        if not resolved.is_relative_to(root):
            raise ValueError("Parity evidence artifact escapes its root: " + name)
        if not resolved.is_file():
            raise ValueError("Parity evidence artifact is not a file: " + name)
        paths.add(candidate)
    return paths


def input_files(pattern):
    """Include local harnesses and fixture data as well as production code."""
    paths = set((ROOT / "tests").glob(pattern))
    paths.update(path for path in (ROOT / "tests").glob("*.py") if not path.name.startswith("test_"))
    for directory, suffixes in ((ROOT / "src/cbus_toolkit", ("*.py", "*.json")),
                                (ROOT / "research", ("*.py", "*.java", "*.cs")),
                                (ROOT / "research/fixtures", ("*.json", "*.txt")),
                                (ROOT / "research/release-gates", ("*.json",))):
        for suffix in suffixes:
            paths.update(directory.glob(suffix))
    paths.update(evidence_artifact_files())
    if (ROOT / "pyproject.toml").is_file():
        paths.add(ROOT / "pyproject.toml")
    return paths


TEST_BINARY_SELECTIONS = {
    "CBUS_CGATE_MOCK_BIN": {"test_rust_cgate_interop.py"},
    "CBUS_CMQTTD_BIN": {
        "test_cmqtt_interop.py",
        "test_cmqtt_programming_methods_interop.py",
    },
}


def _test_binary_input(name):
    """Observe one configured binary without executing or rebuilding it."""
    configured = os.environ.get(name)
    if not configured:
        return None
    row = {"path": str(Path(configured).absolute())}
    try:
        path = Path(configured).resolve(strict=True)
        row["path"] = str(path)
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
                raise ValueError("Test binary must be a regular executable file")
            if not 0 < info.st_size <= 256 * 1024 * 1024:
                raise ValueError("Test binary is empty or exceeds the byte bound")
            digest = hashlib.sha256()
            size = 0
            while block := os.read(descriptor, 1024 * 1024):
                digest.update(block)
                size += len(block)
                if size > 256 * 1024 * 1024:
                    raise ValueError("Test binary grew beyond the byte bound")
            row.update(sha256=digest.hexdigest(), size_bytes=size)
        finally:
            os.close(descriptor)
    except (OSError, ValueError) as error:
        row["error"] = type(error).__name__
    return row


def test_binary_inputs(selected):
    """Record selected explicit test binaries; this is byte identity, not build provenance."""
    selected_names = {path.name for path in selected}
    result = {}
    for name, modules in TEST_BINARY_SELECTIONS.items():
        if selected_names.isdisjoint(modules):
            continue
        row = _test_binary_input(name)
        if row is not None:
            result[name] = row
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pattern", default="test_*.py")
    parser.add_argument("--require-no-skips", action="store_true")
    parser.add_argument("--verbose", action="store_true", help="Write each test name to the run log")
    parser.add_argument("--output", type=Path, default=ROOT / "research/runtime/test-acceptance.json")
    args = parser.parse_args()
    import cbus_toolkit
    started = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    selected = sorted(path for path in (ROOT / "tests").glob(args.pattern) if path.is_file())
    if not selected:
        parser.error("No test files match this pattern")
    inputs = input_files(args.pattern)
    before = hashes(inputs)
    binaries_before = test_binary_inputs(selected)
    # Support both discovered test modules and explicit tests.* helper imports
    # when this script runs from an isolated installed-wheel environment.
    sys.path.insert(0, str(ROOT))
    result = run_pytest(selected, verbose=args.verbose)
    binaries_after = test_binary_inputs(selected)
    binary_errors = sorted(name for name in binaries_before.keys() | binaries_after.keys()
                           if binaries_before.get(name) != binaries_after.get(name)
                           or "error" in binaries_before.get(name, {})
                           or "error" in binaries_after.get(name, {}))
    after = hashes(input_files(args.pattern))
    changed = [path for path in before if path in after and before[path] != after[path]]
    removed = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    added_tests = sorted(str(path.relative_to(ROOT)) for path in (ROOT / "tests").glob(args.pattern)
                         if path not in selected)
    added_sources = sorted(str(path.relative_to(ROOT)) for path in (ROOT / "src/cbus_toolkit").glob("*.py")
                           if path not in inputs)
    package = resources.files("cbus_toolkit")
    ledger_raw = package.joinpath("capabilities.json").read_bytes()
    ledger = json.loads(ledger_raw)
    try:
        from cbus_toolkit import parity

        register_raw = package.joinpath(parity.REGISTER_RESOURCE).read_bytes()
        evidence_raw = package.joinpath(parity.EVIDENCE_RESOURCE).read_bytes()
        cgate_contract_raw = package.joinpath(parity.CGATE_CONTRACT_RESOURCE).read_bytes()
        progress = parity.evaluate(
            parity.parse_json_document(register_raw, context=parity.REGISTER_RESOURCE),
            parity.parse_json_document(evidence_raw, context=parity.EVIDENCE_RESOURCE),
            ledger,
            evidence_raw=evidence_raw,
            ledger_raw=ledger_raw,
            cgate_contract_inventory=parity.parse_json_document(
                cgate_contract_raw, context=parity.CGATE_CONTRACT_RESOURCE
            ),
            cgate_contract_raw=cgate_contract_raw,
            artifact_root=ROOT,
        )
    except FileNotFoundError:
        # Historical/minimal acceptance fixtures predate the evidence register.
        # They can remain auditable but can never claim parity completion.
        progress = {
            "complete": False,
            "functional_percent_available": False,
            "blockers": ["installed artifact has no parity obligation register"],
        }
    complete = bool(progress["complete"])
    report = {
        "format": "cbus-test-acceptance-v1", "started_at": started,
        "duration_seconds": round(time.monotonic() - start, 3),
        "python": platform.python_version(), "openssl": ssl.OPENSSL_VERSION,
        "package_version": cbus_toolkit.__version__, "package_location": cbus_toolkit.__file__,
        "tests_run": result.tests_run, "failures": len(result.failures), "errors": len(result.errors),
        "skipped": result.skipped,
        "expected_failures": len(result.expected_failures),
        "unexpected_successes": len(result.unexpected_successes),
        "pytest_exit_code": result.exit_code,
        "collected_tests_by_file": result.collected_by_file,
        "uncollected_test_files": result.uncollected_test_files,
        "test_success": result.was_successful(), "require_no_skips": args.require_no_skips,
        "passed": result.was_successful() and not result.expected_failures
                  and not result.unexpected_successes and not changed and not added and not removed
                  and not binary_errors
                  and (not args.require_no_skips or not result.skipped),
        "toolkit_parity_complete": complete,
        "toolkit_parity_progress": progress,
        "scope": "These selected acceptance tests do not establish full Toolkit functionality or physical-device parity.",
        "backend_selectors": {
            "CBUS_ORIGINAL_MODEL_BACKEND": os.environ.get("CBUS_ORIGINAL_MODEL_BACKEND", "docker"),
            "CBUS_EDLT_LIFECYCLE_ORIGINAL_BACKEND": os.environ.get("CBUS_EDLT_LIFECYCLE_ORIGINAL_BACKEND", "docker"),
            "CBUS_NATIVE_SERVICE_BACKEND": os.environ.get("CBUS_NATIVE_SERVICE_BACKEND", "docker"),
            "CBUS_WINDOWS_BRIDGE": os.environ.get("CBUS_WINDOWS_BRIDGE") == "1",
            **({"CBUS_FIRMWARE_ORACLE_BACKEND": os.environ.get("CBUS_FIRMWARE_ORACLE_BACKEND", "docker")}
               if "research/firmware_oracle.py" in before else {})},
        "enabled_native_gates": {name: os.environ.get(name) == "1" if name in ("CBUS_SCENE_NATIVE", "CBUS_NATIVE_TLS_TEST", "CBUS_WINDOWS_BRIDGE")
                                 else bool(os.environ.get(name)) for name in
            ("CBUS_CGATE_TEST_HOST", "CBUS_UNITSPEC_DIR", "CBUS_TOOLKIT_HELP_DIR", "CBUS_TOOLKIT_EXE",
             "CBUS_SCENE_NATIVE", "CBUS_NATIVE_TLS_TEST", "CBUS_FIRMWARE_UPDATER", "CBUS_DFU_DLL",
             "CBUS_WINDOWS_BRIDGE", "CBUS_CGATE_JAVA", "CBUS_LOCAL_CGATE_VENDOR", "CBUS_MONO_MACOS_ROOT",
             "CBUS_WINDOWS_PROVENANCE_ROOT", "CBUS_CATALOG_PATH", "CBUS_CGATE_MOCK_BIN",
             "CBUS_CMQTTD_BIN")},
        "external_test_binaries_before": binaries_before,
        "external_test_binaries_after": binaries_after,
        "external_test_binary_errors": binary_errors,
        "test_files": [str(path.relative_to(ROOT)) for path in sorted(selected)],
        "input_sha256": before, "inputs_changed_during_run": changed,
        "inputs_added_during_run": added, "inputs_removed_during_run": removed,
        "test_files_added_during_run": added_tests,
        "source_files_added_during_run": added_sources,
        "imported_package_module_sha256": {name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for name, module in sorted(sys.modules.items()) if name.startswith("cbus_toolkit")
            and getattr(module, "__file__", "").endswith(".py") and Path(module.__file__).is_file()},
        "failed_tests": result.failures + result.errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("passed", "tests_run", "failures", "errors", "skipped",
                                                 "duration_seconds", "toolkit_parity_complete")}))
    return int(not report["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
