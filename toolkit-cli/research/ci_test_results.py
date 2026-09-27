#!/usr/bin/env python3
"""Bind a CI pytest selection to its actual JUnit cases and execution trace.

Pytest's JUnit ``tests`` counter includes unittest subtests that it does not
emit as separate ``testcase`` elements. Report that difference explicitly;
never present the counter as a list of individually identified tests.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

try:
    import pytest
except ModuleNotFoundError:  # The wheel job audits with the base Python.
    pytest = None


FORMAT = "cbus-ci-test-results-v1"
TRACE_FORMAT = "cbus-ci-pytest-trace-v1"
TOOLKIT_ROOT = Path(__file__).resolve().parents[1]


class AuditError(ValueError):
    """The result cannot prove that the intended selection executed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def _nodeid(item) -> str:
    relative = item.path.resolve().relative_to(item.config.rootpath.resolve()).as_posix()
    suffix = item.nodeid.split("::", 1)
    return relative + ("::" + suffix[1] if len(suffix) == 2 else "")


def pytest_addoption(parser) -> None:
    parser.getgroup("cbus CI results").addoption("--cbus-ci-trace", metavar="PATH")


def pytest_configure(config) -> None:
    config._cbus_ci_collected = []
    config._cbus_ci_deselected = []
    config._cbus_ci_started = []
    config._cbus_ci_call_events = []


def pytest_deselected(items) -> None:
    if items:
        items[0].config._cbus_ci_deselected.extend(_nodeid(item) for item in items)


def pytest_collection_finish(session) -> None:
    nodeids = [_nodeid(item) for item in session.items]
    session.config._cbus_ci_collected = nodeids
    for item, nodeid in zip(session.items, nodeids):
        item.user_properties.append(("cbus_ci_nodeid", nodeid))


def _hookwrapper(function):
    return pytest.hookimpl(hookwrapper=True)(function) if pytest is not None else function


@_hookwrapper
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "setup":
        item.config._cbus_ci_started.append(_nodeid(item))
    elif report.when == "call":
        item.config._cbus_ci_call_events.append({
            "id": _nodeid(item), "outcome": report.outcome,
        })


def pytest_sessionfinish(session, exitstatus) -> None:
    selected = session.config.getoption("--cbus-ci-trace")
    if not selected:
        return
    path = Path(selected)
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "format": TRACE_FORMAT,
        "collected": session.config._cbus_ci_collected,
        "deselected": session.config._cbus_ci_deselected,
        "started": session.config._cbus_ci_started,
        "call_events": session.config._cbus_ci_call_events,
        "session_exitstatus": int(exitstatus),
    }
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _junit(path: Path) -> tuple[dict[str, int], list[dict[str, str]]]:
    root = ET.parse(path).getroot()
    _require(root.tag in ("testsuite", "testsuites"), "Invalid pytest JUnit root")
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    _require(bool(suites), "Pytest JUnit contains no suites")
    counts = {}
    for name in ("tests", "failures", "errors", "skipped"):
        values = [int(suite.attrib[name]) for suite in suites]
        _require(all(value >= 0 for value in values), "Negative JUnit counter")
        counts[name] = sum(values)
    cases = []
    for case in root.iter("testcase"):
        outcomes = [name for name in ("failure", "error", "skipped")
                    if case.find(name) is not None]
        _require(len(outcomes) <= 1, "JUnit case has conflicting outcomes")
        properties = case.find("properties")
        nodeids = ([] if properties is None else
                   [item.attrib.get("value") for item in properties.findall("property")
                    if item.attrib.get("name") == "cbus_ci_nodeid"])
        _require(len(nodeids) == 1 and isinstance(nodeids[0], str) and nodeids[0],
                 "JUnit case lacks one CI trace node ID")
        cases.append({"id": nodeids[0], "outcome": outcomes[0] if outcomes else "passed"})
    _require(bool(cases) and len(cases) == len({case["id"] for case in cases}),
             "JUnit contains no unique test cases")
    _require(counts["tests"] >= len(cases), "JUnit counter omits test cases")
    case_counts = Counter(case["outcome"] for case in cases)
    case_outcomes = {"failures": "failure", "errors": "error", "skipped": "skipped"}
    subtests = {name: counts[name] - case_counts[outcome]
                for name, outcome in case_outcomes.items()}
    _require(all(value >= 0 for value in subtests.values()),
             "JUnit outcome counter omits test cases")
    subtests["reported"] = counts["tests"] - len(cases)
    _require(sum(subtests[name] for name in ("failures", "errors", "skipped"))
             <= subtests["reported"], "JUnit subtest counters are inconsistent")
    subtests["passed"] = subtests["reported"] - sum(
        subtests[name] for name in ("failures", "errors", "skipped"))
    counts["passed"] = counts["tests"] - sum(
        counts[name] for name in ("failures", "errors", "skipped"))
    _require(counts["passed"] >= 0, "JUnit outcome counters exceed tests")
    return {"counts": counts, "unitemized_subtests": subtests}, cases


def audit(junit_path: Path, trace_path: Path, required_modules: list[str]) -> dict:
    junit, cases = _junit(junit_path)
    trace = json.loads(trace_path.read_text())
    _require(isinstance(trace, dict) and trace.get("format") == TRACE_FORMAT,
             "Invalid CI pytest trace")
    for name in ("collected", "deselected", "started"):
        value = trace.get(name)
        _require(isinstance(value, list) and all(isinstance(item, str) and item
                 for item in value), f"Invalid CI pytest {name} list")
    _require(not trace["deselected"], "CI selection deselected tests")
    _require(bool(trace["collected"])
             and len(trace["collected"]) == len(set(trace["collected"])),
             "CI collected no unique tests")
    _require(Counter(trace["started"]) == Counter(trace["collected"]),
             "A collected CI test did not start exactly once")
    _require(Counter(case["id"] for case in cases) == Counter(trace["started"]),
             "JUnit cases do not match started CI tests")
    calls = trace.get("call_events")
    _require(isinstance(calls, list) and all(
        isinstance(event, dict) and isinstance(event.get("id"), str)
        and event.get("id") in trace["started"]
        and event.get("outcome") in ("passed", "failed", "skipped")
        for event in calls), "Invalid CI test call events")
    _require(len(calls) + len(set(trace["started"]) - {event["id"] for event in calls})
             == junit["counts"]["tests"],
             "JUnit test counter does not match call and setup-only events")
    for case in cases:
        if case["outcome"] == "passed":
            _require(any(event["id"] == case["id"] and event["outcome"] == "passed"
                         for event in calls),
                     "JUnit passed case has no passing call event")
    _require(type(trace.get("session_exitstatus")) is int,
             "Invalid pytest exit status in CI trace")
    missing_modules = []
    for module in required_modules:
        _require(module.startswith("tests/test_") and module.endswith(".py")
                 and ".." not in Path(module).parts,
                 "Invalid required CI module")
        if not any(case["id"].startswith(module + "::")
                   and any(event["id"] == case["id"] and event["outcome"] == "passed"
                           for event in calls)
                   and case["outcome"] == "passed" for case in cases):
            missing_modules.append(module)
    counts = junit["counts"]
    if trace["session_exitstatus"] == 0 and counts["failures"] == counts["errors"] == 0:
        _require(not any(event["outcome"] == "failed" for event in calls),
                 "Successful JUnit result contains a failed call event")
        called_ids = {event["id"] for event in calls}
        setup_skips = sum(case["outcome"] == "skipped" and case["id"] not in called_ids
                          for case in cases)
        _require(counts["skipped"] == setup_skips + sum(
            event["outcome"] == "skipped" for event in calls),
            "JUnit skipped counter does not match call and setup skips")
    passed = (trace["session_exitstatus"] == 0
              and counts["failures"] == counts["errors"] == 0
              and counts["passed"] > 0
              and not missing_modules)
    ordinals = Counter()
    call_events = []
    for event in calls:
        ordinals[event["id"]] += 1
        call_events.append({**event, "ordinal": ordinals[event["id"]]})
    return {
        "format": FORMAT, "passed": passed,
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                   cwd=TOOLKIT_ROOT, text=True).strip(),
        "junit_sha256": _digest(junit_path), "trace_sha256": _digest(trace_path),
        "counts": counts, "unitemized_subtests": junit["unitemized_subtests"],
        "collected": trace["collected"], "started": trace["started"],
        "call_events": call_events, "cases": cases,
        "required_modules": required_modules,
        "missing_required_modules": missing_modules,
        "pytest_exit": trace["session_exitstatus"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--require-module", action="append", default=[])
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    try:
        receipt = audit(args.junit, args.trace, args.require_module)
    except AuditError as error:
        receipt = {"format": FORMAT, "passed": False, "error": str(error)}
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError,
            subprocess.CalledProcessError) as error:
        receipt = {"format": FORMAT, "passed": False,
                   "error": f"Cannot audit CI test result: {type(error).__name__}"}
    receipt["selection"] = args.selection
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    counts = receipt.get("counts", {})
    print(json.dumps({"selection": args.selection, "passed": receipt["passed"],
                      "counts": counts, "error": receipt.get("error"),
                      "missing_required_modules": receipt.get("missing_required_modules", [])},
                     sort_keys=True))
    if args.summary:
        with args.summary.open("a") as summary:
            cell = lambda key: str(counts[key]) if key in counts else "n/a"
            subtests = receipt.get("unitemized_subtests", {})
            summary.write("| Selection | Audit | Passed | Skipped | Failed/errors | "
                          "Subtest events without individual JUnit cases |\n")
            summary.write("| --- | --- | ---: | ---: | ---: | ---: |\n")
            failures = (str(counts["failures"] + counts["errors"])
                        if "failures" in counts and "errors" in counts else "n/a")
            summary.write(f"| {args.selection} | {'pass' if receipt['passed'] else 'fail'} | "
                          f"{cell('passed')} | {cell('skipped')} | {failures} | "
                          f"{subtests.get('reported', 'n/a')} |\n")
    return int(not receipt["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
