#!/usr/bin/env python3
"""Run a provisioned acceptance selection with independently checked evidence.

The JSON receipt contains digests and counts, never endpoint values, private
paths, test names, or captured pytest output. JUnit and the private trace are
separate artifacts. This runner requires an installed, non-editable wheel.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import sys
import sysconfig
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FORMAT = "cbus-provisioned-release-gate-v1"
TRACE_FORMAT = "cbus-release-gate-pytest-trace-v1"
KINDS = {"value", "flag", "file", "directory", "executable"}
ENVIRONMENT_NAME = re.compile(r"CBUS_[A-Z0-9_]+")
SOURCE_PATHS = ("src", "tests", "research", "conftest.py", "pyproject.toml", "Makefile")
EXECUTABLE_SUFFIXES = {".py", ".pyi", ".pyc", ".so", ".pyd"}


class GateError(ValueError):
    """A manifest, provision, or result cannot support this gate."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GateError(message)


def digest(path: Path) -> str:
    before = path.stat()
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    after = path.stat()
    identity = lambda stat: (stat.st_dev, stat.st_ino, stat.st_size,
                             stat.st_mtime_ns, stat.st_ctime_ns)
    _require(identity(before) == identity(after), "Gate input changed while hashing")
    return value.hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        _require(key not in value, "Duplicate JSON key in gate evidence")
        value[key] = item
    return value


def _read_json(path: Path, kind: str) -> dict:
    try:
        value = json.loads(path.read_text(), object_pairs_hook=_unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(
                               GateError("Non-finite number in gate evidence")))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GateError(f"Cannot read {kind}: {type(error).__name__}") from error
    _require(isinstance(value, dict), f"Invalid {kind}")
    return value


def _tree_snapshot(paths: list[Path], base: Path) -> dict[str, object]:
    """Bind names and contents while exposing only the aggregate digest."""
    records: list[tuple[str, int, str]] = []
    for path in sorted(set(paths)):
        _require(path.is_file() and not path.is_symlink(),
                 "Gate input file is missing, linked, or not regular")
        relative = path.relative_to(base).as_posix()
        file_digest = digest(path)
        records.append((relative, path.stat().st_size, file_digest))
    encoded = json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "files": len(records),
            "bytes": sum(item[1] for item in records)}


def _directory_snapshot(directory: Path) -> dict[str, object]:
    entries = list(directory.rglob("*"))
    _require(all(not item.is_symlink() and (item.is_file() or item.is_dir())
                 for item in entries),
             "Provision directory contains a link or unsupported entry")
    files = [item for item in entries if item.is_file()]
    _require(bool(files), "Provision directory is empty")
    snapshot = _tree_snapshot(files, directory)
    _require(set(entries) == set(directory.rglob("*")),
             "Provision directory changed while hashing")
    return snapshot


def load_manifest(path: Path, expected_gate: str) -> dict:
    manifest = _read_json(path, "gate manifest")
    _require(manifest.get("format") == FORMAT, "Unsupported release-gate manifest")
    _require(manifest.get("gate") == expected_gate, "Release-gate manifest selects the wrong gate")
    systems = manifest.get("systems")
    _require(isinstance(systems, list) and systems
             and all(isinstance(value, str) and value for value in systems),
             "Release-gate manifest needs at least one system")
    _require(platform.system() in systems,
             "Host does not match release-gate system requirements")
    tests = manifest.get("tests")
    _require(isinstance(tests, list) and tests
             and all(isinstance(test, str) for test in tests)
             and len(tests) == len(set(tests)),
             "Release-gate test selection must be nonempty and unique")
    for test in tests:
        _require(test and not any(char in test for char in "\0\r\n"),
                 "Invalid release-gate test selector")
        file_name = test.split("::", 1)[0]
        relative = PurePosixPath(file_name)
        _require(not relative.is_absolute() and ".." not in relative.parts
                 and len(relative.parts) == 2 and relative.parts[0] == "tests"
                 and relative.name.startswith("test_") and relative.suffix == ".py"
                 and all(part for part in test.split("::")),
                 "Release-gate tests must select repository test modules or their node IDs")
        module = ROOT.joinpath(*relative.parts)
        _require(module.is_file() and module.resolve().is_relative_to((ROOT / "tests").resolve()),
                 "Missing release-gate test module")
    requirements = manifest.get("required_environment")
    _require(isinstance(requirements, dict) and requirements,
             "Release-gate manifest needs explicit provisioning requirements")
    for name, requirement in requirements.items():
        _require(isinstance(name, str) and ENVIRONMENT_NAME.fullmatch(name) is not None,
                 "Invalid release-gate environment name")
        _require(isinstance(requirement, dict) and requirement.get("kind") in KINDS,
                 f"Invalid provision rule for {name}")
        contains = requirement.get("contains", [])
        _require(isinstance(contains, list) and all(isinstance(item, str) and item
                                                    and not PurePosixPath(item).is_absolute()
                                                    and ".." not in PurePosixPath(item).parts
                                                    for item in contains),
                 f"Invalid contained paths for {name}")
        _require(not contains or requirement["kind"] == "directory",
                 f"Contained paths require a directory provision: {name}")
        # A selector value such as CBUS_NATIVE_SERVICE_BACKEND=local is public
        # configuration, not an endpoint, so a value rule may pin it exactly.
        _require("equals" not in requirement
                 or (requirement["kind"] == "value" and isinstance(requirement["equals"], str)
                     and requirement["equals"]),
                 f"An exact value requires a nonempty value provision: {name}")
    return manifest


def verify_provision(manifest: dict, environment: dict[str, str]) -> list[dict[str, object]]:
    """Hash file provisions and directory trees without retaining their paths."""
    verified = []
    for name, requirement in sorted(manifest["required_environment"].items()):
        value = environment.get(name, "")
        _require(bool(value), f"Required provision is missing: {name}")
        kind = requirement["kind"]
        entry: dict[str, object] = {"name": name, "kind": kind, "present": True}
        if kind == "flag":
            _require(value == "1", f"Required provision must equal 1: {name}")
        elif "equals" in requirement:
            _require(value == requirement["equals"],
                     f"Required provision must equal {requirement['equals']}: {name}")
            entry["equals"] = requirement["equals"]
        elif kind != "value":
            path = Path(value).expanduser()
            if kind == "file":
                _require(path.is_file(), f"Required provision is not a file: {name}")
            elif kind == "directory":
                _require(path.is_dir() and not path.is_symlink(),
                         f"Required provision is not a regular directory: {name}")
            else:
                _require(path.is_file() and os.access(path, os.X_OK),
                         f"Required provision is not an executable file: {name}")
            if kind == "directory":
                for relative in requirement.get("contains", []):
                    contained = path.joinpath(*PurePosixPath(relative).parts)
                    _require(contained.is_file() and contained.resolve().is_relative_to(path.resolve()),
                             f"Required provision lacks a contained file: {name}")
                entry.update(_directory_snapshot(path.resolve()))
            else:
                entry.update(sha256=digest(path), bytes=path.stat().st_size)
        verified.append(entry)
    return verified


def source_inputs(selectors: list[str]) -> dict[str, object]:
    result = subprocess.run(["git", "ls-files", "-z", "--", *SOURCE_PATHS],
                            cwd=ROOT, capture_output=True, check=False)
    _require(result.returncode == 0, "Cannot enumerate checked-in gate inputs")
    paths = {ROOT / os.fsdecode(name) for name in result.stdout.split(b"\0") if name}
    required = {ROOT / test.split("::", 1)[0] for test in selectors}
    required.update((Path(__file__), Path(__file__).with_name("release_gate_pytest.py")))
    _require(required.issubset(paths),
             "Selected tests and gate runner/plugin must be tracked by the revision")
    others = subprocess.run(["git", "ls-files", "--others", "-z", "--",
                             "src", "tests", "research", "conftest.py"],
                            cwd=ROOT, capture_output=True, check=False)
    _require(others.returncode == 0, "Cannot enumerate untracked gate inputs")
    untracked = [PurePosixPath(os.fsdecode(name)) for name in others.stdout.split(b"\0") if name]
    _require(not any(path.suffix in EXECUTABLE_SUFFIXES
                     and "__pycache__" not in path.parts for path in untracked),
             "Untracked executable gate input is present")
    _require(all(path.resolve().is_relative_to(ROOT.resolve()) for path in paths),
             "Gate source input escapes the checkout")
    return _tree_snapshot(list(paths), ROOT)


def installed_package() -> dict[str, object]:
    package = Path(sysconfig.get_paths()["purelib"]) / "cbus_toolkit"
    _require(package.is_dir() and (package / "__init__.py").is_file(),
             "A non-editable installed Toolkit wheel is required")
    _require(not package.resolve().is_relative_to((ROOT / "src").resolve()),
             "Installed Toolkit package aliases the source tree")
    entries = list(package.rglob("*"))
    _require(not any(path.is_symlink() for path in entries),
             "Installed Toolkit package contains a link")
    files = [path for path in entries if path.is_file()
             and "__pycache__" not in path.parts and path.suffix != ".pyc"]
    _require(bool(files), "Installed Toolkit package is empty")
    return _tree_snapshot(files, package)


def wheel_package(environment: dict[str, str]) -> dict[str, object]:
    """Bind the archive and prove its RECORD-pinned package matches site-packages."""
    value = environment.get("CBUS_TOOLKIT_WHEEL", "")
    _require(bool(value), "Required installed wheel artifact is missing")
    wheel = Path(value).expanduser()
    _require(wheel.is_file() and wheel.name.startswith("cbus_toolkit_cli-")
             and wheel.suffix == ".whl",
             "Required installed wheel artifact is not a Toolkit wheel file")
    archive_digest = digest(wheel)
    package = Path(sysconfig.get_paths()["purelib"]) / "cbus_toolkit"
    source_package = ROOT / "src" / "cbus_toolkit"
    _require(package.is_dir() and (package / "__init__.py").is_file(),
             "A non-editable installed Toolkit wheel is required")
    _require(source_package.is_dir(), "Checkout Toolkit source package is missing")
    try:
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            _require(len(names) == len(set(names)), "Installed wheel has duplicate members")
            _require(all(not PurePosixPath(name).is_absolute()
                         and ".." not in PurePosixPath(name).parts
                         and "\\" not in name for name in names),
                     "Installed wheel has an unsafe member")
            records = [name for name in names if name.endswith(".dist-info/RECORD")]
            _require(len(records) == 1, "Installed wheel lacks a unique RECORD")
            rows = list(csv.reader(io.StringIO(archive.read(records[0]).decode("utf-8"))))
            _require(all(len(row) == 3 for row in rows), "Installed wheel RECORD is malformed")
            record = {row[0]: (row[1], row[2]) for row in rows}
            _require(len(record) == len(rows), "Installed wheel RECORD duplicates a member")
            members = sorted(name for name in names if name.startswith("cbus_toolkit/")
                             and not name.endswith("/"))
            _require(bool(members) and "cbus_toolkit/__init__.py" in members,
                     "Installed wheel contains no Toolkit package")
            package_entries = list(package.rglob("*"))
            _require(not any(path.is_symlink() for path in package_entries),
                     "Installed Toolkit package contains a link")
            installed = sorted(path.relative_to(package).as_posix() for path in package_entries
                               if path.is_file() and "__pycache__" not in path.parts
                               and path.suffix != ".pyc")
            source_entries = list(source_package.rglob("*"))
            _require(not any(path.is_symlink() for path in source_entries),
                     "Checkout Toolkit source contains a link")
            source = sorted(path.relative_to(source_package).as_posix()
                            for path in source_entries if path.is_file()
                            and "__pycache__" not in path.parts and path.suffix != ".pyc")
            expected = [name.removeprefix("cbus_toolkit/") for name in members]
            _require(installed == expected,
                     "Installed Toolkit package files differ from the wheel")
            _require(source == expected,
                     "Toolkit wheel package files differ from checkout source")
            for name in members:
                data = archive.read(name)
                encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
                _require(record.get(name) == ("sha256=" + encoded, str(len(data))),
                         "Installed wheel package member does not match RECORD")
                target = package / name.removeprefix("cbus_toolkit/")
                _require(target.is_file() and not target.is_symlink()
                         and digest(target) == hashlib.sha256(data).hexdigest(),
                         "Installed Toolkit package member differs from wheel")
                source_target = source_package / name.removeprefix("cbus_toolkit/")
                _require(digest(source_target) == hashlib.sha256(data).hexdigest(),
                         "Toolkit wheel package member differs from checkout source")
    except (OSError, UnicodeError, zipfile.BadZipFile, RuntimeError) as error:
        raise GateError(f"Cannot verify installed wheel artifact: {type(error).__name__}") from error
    _require(digest(wheel) == archive_digest,
             "Installed wheel artifact changed while verifying")
    return {"sha256": archive_digest, "bytes": wheel.stat().st_size,
            "package_members": len(members)}


def verify_test_import(environment: dict[str, str]) -> None:
    command = [sys.executable, "-c",
               "from pathlib import Path; import cbus_toolkit; "
               "print(Path(cbus_toolkit.__file__).resolve())"]
    result = subprocess.run(command, cwd=ROOT, env=environment, text=True,
                            capture_output=True, check=False)
    _require(result.returncode == 0, "Test environment cannot import installed Toolkit")
    expected = (Path(sysconfig.get_paths()["purelib"]) / "cbus_toolkit" / "__init__.py").resolve()
    _require(result.stdout.strip() == str(expected),
             "Test environment imports Toolkit from outside its installed wheel")


def junit_result(path: Path) -> dict[str, object]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        raise GateError(f"Cannot read pytest JUnit result: {type(error).__name__}") from error
    _require(root.tag in ("testsuite", "testsuites"), "Invalid pytest JUnit root")
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    _require(bool(suites), "Pytest JUnit result contains no test suites")
    try:
        counters = {name: sum(int(suite.attrib.get(name, "0")) for suite in suites)
                    for name in ("tests", "failures", "errors", "skipped")}
    except ValueError as error:
        raise GateError("Invalid JUnit counters") from error
    _require(all(value >= 0 for value in counters.values()), "Invalid JUnit counters")
    cases = list(root.iter("testcase"))
    _require(counters["tests"] > 0 and counters["tests"] == len(cases),
             "JUnit test count does not match test cases")
    _require(sum(case.find("failure") is not None for case in cases) == counters["failures"]
             and sum(case.find("error") is not None for case in cases) == counters["errors"]
             and sum(case.find("skipped") is not None for case in cases) == counters["skipped"],
             "JUnit outcome counters do not match test cases")
    nodeids = []
    for case in cases:
        properties = case.find("properties")
        matched = ([] if properties is None else
                   [item.attrib.get("value") for item in properties.findall("property")
                    if item.attrib.get("name") == "cbus_release_gate_nodeid"])
        _require(len(matched) == 1 and isinstance(matched[0], str) and matched[0],
                 "JUnit test case lacks a unique release-gate node ID")
        nodeids.append(matched[0])
    _require(len(nodeids) == len(set(nodeids)), "JUnit contains duplicate test node IDs")
    return {**counters, "passed": counters["tests"] - counters["failures"]
            - counters["errors"] - counters["skipped"], "nodeids": nodeids}


def trace_result(path: Path, selectors: list[str], junit: dict[str, object], exit_code: int) -> dict:
    trace = _read_json(path, "pytest execution trace")
    _require(trace.get("format") == TRACE_FORMAT, "Invalid pytest execution trace")
    collected = trace.get("collected")
    executed = trace.get("executed")
    deselected = trace.get("deselected")
    _require(all(isinstance(value, list) and all(isinstance(item, str) and item for item in value)
                 for value in (collected, executed, deselected)),
             "Invalid pytest execution trace lists")
    _require(not deselected, "Pytest deselected a provisioned test")
    _require(bool(collected) and len(collected) == len(set(collected)),
             "Pytest collected no unique provisioned tests")
    _require(Counter(collected) == Counter(executed),
             "A collected provisioned test did not execute exactly once")
    _require(Counter(executed) == Counter(junit["nodeids"]),
             "JUnit cases do not match executed provisioned tests")
    _require(trace.get("session_exitstatus") == exit_code,
             "Pytest trace exit status does not match the process")
    def matches(node: str, selector: str) -> bool:
        return (node == selector or node.startswith(selector + "::")
                or node.startswith(selector + "["))
    for selector in selectors:
        _require(any(matches(node, selector) for node in collected),
                 "A selected test module or node collected zero tests")
    _require(all(any(matches(node, selector) for selector in selectors) for node in collected),
             "Pytest collected a test outside the declared selection")
    return {"collected": len(collected), "executed": len(executed), "deselected": 0}


def source_revision() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                            capture_output=True, check=False)
    if result.returncode or re.fullmatch(r"[0-9a-f]{40}\n?", result.stdout) is None:
        raise GateError("Cannot identify the source revision")
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                           cwd=ROOT, text=True,
                           capture_output=True, check=False)
    _require(dirty.returncode == 0 and not dirty.stdout,
             "Tracked checkout differs from its revision")
    return result.stdout.strip()


def write_receipt(path: Path, receipt: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--gate", choices=("native", "hardware"), required=True)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    start = time.monotonic()
    receipt: dict[str, object] = {
        "format": FORMAT, "gate": args.gate,
        "started_at": datetime.now(timezone.utc).isoformat(), "passed": False,
    }
    try:
        _require(not os.environ.get("PYTEST_ADDOPTS") and not os.environ.get("PYTEST_PLUGINS"),
                 "Inherited pytest options or plugins are forbidden in release gates")
        manifest_path = args.manifest.resolve(strict=True)
        manifest = load_manifest(manifest_path, args.gate)
        provision = verify_provision(manifest, os.environ)
        source = source_inputs(manifest["tests"])
        package = installed_package()
        wheel = wheel_package(os.environ)
        receipt.update(source_revision=source_revision(), manifest_sha256=digest(manifest_path),
                       selection_sha256=hashlib.sha256(json.dumps(manifest["tests"],
                           separators=(",", ":")).encode()).hexdigest(),
                       selected_test_count=len(manifest["tests"]),
                       source_inputs=source, installed_package=package,
                       wheel_artifact=wheel,
                       verified_provision=provision)
        args.junit.parent.mkdir(parents=True, exist_ok=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        _require(args.junit.resolve() != args.output.resolve(),
                 "JUnit and receipt output paths must differ")
        args.junit.unlink(missing_ok=True)
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "tests")
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        environment.pop("PYTEST_ADDOPTS", None)
        environment.pop("PYTEST_PLUGINS", None)
        verify_test_import(environment)
        with tempfile.TemporaryDirectory(prefix="cbus-release-gate-") as temporary:
            config = Path(temporary) / "pytest.ini"
            config.write_text("[pytest]\n")
            trace = Path(temporary) / "trace.json"
            command = [sys.executable, "-m", "pytest", "-c", str(config),
                       "--rootdir", str(ROOT), "--confcutdir", str(ROOT),
                       "-p", "research.release_gate_pytest",
                       "--cbus-release-gate-trace", str(trace),
                       *manifest["tests"], "-q", "-ra", "-p", "no:cacheprovider",
                       f"--junitxml={args.junit.resolve()}"]
            result = subprocess.run(command, cwd=ROOT, env=environment, check=False)
            _require(source_inputs(manifest["tests"]) == source,
                     "Gate source inputs changed during execution")
            _require(installed_package() == package,
                     "Installed Toolkit package changed during execution")
            _require(wheel_package(os.environ) == wheel,
                     "Installed wheel artifact changed during execution")
            _require(verify_provision(manifest, os.environ) == provision,
                     "Provision artifacts changed during execution")
            _require(digest(manifest_path) == receipt["manifest_sha256"],
                     "Gate manifest changed during execution")
            junit = junit_result(args.junit)
            trace_summary = trace_result(trace, manifest["tests"], junit, result.returncode)
            receipt.update(pytest_exit=result.returncode,
                           result={key: value for key, value in junit.items() if key != "nodeids"},
                           execution=trace_summary,
                           junit_sha256=digest(args.junit), trace_sha256=digest(trace))
            _require(result.returncode == 0, "Pytest failed")
            _require(junit["failures"] == junit["errors"] == junit["skipped"] == 0,
                     "Provisioned release gates do not permit failed or skipped tests")
            receipt["passed"] = True
    except GateError as error:
        receipt["error"] = str(error)
    except OSError as error:
        receipt["error"] = f"OS error while running release gate: {type(error).__name__}"
    receipt["duration_seconds"] = round(time.monotonic() - start, 3)
    write_receipt(args.output, receipt)
    print(json.dumps({key: receipt.get(key) for key in ("gate", "passed", "error", "result")},
                     sort_keys=True))
    return int(not receipt["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
