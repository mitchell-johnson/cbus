"""User JSON adapter contracts; all evaluation stays within memory."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cbus_toolkit.offline_workflows.cli_support import InputError
from cbus_toolkit.offline_workflows.transfer_restore_input import FORMAT, evaluate

SHA = "1" * 64
OTHER = "2" * 64


def transfer(row_id="u1", **changes):
    result = {"row_id": row_id, "source_identity": "source/" + row_id,
              "source_snapshot_sha256": SHA, "destination_identity": "destination/" + row_id,
              "staged_data_sha256": OTHER, "action": "programming-only"}
    result.update(changes)
    return result


def project(row_id="p1", **changes):
    result = {"row_id": row_id, "member_identity": "member/" + row_id,
              "source_project": "OLD", "source_snapshot_sha256": SHA,
              "proposed_name": "RENAMED"}
    result.update(changes)
    return result


def document(surface="advanced-transfer", **changes):
    bindings = {
        "advanced-transfer": {"rows": [transfer()]},
        "transfer-direction": {"context_sha256": SHA},
        "quick-transfer": {"row_ids": ["u1", "u2"], "attempt_id": "quick-attempt"},
        "restore-decision": {"projects": [project()], "archive_sha256": SHA,
                             "destination_snapshot_sha256": OTHER, "destination_names": ["OLD"]},
        "restore-results": {"projects": [project()], "attempt_id": "restore-attempt"},
        "label-transfer": {"labels": [{"text": "A", "slot": 1}, {"text": "B"}], "capacity": 4},
    }
    result = {"format": FORMAT, "surface": surface, "bindings": bindings[surface]}
    if surface == "transfer-direction":
        result["choices"] = {"choice": "rdbDatabase", "decision": "accept"}
    result.update(changes)
    return result


def authority_false(result):
    assert result["execution_admitted"] is False
    assert result["original_workflow_verified"] is False
    assert result["native_mutations"] == 0
    assert result["queue_commands"] == []
    assert result["automatic_replay_authorized"] is False
    if result["component_report"] is not None:
        for name in ("execution_admitted", "original_workflow_verified", "native_mutations", "queue_commands", "automatic_replay_authorized"):
            assert result["component_report"][name] == result[name]


@pytest.mark.parametrize("surface", ["advanced-transfer", "transfer-direction", "quick-transfer", "restore-decision", "restore-results", "label-transfer"])
def test_all_explicit_surfaces_inspect_without_history(surface):
    result = evaluate(document(surface), "inspect")
    assert result["surface"] == surface
    assert result["outcome"] == "inspected"
    assert result["validation_passed"] is True
    assert result["history_applied"] is False
    authority_false(result)


def test_inspect_does_not_apply_history_or_infer_cancel():
    value = document(history=[{"kind": "clear-actions", "row_ids": ["u1"]}, {"kind": "cancel"}])
    result = evaluate(value, "inspect")
    assert result["outcome"] == "inspected"
    assert result["component_report"]["history"] == []
    assert result["component_report"]["selected_actions"] == [{"row_id": "u1", "action": "programming-only"}]
    assert result["supplied_history_count"] == 2


@pytest.mark.parametrize("operation", ["validate", "plan"])
def test_accepted_advanced_unknown_contract_stays_unsupported(operation):
    result = evaluate(document(history=[{"kind": "accept"}]), operation)
    assert result["outcome"] == "unsupported"
    assert result["validation_passed"] is False
    assert result["component_report"]["intent_frozen"] is True
    authority_false(result)


@pytest.mark.parametrize("surface", ["advanced-transfer", "restore-decision", "transfer-direction"])
def test_explicit_cancel_is_a_successful_preparation_with_zero_mutations(surface):
    value = document(surface)
    if surface == "transfer-direction":
        value["choices"]["decision"] = "cancel"
    else:
        value["history"] = [{"kind": "cancel"}]
    result = evaluate(value, "plan")
    assert result["outcome"] == "cancelled"
    assert result["validation_passed"] is True
    authority_false(result)


def test_mixed_transfer_actions_cannot_imply_eligibility():
    value = document()
    value["bindings"]["rows"].append(transfer("u2", action="add-only"))
    value["history"] = [{"kind": "accept"}]
    result = evaluate(value, "plan")
    assert result["outcome"] == "unsupported"
    assert any(issue.get("contract") == "mixed_row_eligibility" for issue in result["component_report"]["issues"])
    authority_false(result)


def test_missing_programming_binding_retains_uncertainty():
    value = document()
    value["bindings"]["rows"][0]["staged_data_sha256"] = None
    result = evaluate(value, "validate")
    assert result["outcome"] == "uncertain"
    assert result["validation_passed"] is False


@pytest.mark.parametrize("surface", ["advanced-transfer", "restore-decision"])
def test_duplicate_rows_are_refused_without_an_accepted_prefix(surface):
    value = document(surface)
    key = "rows" if surface == "advanced-transfer" else "projects"
    value["bindings"][key].append(copy.deepcopy(value["bindings"][key][0]))
    result = evaluate(value, "plan")
    assert result["outcome"] == "refused"
    assert result["validation_passed"] is False
    assert result["component_report"] is None
    authority_false(result)


def test_declared_binding_digest_detects_changed_inputs_and_retains_canonical_report():
    value = document(history=[{"kind": "cancel"}])
    first = evaluate(value, "plan")
    value["expect_binding_sha256"] = first["component_report"]["binding_sha256"]
    assert evaluate(value, "plan")["outcome"] == "cancelled"
    value["bindings"]["rows"][0]["source_snapshot_sha256"] = OTHER
    stale = evaluate(value, "plan")
    assert stale["outcome"] == "refused"
    assert stale["issues"][0]["code"] == "stale_binding"
    assert stale["component_report"]["bindings"]["rows"][0]["source_snapshot_sha256"] == OTHER
    assert stale["binding_check_scope"] == "declared_inputs_only"
    authority_false(stale)


def test_restore_unknown_profile_and_missing_explicit_rename_remain_gated():
    value = document("restore-decision", history=[{"kind": "choose-policy", "policy": "rename"}, {"kind": "accept"}])
    value["bindings"]["name_profile"] = "unknown-profile"
    result = evaluate(value, "plan")
    assert result["outcome"] == "unsupported"
    assert result["component_report"]["intent_frozen"] is False
    del value["bindings"]["name_profile"]
    del value["bindings"]["projects"][0]["proposed_name"]
    result = evaluate(value, "validate")
    assert result["outcome"] == "uncertain"
    assert result["component_report"]["automatic_rename_rule"] is None


def test_quick_and_results_are_caller_records_without_execution_or_rollback_inference():
    quick = evaluate(document("quick-transfer", history=[{"kind": "completed", "row_id": "u1", "percentage": 100},
                                                        {"kind": "failed", "row_id": "u2", "percentage": 40},
                                                        {"kind": "close"}]), "plan")
    results = evaluate(document("restore-results", history=[{"row_id": "p1", "status": "completed"}]), "plan")
    assert quick["outcome"] == "uncertain"
    assert results["outcome"] == "prepared"
    assert quick["component_report"]["advanced_invocation_link_verified"] is False
    assert results["component_report"]["rollback_verified"] is False
    assert results["component_report"]["native_execution_verified"] is False
    authority_false(quick)
    authority_false(results)


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(component_report={"execution_admitted": True}),
    lambda value: value.update(execution_admitted=True),
    lambda value: value["bindings"].update(original_receipt="invented"),
    lambda value: value["bindings"]["rows"][0].update(owner={"project": "OTHER"}),
    lambda value: value["bindings"]["rows"][0].update(original_workflow_verified=True),
])
def test_report_receipt_and_mixed_owner_fields_are_not_input_authority(mutation):
    value = document()
    mutation(value)
    with pytest.raises(InputError):
        evaluate(value, "plan")


@pytest.mark.parametrize("value", [
    [], {}, {"format": FORMAT, "surface": "unknown", "bindings": {}},
    {"format": "bad", "surface": "advanced-transfer", "bindings": {}},
    document(bindings={"rows": "wrong"}),
    document(bindings={"rows": [transfer(source_snapshot_sha256="short")]}),
    document("restore-decision", bindings={"projects": [project(selected=1)], "archive_sha256": SHA, "destination_snapshot_sha256": OTHER}),
    document("label-transfer", bindings={"labels": [{"text": "A", "slot": True}], "capacity": 4}),
])
def test_malformed_inputs_raise_shared_input_error(value):
    with pytest.raises(InputError):
        evaluate(value, "plan")


def test_surface_histories_cannot_be_cross_linked_or_replayed_after_cancel():
    with pytest.raises(InputError):
        evaluate(document("transfer-direction", history=[{"kind": "accept"}]), "plan")
    with pytest.raises(InputError):
        evaluate(document("label-transfer", history=[]), "plan")
    cross = evaluate(document(history=[{"kind": "pause"}]), "plan")
    assert cross["outcome"] == "refused"
    terminal = evaluate(document(history=[{"kind": "cancel"}, {"kind": "accept"}]), "plan")
    assert terminal["outcome"] == "refused"


def test_label_extra_is_bounded_note_metadata_and_allocation_is_existing_component():
    value = document("label-transfer")
    value["bindings"]["extra"] = {"note": "caller-supplied synthetic labels"}
    result = evaluate(value, "plan")
    assert result["outcome"] == "prepared"
    assert result["component_report"]["planner"] == "cbus_toolkit.label_transfer_plan.plan_transfer"
    assert result["component_report"]["behavioral_comparison"] == "unassessed"
    value["bindings"]["extra"] = {"execution_admitted": True}
    with pytest.raises(InputError):
        evaluate(value, "plan")


def test_inputs_and_outputs_are_defensive_and_json_serializable():
    value = document(history=[{"kind": "cancel"}])
    before = copy.deepcopy(value)
    result = evaluate(value, "plan")
    assert value == before
    result["component_report"]["bindings"]["rows"][0]["source_identity"] = "altered"
    again = evaluate(value, "plan")
    assert again["component_report"]["bindings"]["rows"][0]["source_identity"] == "source/u1"
    assert json.loads(json.dumps(again, allow_nan=False)) == again


def test_packaged_cancel_example_runs_successfully():
    example = Path(__file__).parents[2] / "src/cbus_toolkit/offline_workflows/examples/transfer-restore.json"
    value = json.loads(example.read_text())
    result = evaluate(value, "plan")
    assert result["outcome"] == "cancelled"
    authority_false(result)


def test_all_evaluators_are_zero_io():
    values = [document(surface) for surface in ("advanced-transfer", "transfer-direction", "quick-transfer", "restore-decision", "restore-results", "label-transfer")]
    def forbidden(*args, **kwargs):
        raise AssertionError("Input evaluation attempted I/O")
    with patch("builtins.open", forbidden), patch("pathlib.Path.open", forbidden), \
         patch("socket.socket", forbidden), patch("subprocess.Popen", forbidden), \
         patch("cbus_toolkit.native.NativeProjects.__init__", forbidden), \
         patch("cbus_toolkit.programming.Programmer.__init__", forbidden):
        for value in values:
            for operation in ("inspect", "validate", "plan"):
                authority_false(evaluate(value, operation))
