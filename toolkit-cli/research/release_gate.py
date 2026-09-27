#!/usr/bin/env python3
"""Run an exact provisioned pytest gate and retain a sanitized receipt.

The manifest names tests and required environment variables, but never stores
their values.  This runner is for native and physical-hardware acceptance;
ordinary offline CI should invoke pytest directly and retain its JUnit report.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
FORMAT = "cbus-provisioned-release-gate-v1"
KINDS = {"value", "flag", "file", "directory", "executable"}
ENVIRONMENT_NAME = re.compile(r"CBUS_[A-Z0-9_]+")


class GateError(ValueError):
    """A manifest, provision, or result cannot support this gate."""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GateError(message)


def load_manifest(path: Path, expected_gate: str) -> dict:
    try:
        manifest = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise GateError(f"Cannot read gate manifest: {type(error).__name__}") from error
    _require(isinstance(manifest, dict) and manifest.get("format") == FORMAT,
             "Unsupported release-gate manifest")
    _require(manifest.get("gate") == expected_gate, "Release-gate manifest selects the wrong gate")
    systems = manifest.get("systems")
    _require(isinstance(systems, list) and systems and all(isinstance(value, str) for value in systems),
             "Release-gate manifest needs at least one system")
    _require(platform.system() in systems,
             f"Gate {expected_gate} requires one of {systems}; this host is {platform.system()}")
    tests = manifest.get("tests")
    _require(isinstance(tests, list) and tests and len(tests) == len(set(tests)),
             "Release-gate test selection must be nonempty and unique")
    for test in tests:
        _require(isinstance(test, str) and "\0" not in test and "\n" not in test,
                 "Invalid release-gate test selector")
        file_name = test.split("::", 1)[0]
        relative = PurePosixPath(file_name)
        _require(not relative.is_absolute() and ".." not in relative.parts
                 and len(relative.parts) == 2 and relative.parts[0] == "tests"
                 and relative.name.startswith("test_") and relative.suffix == ".py",
                 "Release-gate tests must select repository test modules or their node IDs")
        _require(ROOT.joinpath(*relative.parts).is_file(), f"Missing release-gate test module: {file_name}")
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
                                                    and not Path(item).is_absolute()
                                                    and ".." not in Path(item).parts
                                                    for item in contains),
                 f"Invalid contained paths for {name}")
    return manifest


def verify_provision(manifest: dict, environment: dict[str, str]) -> list[dict[str, object]]:
    """Verify provision without retaining paths or secret values."""
    verified = []
    for name, requirement in sorted(manifest["required_environment"].items()):
        value = environment.get(name, "")
        _require(bool(value), f"Required provision is missing: {name}")
        kind = requirement["kind"]
        if kind == "flag":
            _require(value == "1", f"Required provision must equal 1: {name}")
        elif kind != "value":
            path = Path(value).expanduser()
            if kind == "file":
                _require(path.is_file(), f"Required provision is not a file: {name}")
            elif kind == "directory":
                _require(path.is_dir(), f"Required provision is not a directory: {name}")
            else:
                _require(path.is_file() and os.access(path, os.X_OK),
                         f"Required provision is not an executable file: {name}")
            for relative in requirement.get("contains", []):
                _require(path.joinpath(*Path(relative).parts).is_file(),
                         f"Required provision lacks {relative}: {name}")
        verified.append({"name": name, "kind": kind, "present": True})
    return verified


def junit_result(path: Path) -> dict[str, object]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        raise GateError(f"Cannot read pytest JUnit result: {type(error).__name__}") from error
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    _require(bool(suites), "Pytest JUnit result contains no test suites")
    counters = {name: sum(int(suite.attrib.get(name, "0")) for suite in suites)
                for name in ("tests", "failures", "errors", "skipped")}
    skipped = []
    for case in root.iter("testcase"):
        node = "::".join(value for value in (case.attrib.get("classname"), case.attrib.get("name")) if value)
        if (skip := case.find("skipped")) is not None:
            skipped.append({"test": node, "reason": skip.attrib.get("message", "")})
    _require(counters["tests"] > 0, "Provisioned gate executed zero tests")
    _require(counters["skipped"] == len(skipped), "JUnit skipped-test details are incomplete")
    return {**counters, "passed": counters["tests"] - counters["failures"]
            - counters["errors"] - counters["skipped"], "skip_details": skipped}


def source_revision() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                            capture_output=True, check=False)
    if result.returncode or re.fullmatch(r"[0-9a-f]{40}\n?", result.stdout) is None:
        raise GateError("Cannot identify the source revision")
    return result.stdout.strip()


def write_receipt(path: Path, receipt: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--gate", choices=("native", "hardware"), required=True)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    receipt: dict[str, object] = {
        "format": FORMAT,
        "gate": args.gate,
        "started_at": started,
        "passed": False,
    }
    try:
        manifest_path = args.manifest.resolve(strict=True)
        manifest = load_manifest(manifest_path, args.gate)
        receipt.update(
            source_revision=source_revision(),
            manifest_sha256=digest(manifest_path),
            selected_tests=manifest["tests"],
            verified_provision=verify_provision(manifest, os.environ),
        )
        args.junit.parent.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, "-m", "pytest", *manifest["tests"], "-q", "-ra",
                   "-p", "no:cacheprovider", f"--junitxml={args.junit.resolve()}"]
        result = subprocess.run(command, cwd=ROOT, check=False)
        outcome = junit_result(args.junit)
        receipt.update(pytest_exit=result.returncode, result=outcome)
        receipt["passed"] = (result.returncode == 0 and outcome["failures"] == 0
                             and outcome["errors"] == 0 and outcome["skipped"] == 0)
        if outcome["skipped"]:
            receipt["error"] = "Provisioned release gates do not permit skipped tests"
        elif result.returncode:
            receipt["error"] = "Pytest failed"
    except (GateError, OSError) as error:
        receipt["error"] = str(error)
    receipt["duration_seconds"] = round(time.monotonic() - start, 3)
    write_receipt(args.output, receipt)
    print(json.dumps({key: receipt.get(key) for key in ("gate", "passed", "error", "result")},
                     sort_keys=True))
    return int(not receipt["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
