"""Synthetic caller-input contracts for the pure copy/paste adapter."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from cbus_toolkit.offline_workflows import copy_paste_input as adapter
from cbus_toolkit.offline_workflows.cli_support import InputError


RAW = b'<!--keep--><Group oid="g1"><Unknown key="first"/><Unknown key="second"/></Group>'
OWNER = {"endpoint": "offline:custom-fixture", "repository": "my-repository", "project": "CUSTOM"}


def document():
    return {
        "format": adapter.INPUT_FORMAT,
        "source": {"owner": deepcopy(OWNER), "selector": "//CUSTOM/0007/56/9",
                   "oid": "g1", "kind": "Group", "snapshot_hex": RAW.hex()},
        "profile": {"mode": "proposed-offline-draft", "source_kind": "Group"},
        "operations": [
            {"action": "select-target", "target": {
                "owner": deepcopy(OWNER), "selector": "//CUSTOM/0007/56",
                "oid": "a1", "kind": "Application"}},
            {"action": "paste", "request": {
                "address": "0091", "name": " Caller selected name ",
                "source_sha256": hashlib.sha256(RAW).hexdigest(),
                "address_conflict": False, "name_conflict": False,
                "conflict_choice": "refuse"}},
        ],
    }


@pytest.mark.parametrize("operation", ["validate", "plan"])
def test_valid_user_input_drives_local_policy_without_mutating_source(operation):
    value = document()
    original = deepcopy(value)
    report = adapter.evaluate(value, operation)
    assert value == original
    assert report["format"] == adapter.RESULT_FORMAT
    assert report["workflow"] == "copy-paste"
    assert report["operation"] == operation
    assert report["validation_passed"] is True
    assert report["outcome"] == "prepared"
    assert report["plan_generated"] is (operation == "plan")
    component = report["component"]
    assert component["phase"] == "accepted"
    assert component["source"]["owner"] == OWNER
    assert component["source"]["selector"] == "//CUSTOM/0007/56/9"
    assert component["source"]["sha256"] == hashlib.sha256(RAW).hexdigest()
    assert component["request"]["address"] == "0091"
    assert component["request"]["name"] == " Caller selected name "
    assert component["commands"] == []
    assert component["external_mutation_attempted"] is False
    assert component["native_compatibility"] is False
    assert component["saved"] is False and component["reopened"] is False
    assert [row["action"] for row in report["operation_results"]] == ["select-target", "paste"]


def test_inspect_parses_all_descriptors_without_replaying_timeline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("inspect replayed a local operation")
    for method in ("select_target", "attempt_paste", "cancel_intent", "mark_uncertain", "persistence_gate"):
        monkeypatch.setattr(adapter, method, forbidden)
    value = document()
    value["operations"] += [{"action": "uncertain", "detail": "Explicit uncertain history"},
                            {"action": "persistence-gate", "stage": "saved"}]
    report = adapter.evaluate(value, "inspect")
    assert report["outcome"] == "inspected"
    assert report["validation_passed"] is False
    assert report["component"]["phase"] == "copied"
    assert report["operation_results"] == []
    assert report["not_attempted_operations"] == 4
    assert report["operations"][0]["target"]["selector"] == "//CUSTOM/0007/56"


@pytest.mark.parametrize("field", ["endpoint", "repository", "project"])
def test_mixed_ownership_refuses_even_if_exact_oids_collide(field):
    value = document()
    value["operations"][0]["target"]["owner"][field] += "-other"
    report = adapter.evaluate(value, "plan")
    assert report["outcome"] == "refused"
    assert report["validation_passed"] is False
    assert report["refusal"]["code"] == "different_owner"
    assert report["component"]["source"]["owner"] == OWNER


@pytest.mark.parametrize("operation", ["validate", "plan"])
def test_stale_supplied_hash_refuses_before_any_later_action(operation):
    value = document()
    value["operations"][1]["request"]["source_sha256"] = "0" * 64
    value["operations"].append({"action": "cancel"})
    report = adapter.evaluate(value, operation)
    assert report["outcome"] == "refused"
    assert report["refusal"]["code"] == "source_binding"
    assert report["component"]["phase"] == "refused"
    assert report["not_attempted_operations"] == 1
    assert report["validation_passed"] is False


@pytest.mark.parametrize("changes,code", [
    ({"address_conflict": True}, "address_conflict"),
    ({"name_conflict": True}, "name_conflict"),
    ({"address_conflict": None}, "unknown_conflicts"),
    ({"name_conflict": None}, "unknown_conflicts"),
    ({"source_sha256": None}, "source_binding"),
    ({"address": None}, "explicit_identity_required"),
    ({"name": None}, "explicit_identity_required"),
    ({"conflict_choice": "overwrite"}, "unsupported_conflict_choice"),
])
def test_component_conflict_and_identity_gates_are_preserved(changes, code):
    value = document()
    value["operations"][1]["request"].update(changes)
    report = adapter.evaluate(value, "validate")
    assert report["validation_passed"] is False
    assert report["refusal"]["code"] == code
    assert report["component"]["commands"] == []


@pytest.mark.parametrize("mode", ["unsupported", "original-toolkit", "native-clipboard", "unproved-profile"])
def test_unknown_original_contracts_never_acquire_an_offline_draft(mode):
    value = document()
    value["profile"] = {"mode": mode}
    report = adapter.evaluate(value, "plan")
    assert report["outcome"] == "unsupported"
    assert report["requested_profile_mode"] == mode
    assert report["validation_passed"] is False
    assert report["refusal"]["code"] == "unsupported_profile"
    assert report["component"]["commands"] == []


@pytest.mark.parametrize("kind", ["Project", "Unit", "NetVar", "Trigger", "Action", "Enable"])
def test_unverified_draft_routes_remain_unsupported(kind):
    value = document()
    value["source"]["kind"] = kind
    value["profile"]["source_kind"] = kind
    report = adapter.evaluate(value, "validate")
    assert report["outcome"] == "unsupported"
    assert report["validation_passed"] is False
    assert report["component"]["source"]["kind"] == kind


def test_wrong_profile_and_target_kinds_preserve_existing_refusals():
    value = document()
    value["profile"]["source_kind"] = "Level"
    assert adapter.evaluate(value, "plan")["refusal"]["code"] == "unsupported_source_kind"
    value = document()
    value["operations"][0]["target"]["kind"] = "Network"
    assert adapter.evaluate(value, "plan")["refusal"]["code"] == "wrong_target_kind"


def test_cancellation_is_successful_only_for_local_draft_discard():
    value = document()
    value["operations"].append({"action": "cancel"})
    report = adapter.evaluate(value, "plan")
    assert report["outcome"] == "cancelled"
    assert report["validation_passed"] is True
    assert report["component"]["cancellation_effect"] == "discarded-offline-intent-only"
    assert report["component"]["external_mutation_attempted"] is False
    value["operations"].append({"action": "paste", "request": {}})
    report = adapter.evaluate(value, "plan")
    assert report["outcome"] == "refused"
    assert report["validation_passed"] is False
    assert report["refusal"]["code"] == "invalid_transition"
    assert report["component"]["phase"] == "cancelled"


def test_explicit_uncertainty_stops_dependent_operations_without_replay():
    value = document()
    value["operations"] = [value["operations"][0],
                           {"action": "uncertain", "detail": "Caller recorded interruption"},
                           value["operations"][1], {"action": "cancel"}]
    report = adapter.evaluate(value, "plan")
    assert report["outcome"] == "uncertain"
    assert report["validation_passed"] is False
    assert report["component"]["phase"] == "uncertain"
    assert report["refusal"]["code"] == "uncertain_outcome"
    assert report["not_attempted_operations"] == 2
    assert len(report["operation_results"]) == 2


@pytest.mark.parametrize("stage", ["saved", "reopened"])
def test_persistence_requests_are_explicit_unsupported_gates(stage):
    value = document()
    value["operations"].append({"action": "persistence-gate", "stage": stage})
    report = adapter.evaluate(value, "plan")
    assert report["outcome"] == "unsupported"
    assert report["validation_passed"] is False
    assert report["refusal"]["code"] == "unsupported_persistence"
    assert report["component"]["phase"] == "accepted"
    assert report["component"]["saved"] is False
    assert report["component"]["reopened"] is False


def test_duplicate_paste_cannot_replay_an_already_accepted_intent():
    value = document()
    value["operations"].append(deepcopy(value["operations"][1]))
    report = adapter.evaluate(value, "plan")
    assert report["outcome"] == "refused"
    assert report["validation_passed"] is False
    assert report["refusal"]["code"] == "invalid_transition"
    assert report["component"]["history"].count("paste-attempted") == 1


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(format="wrong-format"),
    lambda value: value.update(extra="unknown"),
    lambda value: value["source"].update(extra="unknown"),
    lambda value: value["source"]["owner"].update(extra="unknown"),
    lambda value: value["source"].update(snapshot_hex="zz"),
    lambda value: value["source"].update(snapshot_hex=""),
    lambda value: value["source"].update(kind="NotAnEntity"),
    lambda value: value["profile"].update(extra="unknown"),
    lambda value: value["profile"].pop("source_kind"),
    lambda value: value["operations"][1]["request"].update(address=91),
    lambda value: value["operations"][1]["request"].update(address_conflict=0),
    lambda value: value["operations"][1]["request"].update(extra="unknown"),
    lambda value: value["operations"].append({"action": "cancel", "request": {}}),
    lambda value: value["operations"].append({"action": "save"}),
    lambda value: value["operations"].append({"action": "persistence-gate", "stage": "accepted"}),
])
def test_all_schema_fields_are_strictly_checked_before_any_replay(mutation, monkeypatch):
    value = document()
    mutation(value)
    def forbidden(*args, **kwargs):
        raise AssertionError("replay preceded complete schema validation")
    monkeypatch.setattr(adapter, "select_target", forbidden)
    with pytest.raises(InputError):
        adapter.evaluate(value, "plan")


def test_input_bounds_and_unknown_operation_are_rejected():
    value = document()
    value["operations"] = [{"action": "cancel"}] * 257
    with pytest.raises(InputError):
        adapter.evaluate(value, "inspect")
    with pytest.raises(InputError):
        adapter.evaluate(document(), "execute")
    with pytest.raises(InputError):
        adapter.evaluate([], "plan")


def test_reports_are_detached_and_do_not_disclose_snapshot_bytes():
    value = document()
    report = adapter.evaluate(value, "plan")
    report["operations"][0]["target"]["owner"]["project"] = "changed"
    report["component"]["source"]["owner"]["project"] = "changed"
    assert value["source"]["owner"]["project"] == "CUSTOM"
    assert value["operations"][0]["target"]["owner"]["project"] == "CUSTOM"
    assert "snapshot_hex" not in json.dumps(report)
    assert adapter.evaluate(value, "plan")["component"]["source"]["owner"]["project"] == "CUSTOM"


def test_committed_example_is_a_meaningful_bound_offline_draft():
    example = Path(adapter.__file__).with_name("examples") / "copy-paste.json"
    value = json.loads(example.read_text())
    report = adapter.evaluate(value, "plan")
    assert report["outcome"] == "prepared"
    assert report["validation_passed"] is True
    assert report["component"]["source"]["selector"] == "//DEMO/0254/56/1"
    assert report["component"]["request"]["address"] == "0042"
    assert report["component"]["commands"] == []


def test_practical_operation_bound_is_enforced_without_running_inspection():
    value = document()
    value["operations"] = [value["operations"][0]] * 256
    assert adapter.evaluate(value, "inspect")["not_attempted_operations"] == 256
    value["operations"].append(value["operations"][0])
    with pytest.raises(InputError):
        adapter.evaluate(value, "inspect")


def test_unsupported_profile_without_paste_still_refuses_validation():
    value = document()
    value["profile"] = {"mode": "original-toolkit"}
    value["operations"] = []
    report = adapter.evaluate(value, "validate")
    assert report["outcome"] == "unsupported"
    assert report["validation_passed"] is False
    assert report["refusal"]["code"] == "unsupported_profile"
    value["operations"] = [{"action": "cancel"}]
    report = adapter.evaluate(value, "plan")
    assert report["outcome"] == "cancelled"
    assert report["validation_passed"] is True
    assert report["component"]["commands"] == []


def test_invalid_uncertainty_text_is_parsed_before_any_local_history(monkeypatch):
    value = document()
    value["operations"].append({"action": "uncertain", "detail": "invalid\ncontrol"})
    def forbidden(*args, **kwargs):
        raise AssertionError("malformed late detail reached earlier replay")
    monkeypatch.setattr(adapter, "select_target", forbidden)
    with pytest.raises(InputError):
        adapter.evaluate(value, "plan")
