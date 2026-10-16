"""File-shaped public JSON cases for local Neo preparation, without native I/O."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from cbus_toolkit.extended_macros import ExtendedKeys
from cbus_toolkit.offline_workflows.cli_support import InputError
from cbus_toolkit.offline_workflows.neo_editor_input import evaluate


EXAMPLE = Path(__file__).resolve().parents[2] / "src/cbus_toolkit/offline_workflows/examples/neo-editor.json"


def supplied():
    return json.loads(EXAMPLE.read_text())


def test_packaged_example_is_complete_explicit_input_and_plans_a_apply_b_cancel():
    document = supplied()
    original = deepcopy(document)
    result = evaluate(document, "plan")
    assert result["validation_passed"] and result["outcome"] == "cancelled"
    assert result["operations_executed"] == 5
    state = result["final_state"]
    assert not state["is_open"] and not state["dirty"]
    assert state["local_apply_count"] == 1
    assert state["working"]["memory"]["bytes"]["104"] == 0xB0
    assert state["working"]["memory"]["bytes"]["80"] == 1
    assert state["working"] == state["applied"] != state["opening"]
    assert state["working"]["graph_hex"] == document["snapshot"]["graph_hex"]
    assert state["pp_save_count"] == state["project_save_count"] == 0
    assert "0" not in state["working"]["memory"]["bytes"]
    assert document == original


def test_inspect_collects_descriptors_without_executing_even_invalid_lifecycle():
    document = supplied()
    document["operations"] = [{"action": "cancel-destination"}, {"action": "request-apply"}]
    result = evaluate(document, "inspect")
    assert result["outcome"] == "inspected" and result["validation_passed"]
    assert result["operations_executed"] == 0 and not result["operation_semantics_validated"]
    assert [row["action"] for row in result["operation_descriptors"]] == ["cancel-destination", "request-apply"]
    assert result["final_state"]["working"] == result["final_state"]["opening"]
    assert result["final_state"]["history"] == [{"action": "open", "draft_revision": 0, "details": {}}]
    rejected = evaluate(document, "validate")
    assert rejected["outcome"] == "refused" and not rejected["validation_passed"]
    assert rejected["errors"][0]["operation_index"] == 1 and rejected["operations_executed"] == 0


def test_validate_and_plan_replay_same_pure_semantics_and_deterministic_snapshot():
    document = supplied()
    validated = evaluate(document, "validate")
    planned = evaluate(document, "plan")
    assert validated["validation_passed"] and validated["operation_semantics_validated"]
    assert validated["final_state"] == planned["final_state"]
    assert evaluate(document, "plan") == planned
    json.dumps(planned, sort_keys=True, allow_nan=False)


def test_nested_destination_cancel_retains_dirty_b_and_applied_a_then_accepts_once():
    document = supplied()
    document["operations"] = document["operations"][:4] + [
        {"action": "request-apply"}, {"action": "cancel-destination"},
    ]
    result = evaluate(document, "plan")
    state = result["final_state"]
    assert result["outcome"] == "prepared" and state["is_open"] and state["dirty"]
    assert state["local_apply_count"] == 1 and state["destination_action"] is None
    assert state["working"]["memory"]["bytes"]["104"] == 0xF0
    assert state["applied"]["memory"]["bytes"]["104"] == 0xB0
    document["operations"] += [{"action": "request-apply"},
                               {"action": "confirm-database", "current": {"reference": "applied"}}]
    accepted = evaluate(document, "validate")["final_state"]
    assert accepted["local_apply_count"] == 2 and not accepted["dirty"]


def test_stale_explicit_opening_reference_refuses_and_preserves_prior_history():
    document = supplied()
    document["operations"] = document["operations"][:4] + [
        {"action": "request-apply"},
        {"action": "confirm-database", "current": {"reference": "opening"}},
        {"action": "cancel-editor", "route": "cancel"},
    ]
    result = evaluate(document, "plan")
    assert result["outcome"] == "refused" and result["operations_executed"] == 5
    assert result["errors"][0]["operation_index"] == 6
    assert "baseline" in result["errors"][0]["message"]
    assert result["final_state"]["dirty"] and result["final_state"]["destination_action"] == "apply"
    assert result["final_state"]["local_apply_count"] == 1


def test_explicit_full_current_snapshot_is_used_and_graph_drift_refuses():
    document = supplied()
    document["operations"] = document["operations"][:3]
    document["operations"][2]["current"] = {"snapshot": deepcopy(document["snapshot"])}
    assert evaluate(document, "plan")["validation_passed"]
    document["operations"][2]["current"]["snapshot"]["graph_hex"] += "20"
    result = evaluate(document, "plan")
    assert result["outcome"] == "refused" and result["operations_executed"] == 2
    assert result["final_state"]["local_apply_count"] == 0


@pytest.mark.parametrize("choice", [
    {"destination": "physical"}, {"destination": "both"}, {"entire_unit": True},
    {"dlt_labels": True}, {"changed_only": True},
])
def test_unsupported_destination_choices_stop_before_local_acceptance(choice):
    document = supplied()
    document["operations"] = document["operations"][:3]
    document["operations"][2].update(choice)
    result = evaluate(document, "plan")
    assert result["outcome"] == "unsupported" and not result["validation_passed"]
    assert result["operations_executed"] == 2
    assert result["final_state"]["local_apply_count"] == 0
    assert result["final_state"]["is_open"] and result["final_state"]["dirty"]


@pytest.mark.parametrize("change", [
    {"firmware": "2.5.01"}, {"unit_type": "KEYM8"}, {"catalogue": "5058NL"},
    {"network_state": "open"}, {"source": "//WFNEO/254/p/1"}, {"synthetic": False},
])
def test_exact_caller_profile_gates_cannot_be_replaced_with_example_defaults(change):
    document = supplied()
    document["profile"].update(change)
    result = evaluate(document, "validate")
    assert not result["validation_passed"]
    assert result["final_state"] is None and result["operations_executed"] == 0


@pytest.mark.parametrize("field", ["profile", "spec", "snapshot", "operations", "source_metadata"])
def test_missing_required_top_input_is_a_shape_error(field):
    document = supplied()
    del document[field]
    with pytest.raises(InputError, match="missing"):
        evaluate(document, "plan")


@pytest.mark.parametrize("scope", ["top", "profile", "spec", "snapshot", "operation", "preset"])
def test_unknown_fields_fail_closed(scope):
    document = supplied()
    target = {"top": document, "profile": document["profile"], "spec": document["spec"],
              "snapshot": document["snapshot"], "operation": document["operations"][0],
              "preset": document["operations"][0]["options"]}[scope]
    target["native_save"] = True
    with pytest.raises(InputError, match="unknown"):
        evaluate(document, "plan")


@pytest.mark.parametrize("case", ["duplicate_parameter", "source_mismatch", "field_identity", "bool_byte",
                                  "alias_address", "float_pp", "bad_hex", "bool_key", "null_snapshot",
                                  "double_current", "too_many_operations", "bool_choice"])
def test_malformed_or_ambiguous_decoded_json_refuses_without_defaults(case):
    document = supplied()
    if case == "duplicate_parameter":
        document["spec"]["parameters"].append(deepcopy(document["spec"]["parameters"][0]))
    elif case == "source_mismatch":
        document["spec"]["parameters"][0]["source"] = "not-supplied.xml"
    elif case == "field_identity":
        document["spec"]["parameters"][0]["fields"]["Name"] = "Wrong"
    elif case == "bool_byte":
        document["snapshot"]["memory"]["bytes"]["104"] = True
    elif case == "alias_address":
        document["snapshot"]["memory"]["bytes"]["0104"] = 0
    elif case == "float_pp":
        document["snapshot"]["values"]["OpaqueExtraPP"] = 1.5
    elif case == "bad_hex":
        document["snapshot"]["graph_hex"] = "0z"
    elif case == "bool_key":
        document["operations"][0]["options"]["key"] = True
    elif case == "null_snapshot":
        document["snapshot"] = None
    elif case == "double_current":
        document["operations"][2]["current"]["snapshot"] = document["snapshot"]
    elif case == "too_many_operations":
        document["operations"] = [{"action": "request-apply"}] * 129
    else:
        document["operations"][2]["entire_unit"] = 0
    with pytest.raises(InputError):
        evaluate(document, "plan")


def test_unknown_operation_or_format_is_explicitly_unsupported():
    document = supplied()
    document["operations"] = [{"action": "native-save"}]
    assert evaluate(document, "plan")["outcome"] == "unsupported"
    document["format"] = "native-editor-history"
    assert evaluate(document, "inspect")["outcome"] == "unsupported"
    assert evaluate(supplied(), "apply")["outcome"] == "unsupported"


def test_raw_pp_inconsistency_is_refused_with_no_open_state_or_operations():
    document = supplied()
    document["snapshot"]["memory"]["bytes"]["104"] = 0xF0
    result = evaluate(document, "plan")
    assert result["outcome"] == "refused" and not result["validation_passed"]
    assert "disagree" in result["errors"][0]["message"]
    assert result["final_state"] is None


def test_evaluate_is_pure_and_never_upgrades_local_acceptance_to_persistence(monkeypatch):
    import builtins
    import socket

    document = supplied()
    def forbidden(*args, **kwargs):
        raise AssertionError("Input evaluator attempted I/O")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(Path, "read_text", forbidden)
        patch.setattr(Path, "read_bytes", forbidden)
        patch.setattr(Path, "write_text", forbidden)
        patch.setattr(Path, "write_bytes", forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(socket, "create_connection", forbidden)
        patch.setattr(ExtendedKeys, "apply", forbidden)
        result = evaluate(document, "plan")
    for key in ("saved", "io_performed", "native_acceptance", "physical_acceptance", "external_persistence_verified"):
        assert result[key] is False
    assert "PROPOSED" in result["final_state"]["policy"]
    assert result["final_state"]["original_terminal_semantics"] == "original terminal semantics unassessed"
    result["final_state"]["working"]["values"]["OpaqueExtraPP"]["array"][1]["flag"] = False
    assert document["snapshot"]["values"]["OpaqueExtraPP"]["array"][1]["flag"] is True
