"""Literal matrix-selection and retained-evidence tests; no Rust or product services."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from test_installed_rust_interop import pytest_evidence


MAKE = """check-cgate-interop: compile
\tpython -m pytest 'tests/test_matrix_fixture.py::test_mock' tests/test_rust_cgate_interop.py -q

check-cmqtt-interop: compile
\tpython -m pytest 'tests/test_matrix_fixture.py::test_daemon' tests/test_cmqtt_programming_methods_interop.py -q

"""
COUNTS = {"mock": 552, "daemon": 569}
DIGESTS = {
    "mock": "9d7f4c2e130560e0348fe511ca4eb4a45ae306519c00421e73fe3091616f61bc",
    "daemon": "e2d64334548ea89324bc607058216a2a3623c3160eaa8bbd449d03fe66277c0b",
}


@pytest.fixture(scope="module")
def gate():
    default = Path(__file__).resolve().parents[1] / "research/installed_rust_interop.py"
    path = Path(os.environ.get("CBUS_INSTALLED_INTEROP_HELPER", str(default)))
    spec = importlib.util.spec_from_file_location("matrix_gate_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plans(gate):
    return gate.declared_selections(MAKE)


def epoch(gate, backend, configured, *, skipped=None):
    plan = configured[backend]
    core = plan["whole_modules"][0] + "::test_literal_core"
    ids = sorted([*plan["required_ids"], core])
    optional = [skipped] if skipped else []
    selection = {
        "required_ids": ids, "required_passed": len(ids),
        "parent_counts": {"passed": len(ids), **({"skipped": 1} if skipped else {})},
        "parent_total": len(ids) + len(optional),
        "unitemized_subtests": {"reported": 0, "passed": 0, "skipped": 0, "failures": 0, "errors": 0},
        "optional_skipped_ids": optional,
    }
    inputs = {"toolkit-cli/Makefile": {"sha256": "a" * 64, "bytes": 10}}
    package = {"file_count": 1, "files": {"__init__.py": {"sha256": "b" * 64, "bytes": 1}},
               "wheel": {"sha256": backend * 3}, "record": {"entries": 2}}
    origins = {"violations": 0, "python_processes": 1, "owned_rust_children": 0, "owned_rust_reaped": 0}
    phase = {"selection": copy.deepcopy(selection), "actual_parent_counts": selection["parent_counts"],
             "unitemized_subtests": selection["unitemized_subtests"],
             "collection": {"exit": 0, "timed_out": False}, "pytest": {"exit": 0, "timed_out": False},
             "collection_origins": copy.deepcopy(origins), "origins": copy.deepcopy(origins)}
    binaries = {"mock": {"sha256": backend + "-mock"}, "daemon": {"sha256": backend + "-daemon"}}
    summary = {"format": gate.FORMAT, "backend": backend, "passed": True,
               "scope": "full-maintained-backend-declaration", "configured_rosters": configured,
               "selected_rosters": {backend: plan}, "phases": {backend: phase},
               "source_quiet": True, "copied_reference_quiet": True, "binaries_quiet": True,
               "source_revision": "1" * 40, "input_count": len(inputs),
               "package_before": package, "package_after": copy.deepcopy(package),
               "binaries_before": binaries, "binaries_after": copy.deepcopy(binaries),
               "runner_inputs": {"guard": {"sha256": "c" * 64}},
               "optional_skip_admission": {"allowed": gate.OPTIONAL_SKIPS}}
    return {"summary": summary, "source_before": inputs, "source_after": copy.deepcopy(inputs),
            "selection": selection}


@pytest.mark.parametrize("backend", ["mock", "daemon"])
def test_complete_backend_selection_retains_every_ordered_field(gate, backend):
    configured = plans(gate)
    chosen, scope = gate.choose_selections(configured, backend=backend)
    assert scope == "full-maintained-backend-declaration"
    assert chosen == {backend: configured[backend]}
    assert configured.keys() == {"mock", "daemon"}
    assert chosen[backend]["whole_modules"] and chosen[backend]["quoted_ids"]


@pytest.mark.parametrize("backend", ["other", "", [], {}, True, 1])
def test_invalid_backend_never_falls_back_to_both(gate, backend):
    with pytest.raises(gate.GateError):
        gate.choose_selections(plans(gate), backend=backend)


@pytest.mark.parametrize("selects", [[], ["tests/test_matrix_fixture.py::test_mock"]])
def test_backend_cannot_be_combined_with_any_focused_selection(gate, selects):
    with pytest.raises(gate.GateError, match="mutually exclusive"):
        gate.choose_selections(plans(gate), selects, backend="mock")


def test_default_both_and_focused_modes_are_unchanged(gate):
    configured = plans(gate)
    assert gate.choose_selections(configured) == (configured, "full-maintained-declaration")
    chosen, scope = gate.choose_selections(configured, [configured["daemon"]["required_ids"][0]])
    assert scope == "focused-explicit-subset" and set(chosen) == {"daemon"}
    assert chosen["daemon"]["whole_modules"] == []


@pytest.mark.parametrize("extra", [
    ["--backend", "other"], ["--backend", "mock", "--select", "tests/test_matrix_fixture.py::test_mock"],
    ["--timeout", "0"], ["--timeout", "-1"], ["--timeout", "oops"],
])
def test_cli_selection_and_timeout_refuse_before_any_installer(gate, extra):
    with pytest.raises(SystemExit) as error:
        gate.argument_parser().parse_args(["--mock-bin", "missing", "--cmqttd-bin", "missing",
                                           "--output", "missing", *extra])
    assert error.value.code == 2


def test_current_backend_rosters_have_literal_full_digests_and_core_modules(gate):
    make = Path(os.environ.get("CBUS_INSTALLED_INTEROP_BASE_MAKE",
                               str(Path(__file__).resolve().parents[1] / "Makefile")))
    configured = gate.declared_selections(make.read_text())
    for backend in COUNTS:
        chosen, _ = gate.choose_selections(configured, backend=backend)
        ids = chosen[backend]["required_ids"]
        assert len(ids) == COUNTS[backend]
        assert hashlib.sha256(("\n".join(sorted(ids)) + "\n").encode()).hexdigest() == DIGESTS[backend]
        assert chosen[backend] == configured[backend]
    assert len(configured["mock"]["whole_modules"]) == 1
    assert len(configured["daemon"]["whole_modules"]) == 6
    assert sum(len(plan["required_ids"]) for plan in configured.values()) == 1121
    assert sum(len(plan["required_ids"]) - len(plan["quoted_ids"]) for plan in configured.values()) == 6


def test_two_terminal_epochs_combine_exact_ids_without_equal_binary_or_wheel_claim(gate):
    configured = plans(gate)
    evidence = [epoch(gate, backend, configured) for backend in ("mock", "daemon")]
    result = gate.audit_backend_matrix(evidence, configured, expected_revision="1" * 40,
                                       expected_inputs=evidence[0]["source_before"],
                                       expected_package=evidence[0]["summary"]["package_before"]["files"])
    assert result["passed"] is True and result["explicit_required_passed"] == 2
    assert result["scope"] == "two-complete-maintained-backend-epochs"
    assert result["phases"]["mock"]["binaries"] != result["phases"]["daemon"]["binaries"]
    assert len(result["phases"]) == 2


@pytest.mark.parametrize("fault", ["missing", "duplicate", "focused", "failed", "source", "revision",
    "package", "plan", "missing-id", "foreign-id", "phase", "pytest", "origins", "binary", "runner"])
def test_matrix_rejects_incomplete_stale_or_substituted_epoch(gate, fault):
    configured = plans(gate)
    evidence = [epoch(gate, backend, configured) for backend in ("mock", "daemon")]
    row, summary = evidence[1], evidence[1]["summary"]
    phase = summary["phases"]["daemon"]
    if fault == "missing": evidence.pop()
    elif fault == "duplicate": evidence[1] = copy.deepcopy(evidence[0])
    elif fault == "focused": summary["scope"] = "focused-explicit-subset"
    elif fault == "failed": summary["passed"] = False
    elif fault == "source": row["source_before"] = row["source_after"] = {"foreign": {}}
    elif fault == "revision": summary["source_revision"] = "2" * 40
    elif fault == "package": summary["package_before"] = summary["package_after"] = {"file_count": 1, "files": {"foreign.py": {}}}
    elif fault == "plan": summary["selected_rosters"] = {"daemon": {}}
    elif fault == "missing-id": row["selection"]["required_ids"].remove(configured["daemon"]["required_ids"][0])
    elif fault == "foreign-id": row["selection"]["required_ids"].append("tests/test_foreign.py::test_hidden")
    elif fault == "phase": summary["phases"] = {}
    elif fault == "pytest": phase["pytest"]["exit"] = 1
    elif fault == "origins": phase["origins"]["violations"] = 1
    elif fault == "binary": summary["binaries_after"] = {}
    elif fault == "runner": summary["runner_inputs"] = {}
    with pytest.raises(gate.GateError):
        gate.audit_backend_matrix(evidence, configured)


def artifact_epoch(gate, root, backend, *, optional=False, skip_reason=None, explicit_outcome="passed"):
    configured = plans(gate)
    skipped = next(nodeid for nodeid in gate.OPTIONAL_SKIPS
                   if nodeid.split("::", 1)[0] in configured[backend]["whole_modules"]) if optional else None
    value = epoch(gate, backend, configured, skipped=skipped)
    ids = [*value["selection"]["required_ids"], *([skipped] if skipped else [])]
    outcomes = {configured[backend]["required_ids"][0]: explicit_outcome}
    if skipped: outcomes[skipped] = "skipped"
    phase_root = root / backend
    raw = pytest_evidence(phase_root, ids=ids, outcomes=outcomes)
    if skipped:
        tree = ET.parse(raw["junit"])
        for case in tree.getroot().iter("testcase"):
            if case.find("skipped") is not None:
                case.find("skipped").set("message", skip_reason or gate.OPTIONAL_SKIPS[skipped]["reason"])
        tree.write(raw["junit"], encoding="utf-8", xml_declaration=True)
    collection = phase_root / "collection-trace.json"
    collection.write_text(json.dumps({"collected": ids, "deselected": []}) + "\n")
    audit = phase_root / "audit-receipt.json"
    audit.write_text("{}\n")  # Its bytes are bound; actual acceptance is re-derived from raw inputs.
    guard = phase_root / "origins/origins-1.jsonl"
    guard.parent.mkdir()
    guard.write_text('{"kind":"literal-artifact-fixture"}\n')
    phase = value["summary"]["phases"][backend]
    for filename, key in (("collection-trace.json", "collection_trace"), ("trace.json", "trace"),
                          ("junit.xml", "junit"), ("audit-receipt.json", "maintained_audit")):
        phase[key] = gate.pin(phase_root / filename)
    phase["guard_data_files"] = {"origins/origins-1.jsonl": gate.pin(guard)}
    for filename, payload in (("source-before.json", value["source_before"]),
                              ("source-after.json", value["source_after"]),
                              ("package-before.json", value["summary"]["package_before"]),
                              ("summary.json", value["summary"])):
        (root / filename).write_text(json.dumps(payload) + "\n")
    return root / "summary.json", configured


def auditor(gate):
    default = Path(__file__).resolve().parents[1] / "research/ci_test_results.py"
    return gate.load_auditor(Path(os.environ.get("CBUS_INSTALLED_INTEROP_MATRIX_AUDITOR", str(default))))


@pytest.mark.parametrize("backend", ["mock", "daemon"])
def test_retained_core_optional_skip_has_exact_census_reason(gate, tmp_path, backend):
    summary, configured = artifact_epoch(gate, tmp_path, backend, optional=True)
    value = gate.read_backend_evidence(summary, configured, auditor(gate))
    assert len(value["selection"]["optional_skipped_ids"]) == 1
    assert value["selection"]["required_passed"] == 2


@pytest.mark.parametrize("fault", ["wrong-reason", "required-skip", "required-fail", "artifact-tamper", "guard-missing"])
def test_raw_artifact_failures_cannot_be_hidden_by_passed_summary(gate, tmp_path, fault):
    summary, configured = artifact_epoch(gate, tmp_path, "mock", optional=fault == "wrong-reason",
        skip_reason="unregistered excuse" if fault == "wrong-reason" else None,
        explicit_outcome={"required-skip": "skipped", "required-fail": "failed"}.get(fault, "passed"))
    if fault == "artifact-tamper": (tmp_path / "mock/junit.xml").write_text("<changed/>\n")
    if fault == "guard-missing": (tmp_path / "mock/origins/origins-1.jsonl").unlink()
    with pytest.raises(gate.GateError):
        gate.read_backend_evidence(summary, configured, auditor(gate))


@pytest.mark.parametrize("job_result", ["failure", "cancelled", "skipped"])
def test_hosted_non_success_job_result_stays_failed_without_loading_artifacts(gate, tmp_path, job_result):
    output = tmp_path / "aggregate.json"
    assert gate.matrix_main(["--summary", str(tmp_path / "missing-mock"), "--summary",
                             str(tmp_path / "missing-daemon"), "--output", str(output),
                             "--job-result", job_result]) == 1
    value = json.loads(output.read_text())
    assert value["passed"] is False
    assert value["error"]["message"] == "Hosted backend matrix jobs did not all succeed"


def test_matrix_ci_keeps_full_backend_budget_and_independent_retention():
    root = Path(__file__).resolve().parents[2]
    workflow_path = Path(os.environ.get("CBUS_INSTALLED_INTEROP_MATRIX_CI", str(root / ".github/workflows/ci.yml")))
    make_path = Path(os.environ.get("CBUS_INSTALLED_INTEROP_BASE_MAKE", str(root / "toolkit-cli/Makefile")))
    workflow, make = workflow_path.read_text(), make_path.read_text()
    child = workflow.split("  toolkit-wheel-rust-interop:\n", 1)[1].split("  toolkit-wheel-rust-interop-matrix:\n", 1)[0]
    aggregate = workflow.split("  toolkit-wheel-rust-interop-matrix:\n", 1)[1].split("  toolkit-native-release:\n", 1)[0]
    assert "fail-fast: false" in child and "backend: [mock, daemon]" in child
    assert "timeout-minutes: 300" in child and "WHEEL_INTEROP_TIMEOUT=14400" in child
    assert "WHEEL_INTEROP_BACKEND=${{ matrix.backend }}" in child and "--select" not in child
    assert child.count("${{ matrix.backend }}") >= 4 and "include-hidden-files: true" in child
    assert "if: ${{ always() }}" in child and "needs: [toolkit-wheel-rust-interop]" in aggregate
    assert '--job-result "${{ needs.toolkit-wheel-rust-interop.result }}"' in aggregate
    assert "actions/download-artifact@v4" in aggregate and "include-hidden-files: true" in aggregate
    assert "WHEEL_INTEROP_TIMEOUT ?= 7200" in make and "WHEEL_INTEROP_BACKEND ?=" in make
    target = make.split("check-wheel-interop:\n", 1)[1].split("\n\n", 1)[0]
    assert "--timeout" in target and "--backend" in target and "--select" not in target
