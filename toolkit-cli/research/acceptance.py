#!/usr/bin/env python3
"""Run acceptance tests with a durable result; test success is not parity."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import resources
import json
import os
from pathlib import Path
import platform
import ssl
import sys
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


def hashes(paths):
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def input_files(pattern):
    """Include local harnesses and fixture data as well as production code."""
    paths = set((ROOT / "tests").glob(pattern))
    paths.update(path for path in (ROOT / "tests").glob("*.py") if not path.name.startswith("test_"))
    for directory, suffixes in ((ROOT / "src/cbus_toolkit", ("*.py", "*.json")),
                                (ROOT / "research", ("*.py", "*.java", "*.cs")),
                                (ROOT / "research/fixtures", ("*.json", "*.txt"))):
        for suffix in suffixes:
            paths.update(directory.glob(suffix))
    if (ROOT / "pyproject.toml").is_file():
        paths.add(ROOT / "pyproject.toml")
    return paths


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
    selected = list((ROOT / "tests").glob(args.pattern))
    if not selected:
        parser.error("No test files match this pattern")
    inputs = input_files(args.pattern)
    before = hashes(inputs)
    # Support both discovered test modules and explicit tests.* helper imports
    # when this script runs from an isolated installed-wheel environment.
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=args.pattern)
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2 if args.verbose else 1).run(suite)
    after = hashes(input_files(args.pattern))
    changed = [path for path in before if path in after and before[path] != after[path]]
    removed = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    added_tests = sorted(str(path.relative_to(ROOT)) for path in (ROOT / "tests").glob(args.pattern)
                         if path not in selected)
    added_sources = sorted(str(path.relative_to(ROOT)) for path in (ROOT / "src/cbus_toolkit").glob("*.py")
                           if path not in inputs)
    ledger = json.loads(resources.files("cbus_toolkit").joinpath("capabilities.json").read_text())
    complete = bool(ledger["census_complete"] and all(row["status"] == "verified" for row in ledger["features"]))
    report = {
        "format": "cbus-test-acceptance-v1", "started_at": started,
        "duration_seconds": round(time.monotonic() - start, 3),
        "python": platform.python_version(), "openssl": ssl.OPENSSL_VERSION,
        "package_version": cbus_toolkit.__version__, "package_location": cbus_toolkit.__file__,
        "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "skipped": [{"test": test.id(), "reason": reason} for test, reason in result.skipped],
        "expected_failures": len(result.expectedFailures), "unexpected_successes": len(result.unexpectedSuccesses),
        "test_success": result.wasSuccessful(), "require_no_skips": args.require_no_skips,
        "passed": result.wasSuccessful() and not result.expectedFailures and not changed and not added and not removed
                  and (not args.require_no_skips or not result.skipped),
        "toolkit_parity_complete": complete,
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
             "CBUS_WINDOWS_PROVENANCE_ROOT", "CBUS_CATALOG_PATH")},
        "test_files": [str(path.relative_to(ROOT)) for path in sorted(selected)],
        "input_sha256": before, "inputs_changed_during_run": changed,
        "inputs_added_during_run": added, "inputs_removed_during_run": removed,
        "test_files_added_during_run": added_tests,
        "source_files_added_during_run": added_sources,
        "imported_package_module_sha256": {name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for name, module in sorted(sys.modules.items()) if name.startswith("cbus_toolkit")
            and getattr(module, "__file__", "").endswith(".py") and Path(module.__file__).is_file()},
        "failed_tests": [{"test": test.id(), "traceback": detail} for test, detail in result.failures + result.errors],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("passed", "tests_run", "failures", "errors", "skipped",
                                                 "duration_seconds", "toolkit_parity_complete")}))
    return int(not report["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
