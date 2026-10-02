from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from cbus_toolkit.toolkit_obligation_reconcile import (
    ReconciliationError, VerifiedGate, collect_source_records, parse_json,
    reconcile, verify_gate_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
VECTOR = ROOT / "research/fixtures/toolkit-obligation-reconcile-vectors.json"


def raw(document: dict) -> bytes:
    # Independent fixture encoding; no producer is used to author expectations.
    return json.dumps(document, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode()


def pin(content: bytes) -> dict:
    return {"sha256": sha256(content).hexdigest(), "bytes": len(content)}


def fixture() -> tuple[dict, dict[str, bytes], dict]:
    content = VECTOR.read_bytes()
    assert sha256(content).hexdigest() == "ade03d94896a8c198a1515476d76005e9d7d9fd355af59d9947520bc51b8778c"
    vector = json.loads(content)
    return deepcopy(vector["bundle"]), {n: raw(d) for n, d in vector["artifact_documents"].items()}, vector


def repin_receipt(bundle: dict, payloads: dict[str, bytes]) -> None:
    record = bundle["receipts"][0]
    name = record["artifact"]["id"]
    content = raw({k: v for k, v in record.items() if k != "artifact"})
    record["artifact"] = {"id": name, **pin(content)}
    bundle["current_artifacts"][name] = pin(content)
    payloads[name] = content


def codes(report: dict) -> set[str]:
    return {row["code"] for row in report["unresolved"]}


def test_literal_full_join_is_complete_only_for_declared_synthetic_surface() -> None:
    bundle, payloads, vector = fixture()
    report = reconcile(bundle, artifact_bytes=payloads)
    assert report["counts"] == vector["expected_counts"]
    assert report["scope"] == "declared-modeled-input-surface-only"
    assert report["complete_for_declared_surface"] is True
    assert report["denominator_ready"] is True
    assert report["full_toolkit_parity"] is False
    assert report["census_completeness_verified"] is False
    assert report["unresolved"] == []
    assert len(report["variant_gates"]) == 6
    assert all(len(gate["required_source_ids"]) == 21 and gate["satisfied"] for gate in report["variant_gates"])


def test_collector_exact_rows_match_independent_literal_id_and_hash_recipe() -> None:
    _, _, vector = fixture()
    documents = vector["artifact_documents"]
    collected = collect_source_records(documents["toolkit-executable-surface"], documents["toolkit-help-surface"],
                                       [("synthetic-managed-annex", documents["synthetic-managed-annex"])])
    expected = deepcopy(vector["bundle"]["sources"])
    for row in expected:
        row["profile_variants"] = []
        if row["kind"] == "executable_event":
            row["handler_id"] = None  # MAP naming alone cannot resolve a handler body.
    assert collected == expected
    assert len([row for row in collected if row["kind"] == "executable_event"]) == 2
    assert [row["source_id"] for row in collected if row["kind"] == "executable_property"] == [
        "TSYNTHETICFORM/SyntheticForm/Indicator#OnColor",
    ]


def test_collector_actual_sanitized_source_surface_is_not_a_function_denominator() -> None:
    paths = {
        "toolkit-executable-surface": ROOT / "docs/toolkit-executable-surface.json",
        "toolkit-help-surface": ROOT / "docs/toolkit-surface.json",
        "inventory-annex": ROOT / "research/fixtures/edlt-scene-inventory-source-annex.json",
    }
    expected = {
        "toolkit-executable-surface": (2098634, "c7205a186952f2c2543d9e545d1055a606889614b382294fa7e2cb2340ed2767"),
        "toolkit-help-surface": (5926486, "2cd1dd61f80a34ff14aebcfb44e131aa0ab738856a5073342bc3aac5a3494401"),
        "inventory-annex": (421922, "6e404c513e218df6df74ad964d8881b6542fee6ac42393f6c731374ea023df57"),
    }
    payloads = {name: path.read_bytes() for name, path in paths.items()}
    for name, content in payloads.items():
        assert (len(content), sha256(content).hexdigest()) == expected[name]
    docs = {name: json.loads(content) for name, content in payloads.items()}
    sources = collect_source_records(docs["toolkit-executable-surface"], docs["toolkit-help-surface"],
                                    [("inventory-annex", docs["inventory-annex"])],
                                    artifact_pins={name: pin(content) for name, content in payloads.items()})
    assert len(sources) == 21765  # 12353 EXE +9308 help +104 retained method/declaration spans.
    assert all(row["profile_variants"] == [] for row in sources)
    assert sum(row["kind"] == "executable_event" for row in sources) == 1839
    assert sum(row["kind"] == "native_method" for row in sources) == 15
    assert sum(row["kind"] == "managed_method" for row in sources) == 48
    # Only names/digests enter normalized rows; IL, source instructions and host paths do not.
    serialized = json.dumps(sources)
    assert all(token not in serialized for token in ("file_offset", "direct_calls", "il_offset", "raw_hex", "/Users/", "/Volumes/"))


@pytest.mark.parametrize("change,reason", [
    ("remove-binding", "source_variants_unmapped"),
    ("missing-source-profile", "source_profile_roster_missing"),
    ("provisional-obligation", "obligation_definition_unresolved"),
    ("missing-obligation-profile", "obligation_definition_unresolved"),
    ("missing-obligation-variant", "binding_obligation_variant_unknown"),
    ("unknown-bound-source", "binding_source_unknown"),
    ("stale-binding-source", "binding_source_stale"),
    ("unknown-handler", "event_handler_unresolved"),
    ("wrong-handler", "event_handler_identity_mismatch"),
    ("stale-source-parent", "source_artifact_stale"),
    ("changed-anchor", "source_record_hash_mismatch"),
    ("invented-anchor", "source_not_in_current_inventory"),
])
def test_mapping_faults_block_denominator_and_bounded_completeness(change: str, reason: str) -> None:
    bundle, payloads, _ = fixture()
    if change == "remove-binding":
        bundle["bindings"].pop()
    elif change == "missing-source-profile":
        bundle["sources"][0]["profile_variants"] = []
    elif change == "provisional-obligation":
        bundle["obligations"][0]["definition_status"] = "provisional"
    elif change == "missing-obligation-profile":
        bundle["obligations"][0]["profiles"] = []
    elif change == "missing-obligation-variant":
        bundle["obligations"][0]["profiles"][0]["variants"] = ["empty"]
    elif change == "unknown-bound-source":
        bundle["bindings"][0]["source_id"] = "scope:unknown"
    elif change == "stale-binding-source":
        bundle["bindings"][0]["source_sha256"] = "f" * 64
    elif change in {"unknown-handler", "wrong-handler"}:
        event = next(s for s in bundle["sources"] if s["kind"] == "executable_event" and "OnClick" in s["source_id"])
        event["handler_id"] = None if change == "unknown-handler" else next(
            s["id"] for s in bundle["sources"] if s["kind"] == "native_method" and "FormShow" in s["source_id"])
    elif change == "stale-source-parent":
        bundle["current_artifacts"]["toolkit-help-surface"]["sha256"] = "f" * 64
    elif change == "changed-anchor":
        bundle["sources"][0]["anchor"]["name"] = "invented"
    elif change == "invented-anchor":
        source = bundle["sources"][0]
        source["anchor"]["name"] = "invented"
        source["source_sha256"] = sha256(raw({k: source[k] for k in ("kind", "source_id", "anchor", "artifacts")})).hexdigest()
    report = reconcile(bundle, artifact_bytes=payloads)
    assert not report["denominator_ready"]
    assert not report["complete_for_declared_surface"]
    assert reason in codes(report)


@pytest.mark.parametrize("kind", ["generic_forwarding", "test_filename", "unresolved"])
def test_generic_implementation_and_test_filename_do_not_prove_workflow(kind: str) -> None:
    bundle, payloads, _ = fixture()
    bundle["obligations"][0]["implementation_basis"] = kind
    report = reconcile(bundle, artifact_bytes=payloads)
    assert report["denominator_ready"]  # The explicit scope mapping itself is still defined.
    assert not report["complete_for_declared_surface"]
    assert "workflow_implementation_basis_unproved" in codes(report)


@pytest.mark.parametrize("kind", ["declarative", "generic_forwarding", "test_inventory", "static"])
def test_nonexecuting_or_static_receipt_does_not_satisfy_modeled_workflow(kind: str) -> None:
    bundle, payloads, _ = fixture()
    bundle["receipts"][0]["execution_kind"] = kind
    repin_receipt(bundle, payloads)
    report = reconcile(bundle, artifact_bytes=payloads)
    assert report["denominator_ready"] and not report["complete_for_declared_surface"]
    assert report["counts"]["satisfied_variant_gates"] == 0


@pytest.mark.parametrize("change,reason", [
    ("stale-artifact", "receipt_artifact_stale_or_unverified"),
    ("stale-source", "receipt_source_stale_or_unresolved"),
    ("changed-document", "receipt_document_mismatch"),
    ("unknown-variant", "observation_obligation_variant_unknown"),
    ("failed", "required_variant_dimension_unsatisfied"),
    ("skipped", "required_variant_dimension_unsatisfied"),
    ("missing-case", "receipt_has_no_workflow_execution"),
    ("missing-source-observation", "required_variant_dimension_unsatisfied"),
    ("missing-dimension", "required_variant_dimension_unsatisfied"),
])
def test_receipt_faults_leave_required_gate_unsatisfied(change: str, reason: str) -> None:
    bundle, payloads, _ = fixture()
    receipt = bundle["receipts"][0]
    if change == "stale-artifact":
        bundle["current_artifacts"][receipt["artifact"]["id"]]["sha256"] = "f" * 64
    elif change == "stale-source":
        receipt["source_pins"][next(iter(receipt["source_pins"]))] = "f" * 64
    elif change == "changed-document":
        receipt["case_ids"].append("case:not-in-document")
    elif change == "unknown-variant":
        receipt["observations"][0]["variant"] = "unknown"
    elif change in {"failed", "skipped"}:
        receipt["result"] = change
        for observation in receipt["observations"]:
            observation["result"] = change
    elif change == "missing-case":
        receipt["case_ids"] = []; receipt["observations"] = []
    elif change == "missing-source-observation":
        receipt["observations"][0]["source_ids"].pop()
    elif change == "missing-dimension":
        receipt["observations"].pop()
    if change not in {"stale-artifact", "changed-document"}:
        repin_receipt(bundle, payloads)
    report = reconcile(bundle, artifact_bytes=payloads)
    assert report["denominator_ready"] and not report["complete_for_declared_surface"]
    assert reason in codes(report)


@pytest.mark.parametrize("dimension,kind", [("physical", "modeled"), ("original_differential", "modeled"),
                                           ("physical", "hardware"), ("original_differential", "original")])
def test_required_original_or_hardware_cannot_be_granted_by_json_status(dimension: str, kind: str) -> None:
    bundle, payloads, _ = fixture()
    bundle["obligations"][0]["profiles"][0]["required_dimensions"].append(dimension)
    receipt = bundle["receipts"][0]
    receipt["execution_kind"] = kind
    for variant in ["empty", "populated"]:
        receipt["observations"].append({**deepcopy(receipt["observations"][0]),
            "variant": variant, "dimension": dimension, "case_id": "case:" + variant})
    if kind in {"hardware", "original"}:
        receipt["gate_id"] = "claimed-gate"
    repin_receipt(bundle, payloads)
    report = reconcile(bundle, artifact_bytes=payloads)
    assert not report["complete_for_declared_surface"]
    assert report["full_toolkit_parity"] is False and report["census_completeness_verified"] is False
    assert ("required_gate_provenance_unverified" if kind in {"hardware", "original"}
            else "observation_execution_kind_ineligible") in codes(report)


@pytest.mark.parametrize("target", ["sources", "obligations", "bindings", "receipts"])
def test_duplicate_ids_refuse_instead_of_silently_deduplicating(target: str) -> None:
    bundle, payloads, _ = fixture()
    bundle[target].append(deepcopy(bundle[target][0]))
    with pytest.raises(ReconciliationError, match="duplicate"):
        reconcile(bundle, artifact_bytes=payloads)


def test_duplicate_binding_with_new_id_and_conflicting_disposition_refuse() -> None:
    bundle, payloads, _ = fixture()
    extra = {**bundle["bindings"][0], "id": "binding:duplicate"}
    bundle["bindings"].append(extra)
    with pytest.raises(ReconciliationError, match="duplicate source/obligation"):
        reconcile(bundle, artifact_bytes=payloads)
    extra["disposition"] = "nonfunctional"; extra["obligation_id"] = None
    with pytest.raises(ReconciliationError, match="conflicting"):
        reconcile(bundle, artifact_bytes=payloads)


def test_scalar_exception_does_not_erase_onclick_or_unknown_oncolor_handler() -> None:
    _, _, vector = fixture()
    doc = deepcopy(vector["artifact_documents"]["toolkit-executable-surface"])
    indicator = doc["resources"][0]["components"][2]
    indicator["class"] = "TUnknownLEDSubclass"
    doc["resources"][0]["event_bindings"][1]["handler"] = "clRed"
    rows = collect_source_records(doc, None)
    assert sum(row["kind"] == "executable_event" for row in rows) == 3
    assert not any(row["kind"] == "executable_property" for row in rows)
    assert any(row["source_id"].endswith("#OnClick=clRed") for row in rows)
    assert any(row["source_id"].endswith("#OnColor=clRed") for row in rows)


def test_new_current_control_blocks_completion_even_when_all_old_workflow_gates_pass() -> None:
    bundle, payloads, _ = fixture()
    doc = json.loads(payloads["toolkit-executable-surface"])
    doc["resources"][0]["components"].append({"path": "SyntheticForm/NewButton", "class": "TButton", "name": "NewButton"})
    doc["counts"]["components"] = 4
    payloads["toolkit-executable-surface"] = raw(doc)
    bundle["current_artifacts"]["toolkit-executable-surface"] = pin(raw(doc))
    # Independently rebind all existing exact source/receipt pins to the current
    # inventory, leaving only the genuine newly discovered control unmapped.
    for source in bundle["sources"]:
        if source["artifacts"][0]["id"] == "toolkit-executable-surface":
            source["artifacts"][0] = {"id": "toolkit-executable-surface", **pin(raw(doc))}
            source["source_sha256"] = sha256(raw({k: source[k] for k in ("kind", "source_id", "anchor", "artifacts")})).hexdigest()
    by_id = {s["id"]: s for s in bundle["sources"]}
    for binding in bundle["bindings"]:
        binding["source_sha256"] = by_id[binding["source_id"]]["source_sha256"]
    bundle["receipts"][0]["source_pins"] = {s["id"]: s["source_sha256"] for s in bundle["sources"]}
    source_id = "TSYNTHETICFORM/SyntheticForm/NewButton"
    added = {"id": "scope:executable-control:" + sha256(source_id.encode()).hexdigest()[:20],
             "kind": "executable_control", "source_id": source_id,
             "anchor": {"class": "TButton", "name": "NewButton", "resource_sha256": "1" * 64},
             "artifacts": [{"id": "toolkit-executable-surface", **pin(raw(doc))}],
             "profile_variants": [{"profile": "synthetic-profile", "variant": "empty"},
                                  {"profile": "synthetic-profile", "variant": "populated"}],
             "handler_id": None}
    added["source_sha256"] = sha256(raw({k: added[k] for k in ("kind", "source_id", "anchor", "artifacts")})).hexdigest()
    bundle["sources"].append(added)
    repin_receipt(bundle, payloads)
    report = reconcile(bundle, artifact_bytes=payloads)
    assert report["counts"]["satisfied_variant_gates"] == 6
    assert report["counts"]["source_records"] == 22 and report["counts"]["mapping_resolved_sources"] == 21
    assert not report["denominator_ready"] and not report["complete_for_declared_surface"]
    assert {"code": "source_variants_unmapped", "source_id": added["id"]} in report["unresolved"]
    # Omitting the new source row entirely cannot hide the same actual control
    # behind a supplied source_inventory_complete flag.
    bundle["sources"].pop()
    report = reconcile(bundle, artifact_bytes=payloads)
    assert report["counts"]["source_records"] == 21
    assert report["counts"]["discovered_source_records"] == 22
    assert report["counts"]["omitted_source_records"] == 1
    assert not report["denominator_ready"] and not report["complete_for_declared_surface"]
    entry = next(r for r in report["inventory_membership"] if r["artifact_id"] == "toolkit-executable-surface")
    assert entry["omitted_sources"] == [{key: added[key] for key in ("id", "source_id", "kind", "source_sha256")}]


def test_nonfunctional_control_disposition_requires_exact_current_static_receipt() -> None:
    bundle, payloads, _ = fixture()
    source = next(s for s in bundle["sources"] if s["kind"] == "executable_property")
    bindings = [b for b in bundle["bindings"] if b["source_id"] == source["id"]]
    for binding in bindings:
        binding["disposition"] = "nonfunctional"; binding["obligation_id"] = None
    report = reconcile(bundle, artifact_bytes=payloads)
    assert not report["denominator_ready"] and not report["complete_for_declared_surface"]
    assert "nonfunctional_disposition_unproved" in codes(report)
    # Independent source-pinned scope analysis proves that OnColor is a scalar,
    # rather than allowing a filename or generic broad ledger to remove it.
    record = {"format": "cbus-toolkit-obligation-reconciliation-evidence-v1",
              "id": "evidence:scalar-disposition", "execution_kind": "static", "result": "passed",
              "case_ids": ["analysis:scalar-oncolor"], "source_pins": {source["id"]: source["source_sha256"]},
              "gate_id": None, "observations": [{"obligation_id": None, "profile": "synthetic-profile",
                  "variant": v, "dimension": "scope_disposition", "result": "passed",
                  "case_id": "analysis:scalar-oncolor", "source_ids": [source["id"]]}
                  for v in ["empty", "populated"]]}
    name = "synthetic-scalar-disposition.json"; payloads[name] = raw(record)
    bundle["current_artifacts"][name] = pin(raw(record))
    bundle["receipts"].append({**record, "artifact": {"id": name, **pin(raw(record))}})
    accepted = reconcile(bundle, artifact_bytes=payloads)
    assert accepted["denominator_ready"] and accepted["complete_for_declared_surface"]
    payloads[name] = b'{"result":"passed"}'
    assert not reconcile(bundle, artifact_bytes=payloads)["complete_for_declared_surface"]


def test_unresolved_extra_receipt_does_not_hide_behind_other_passing_evidence() -> None:
    bundle, payloads, _ = fixture()
    extra = deepcopy(bundle["receipts"][0]); extra["id"] = "evidence:stale-extra"
    extra["artifact"]["id"] = "missing-extra.json"
    bundle["receipts"].append(extra)
    report = reconcile(bundle, artifact_bytes=payloads)
    assert report["counts"]["satisfied_variant_gates"] == 6
    assert not report["complete_for_declared_surface"]
    assert "receipt_artifact_stale_or_unverified" in codes(report)


def test_unverified_artifact_pins_and_incomplete_inventory_cannot_close_scope() -> None:
    bundle, payloads, _ = fixture()
    report = reconcile(bundle)
    assert not report["denominator_ready"] and not report["complete_for_declared_surface"]
    assert "source_artifact_unverified" in codes(report)
    bundle["source_inventory_complete"] = False
    report = reconcile(bundle, artifact_bytes=payloads)
    assert not report["denominator_ready"] and "declared_source_inventory_incomplete" in codes(report)


def test_duplicate_json_keys_and_private_coordinates_or_instruction_payload_refuse() -> None:
    with pytest.raises(ReconciliationError, match="duplicate JSON"):
        parse_json('{"sources":[],"sources":[]}')
    with pytest.raises(ReconciliationError, match="nonfinite"):
        parse_json('{"value":NaN}')
    for value in ["/Users/example/private.xml", "C:\\private\\project.xml"]:
        bundle, payloads, _ = fixture()
        bundle["sources"][0]["source_id"] = value
        with pytest.raises(ReconciliationError, match="private coordinate"):
            reconcile(bundle, artifact_bytes=payloads)
    bundle, payloads, _ = fixture()
    bundle["sources"][0]["anchor"]["raw_hex"] = "414243"
    with pytest.raises(ReconciliationError, match="invalid source anchor"):
        reconcile(bundle, artifact_bytes=payloads)


@pytest.mark.parametrize("fault", ["source-null", "profile-object", "hash-type", "handler-object", "observation-null"])
def test_malformed_declaration_structures_refuse_with_controlled_errors(fault: str) -> None:
    bundle, payloads, _ = fixture()
    if fault == "source-null":
        bundle["sources"][0] = None
    elif fault == "profile-object":
        bundle["obligations"][0]["profiles"][0]["variants"] = [{}]
    elif fault == "hash-type":
        bundle["sources"][0]["source_sha256"] = {}
    elif fault == "handler-object":
        bundle["sources"][0]["handler_id"] = {}
    else:
        bundle["receipts"][0]["observations"][0] = None
        repin_receipt(bundle, payloads)
    with pytest.raises(ReconciliationError):
        reconcile(bundle, artifact_bytes=payloads)


def retained_gate_fixture(kind: str = "native") -> dict:
    """Invented retained files verify the parser, never an actual provisioned run."""
    cases = ["tests/test_synthetic.py::test_empty", "tests/test_synthetic.py::test_populated"]
    provision = [{"name": "CBUS_ORIGINAL_FIXTURE", "kind": "file", "present": True,
                  "sha256": "b" * 64, "bytes": 1, "pinned": True}]
    rules = {"CBUS_ORIGINAL_FIXTURE": {"kind": "file", "sha256": "b" * 64}}
    if kind == "hardware":
        provision.append({"name": "CBUS_HARDWARE_ACCEPTANCE", "kind": "flag", "present": True})
        rules["CBUS_HARDWARE_ACCEPTANCE"] = {"kind": "flag"}
    manifest = {"format": "cbus-provisioned-release-gate-v1", "gate": kind,
                "systems": ["Synthetic"], "tests": cases, "required_environment": rules}
    trace = {"format": "cbus-release-gate-pytest-trace-v1", "collected": cases,
             "executed": cases, "deselected": [], "session_exitstatus": 0,
             "subtests": {"passed": 0, "failed": 0, "skipped": 0}}
    suite = ET.Element("testsuite", tests="2", failures="0", errors="0", skipped="0")
    for name in cases:
        case = ET.SubElement(suite, "testcase", name=name)
        props = ET.SubElement(case, "properties")
        ET.SubElement(props, "property", name="cbus_release_gate_nodeid", value=name)
    junit = ET.tostring(suite)
    files = {"src/synthetic.py": b"synthetic current source"}
    rows = [(n, len(b), sha256(b).hexdigest()) for n, b in sorted(files.items())]
    snapshot = {"sha256": sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest(),
                "files": len(files), "bytes": sum(len(b) for b in files.values())}
    receipt = {"format": "cbus-provisioned-release-gate-v1", "gate": kind, "passed": True,
        "pytest_exit": 0, "manifest_sha256": sha256(raw(manifest)).hexdigest(),
        "trace_sha256": sha256(raw(trace)).hexdigest(), "junit_sha256": sha256(junit).hexdigest(),
        "selection_sha256": sha256(json.dumps(cases, separators=(",", ":")).encode()).hexdigest(),
        "selected_test_count": 2, "verified_provision": provision, "source_inputs": snapshot,
        "result": {"tests": 2, "passed": 2, "failures": 0, "errors": 0, "skipped": 0},
        "execution": {"collected": 2, "executed": 2, "deselected": 0}}
    payloads = {"gate-receipt.json": raw(receipt), "gate-manifest.json": raw(manifest),
                "gate-trace.json": raw(trace), "gate-junit.xml": junit}
    return {"gate_id": "synthetic-retained-gate", "receipt_raw": raw(receipt), "manifest_raw": raw(manifest),
            "trace_raw": raw(trace), "junit_raw": junit,
            "artifact_ids": dict(zip(["receipt", "manifest", "trace", "junit"], payloads)),
            "current_artifacts": {n: pin(b) for n, b in payloads.items()},
            "current_source_files": files, "current_provision": provision}


@pytest.mark.parametrize("kind,dimension", [("native", "original_differential"), ("hardware", "physical")])
def test_retained_gate_token_requires_exact_artifacts_and_stays_bounded(kind: str, dimension: str) -> None:
    data = retained_gate_fixture(kind)
    gate = verify_gate_receipt(**data)
    assert gate.kind == kind and len(gate.case_ids) == 2
    bundle, payloads, _ = fixture()
    bundle["obligations"][0]["profiles"][0]["required_dimensions"].append(dimension)
    receipt = bundle["receipts"][0]
    receipt["execution_kind"] = "original" if kind == "native" else "hardware"
    receipt["gate_id"] = gate.gate_id
    receipt["case_ids"] = list(gate.case_ids)
    for obs in receipt["observations"]:
        obs["case_id"] = gate.case_ids[0 if obs["variant"] == "empty" else 1]
    for index, variant in enumerate(["empty", "populated"]):
        receipt["observations"].append({**deepcopy(receipt["observations"][0]),
            "dimension": dimension, "variant": variant, "case_id": gate.case_ids[index]})
    repin_receipt(bundle, payloads)
    bundle["current_artifacts"].update(data["current_artifacts"])
    for role, arg in [("receipt", "receipt_raw"), ("manifest", "manifest_raw"), ("trace", "trace_raw"), ("junit", "junit_raw")]:
        payloads[data["artifact_ids"][role]] = data[arg]
    report = reconcile(bundle, artifact_bytes=payloads, verified_gates=[gate])
    assert report["complete_for_declared_surface"] is True
    assert report["full_toolkit_parity"] is False and report["census_completeness_verified"] is False
    # A token verified against an old artifact cannot bless its successor.
    bundle["current_artifacts"]["gate-junit.xml"]["sha256"] = "f" * 64
    assert not reconcile(bundle, artifact_bytes=payloads, verified_gates=[gate])["complete_for_declared_surface"]


@pytest.mark.parametrize("fault", ["skip", "missing-execution", "duplicate-case", "wrong-junit-case",
                                   "stale-source", "stale-provision", "missing-provision", "wrong-artifact"])
def test_retained_gate_refuses_missing_or_skipped_proof(fault: str) -> None:
    data = retained_gate_fixture()
    if fault == "skip":
        root = ET.fromstring(data["junit_raw"]); root.set("skipped", "1")
        ET.SubElement(root.find("testcase"), "skipped")
        data["junit_raw"] = ET.tostring(root)
    elif fault in {"missing-execution", "duplicate-case"}:
        trace = json.loads(data["trace_raw"])
        trace["executed"] = trace["executed"][:-1] if fault == "missing-execution" else trace["executed"] * 2
        data["trace_raw"] = raw(trace)
    elif fault == "wrong-junit-case":
        root = ET.fromstring(data["junit_raw"])
        root.find("testcase/properties/property").set("value", "tests/test_other.py::test_other")
        data["junit_raw"] = ET.tostring(root)
    elif fault == "stale-source":
        data["current_source_files"]["src/synthetic.py"] += b" changed"
    elif fault == "stale-provision":
        data["current_provision"] = deepcopy(data["current_provision"])
        data["current_provision"][0]["sha256"] = "f" * 64
    elif fault == "missing-provision":
        data["current_provision"] = []
    elif fault == "wrong-artifact":
        data["current_artifacts"]["gate-receipt.json"]["sha256"] = "f" * 64
    if fault in {"skip", "wrong-junit-case", "missing-execution", "duplicate-case"}:
        # Keep byte bindings current so the semantic proof check is exercised.
        receipt = json.loads(data["receipt_raw"])
        receipt["junit_sha256"] = sha256(data["junit_raw"]).hexdigest()
        receipt["trace_sha256"] = sha256(data["trace_raw"]).hexdigest()
        data["receipt_raw"] = raw(receipt)
        for role, arg in [("receipt", "receipt_raw"), ("trace", "trace_raw"), ("junit", "junit_raw")]:
            data["current_artifacts"][data["artifact_ids"][role]] = pin(data[arg])
    with pytest.raises(ReconciliationError):
        verify_gate_receipt(**data)


def test_raw_or_forged_gate_tokens_are_not_owner_issued() -> None:
    bundle, payloads, _ = fixture()
    for gate in [{"gate_id": "fake", "kind": "native", "passed": True},
                 VerifiedGate("fake", "native", (), (), "f" * 64, object())]:
        with pytest.raises(ReconciliationError, match="issued"):
            reconcile(bundle, artifact_bytes=payloads, verified_gates=[gate])


@pytest.mark.parametrize("changed", [
    {"kind": "hardware"},
    {"case_ids": ("tests/test_forged.py::test_physical",)},
    {"artifact_pins": ()},
    {"source_snapshot_sha256": "f" * 64},
    {"gate_id": "another-gate"},
])
def test_issued_gate_content_changes_cannot_reuse_verification(changed: dict) -> None:
    # An issued native token must never promote itself to a hardware gate or
    # bless a different case/artifact/source roster through dataclasses.replace.
    gate = verify_gate_receipt(**retained_gate_fixture())
    bundle, payloads, _ = fixture()
    with pytest.raises(ReconciliationError, match="issued"):
        reconcile(bundle, artifact_bytes=payloads, verified_gates=[replace(gate, **changed)])
