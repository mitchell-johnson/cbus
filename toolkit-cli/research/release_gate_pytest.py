"""Private pytest instrumentation for a provisioned release-gate run.

The release-gate runner loads this plugin explicitly with third-party plugin
autoload disabled.  It records the exact collected, deselected, and started
node IDs and places each node ID into that test's JUnit properties.  The
runner validates both outputs; this module does not decide whether a gate
passed.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import pytest


FORMAT = "cbus-release-gate-pytest-trace-v1"
_SUBTESTS: Counter = Counter()


def _nodeid(item):
    """Use a stable checkout-relative ID even when pytest uses one-file root IDs."""
    relative = item.path.resolve().relative_to(item.config.rootpath.resolve()).as_posix()
    suffix = item.nodeid.split("::", 1)
    return relative + ("::" + suffix[1] if len(suffix) == 2 else "")


def pytest_addoption(parser):
    group = parser.getgroup("cbus release gate")
    group.addoption("--cbus-release-gate-trace", metavar="PATH")


def pytest_configure(config):
    config._cbus_release_gate_collected = []
    config._cbus_release_gate_deselected = []
    config._cbus_release_gate_executed = []
    _SUBTESTS.clear()


def pytest_deselected(items):
    if not items:
        return
    config = items[0].config
    config._cbus_release_gate_deselected.extend(_nodeid(item) for item in items)


def pytest_collection_finish(session):
    nodeids = [_nodeid(item) for item in session.items]
    session.config._cbus_release_gate_collected = nodeids
    for item, nodeid in zip(session.items, nodeids):
        item.user_properties.append(("cbus_release_gate_nodeid", nodeid))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "setup":
        item.config._cbus_release_gate_executed.append(_nodeid(item))


def pytest_runtest_logreport(report):
    # JUnit counts unittest subtests without emitting their cases; count
    # them independently so the runner can bind that difference.
    if report.when == "call" and type(report).__name__ == "SubtestReport":
        _SUBTESTS[report.outcome] += 1


def pytest_sessionfinish(session, exitstatus):
    selected = session.config.getoption("--cbus-release-gate-trace")
    if not selected:
        return
    path = Path(selected)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": FORMAT,
        "collected": session.config._cbus_release_gate_collected,
        "deselected": session.config._cbus_release_gate_deselected,
        "executed": session.config._cbus_release_gate_executed,
        "subtests": {outcome: _SUBTESTS[outcome]
                     for outcome in ("passed", "failed", "skipped")},
        "session_exitstatus": int(exitstatus),
    }
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)
