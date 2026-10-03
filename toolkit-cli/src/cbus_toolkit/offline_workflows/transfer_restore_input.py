"""Strict JSON inputs for six independent transfer/restore preparations.

The adapter consumes supplied identities, digests and choices only. Inspection
constructs opening descriptors with no history applied. Validation and planning
recompute the complete ordered history through the existing pure components.
Digest checks compare declared inputs, never current files or a native receipt.
"""
from __future__ import annotations

from .cli_support import (InputError, as_array as _as_array, as_bool as _as_bool,
                          as_int as _as_int, as_text as _as_text, object_fields)
from . import transfer_restore as component

FORMAT = "cbus-offline-transfer-restore-input-v1"
SURFACES = ("advanced-transfer", "transfer-direction", "quick-transfer",
            "restore-decision", "restore-results", "label-transfer")
OPERATIONS = ("inspect", "validate", "plan")


def as_array(value):
    return _as_array(value, "transfer/restore array")


def as_text(value):
    return _as_text(value, "transfer/restore text")


def as_bool(value):
    return _as_bool(value, "transfer/restore selection")


def as_int(value, *, minimum=0, maximum=4096):
    return _as_int(value, "transfer/restore integer", minimum=minimum, maximum=maximum)


def _object(value, required, optional=()):
    object_fields(value, required, optional)
    return value


def _optional_text(value):
    return None if value is None else as_text(value)


def _strings(value):
    return [as_text(item) for item in as_array(value)]


def _digest(value, *, optional=False):
    if optional and value is None:
        return None
    value = as_text(value)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise InputError("Expected a lowercase SHA-256 digest")
    return value


def _transfer_row(value):
    value = _object(value, ("row_id", "source_identity", "source_snapshot_sha256"),
                    ("destination_identity", "destination_snapshot_sha256", "staged_data_sha256",
                     "source_address", "serial", "unit_type", "firmware", "route", "destination_state", "action"))
    fields = dict(value)
    for name in ("row_id", "source_identity", "destination_state", "action"):
        if name in fields:
            fields[name] = as_text(fields[name])
    for name in ("destination_identity", "source_address", "serial", "unit_type", "firmware"):
        if name in fields:
            fields[name] = _optional_text(fields[name])
    for name in ("source_snapshot_sha256", "destination_snapshot_sha256", "staged_data_sha256"):
        if name in fields:
            fields[name] = _digest(fields[name], optional=name != "source_snapshot_sha256")
    if "route" in fields:
        fields["route"] = _strings(fields["route"])
    return component.TransferRow(**fields)


def _restore_project(value):
    value = _object(value, ("row_id", "member_identity", "source_project", "source_snapshot_sha256"),
                    ("selected", "proposed_name"))
    fields = {name: as_text(value[name]) for name in ("row_id", "member_identity", "source_project")}
    fields["source_snapshot_sha256"] = _digest(value["source_snapshot_sha256"])
    if "selected" in value:
        fields["selected"] = as_bool(value["selected"])
    if "proposed_name" in value:
        fields["proposed_name"] = _optional_text(value["proposed_name"])
    return component.RestoreProject(**fields)


def _advanced_event(value):
    value = _object(value, ("kind",), ("row_ids", "action"))
    fields = {"kind": as_text(value["kind"])}
    if "row_ids" in value:
        fields["row_ids"] = _strings(value["row_ids"])
    if "action" in value:
        fields["action"] = _optional_text(value["action"])
    return component.AdvancedTransferEvent(**fields)


def _quick_event(value):
    value = _object(value, ("kind",), ("row_id", "percentage", "detail"))
    fields = {"kind": as_text(value["kind"])}
    for name in ("row_id", "detail"):
        if name in value:
            fields[name] = _optional_text(value[name])
    if "percentage" in value:
        fields["percentage"] = None if value["percentage"] is None else as_int(value["percentage"], minimum=0, maximum=100)
    return component.QuickTransferEvent(**fields)


def _restore_event(value):
    value = _object(value, ("kind",), ("row_ids", "policy", "proposed_name"))
    fields = {"kind": as_text(value["kind"])}
    if "row_ids" in value:
        fields["row_ids"] = _strings(value["row_ids"])
    for name in ("policy", "proposed_name"):
        if name in value:
            fields[name] = _optional_text(value[name])
    return component.RestoreEvent(**fields)


def _restore_result(value):
    value = _object(value, ("row_id", "status"), ("detail",))
    fields = {name: as_text(value[name]) for name in ("row_id", "status")}
    if "detail" in value:
        fields["detail"] = _optional_text(value["detail"])
    return component.RestoreResult(**fields)


def _history(document, factory):
    return [factory(value) for value in as_array(document.get("history", []))]


def _prepare(document, operation):
    surface = document["surface"]
    binding = document["bindings"]
    apply_history = operation != "inspect"
    if surface == "advanced-transfer":
        binding = _object(binding, ("rows",))
        rows = [_transfer_row(value) for value in as_array(binding["rows"])]
        history = _history(document, _advanced_event)
        return component.prepare_advanced_transfer(rows, history if apply_history else ()), len(history)
    if surface == "transfer-direction":
        binding = _object(binding, (), ("context_sha256",))
        choices = _object(document["choices"], ("choice", "decision"))
        choice = _optional_text(choices["choice"])
        decision = as_text(choices["decision"])
        if decision not in ("review", "accept", "cancel"):
            raise InputError("Unknown transfer direction decision")
        return component.prepare_transfer_direction(choice, decision=decision if apply_history else "review",
                   context_sha256=_digest(binding.get("context_sha256"), optional=True)), 1
    if surface == "quick-transfer":
        binding = _object(binding, ("row_ids", "attempt_id"), ("context_sha256", "previous_attempt_sha256"))
        row_ids = _strings(binding["row_ids"])
        history = _history(document, _quick_event)
        return component.record_quick_transfer(row_ids, history if apply_history else (),
                   attempt_id=as_text(binding["attempt_id"]),
                   context_sha256=_digest(binding.get("context_sha256"), optional=True),
                   previous_attempt_sha256=_digest(binding.get("previous_attempt_sha256"), optional=True)), len(history)
    if surface == "restore-decision":
        binding = _object(binding, ("projects", "archive_sha256", "destination_snapshot_sha256"),
                          ("destination_names", "name_profile"))
        projects = [_restore_project(value) for value in as_array(binding["projects"])]
        history = _history(document, _restore_event)
        return component.prepare_restore(projects, archive_sha256=_digest(binding["archive_sha256"]),
                   destination_snapshot_sha256=_digest(binding["destination_snapshot_sha256"]),
                   destination_names=_strings(binding.get("destination_names", [])),
                   name_profile=as_text(binding.get("name_profile", component.NAME_PROFILE)),
                   history=history if apply_history else ()), len(history)
    if surface == "restore-results":
        binding = _object(binding, ("projects", "attempt_id"), ("decision_sha256", "previous_attempt_sha256"))
        projects = [_restore_project(value) for value in as_array(binding["projects"])]
        results = _history(document, _restore_result)
        return component.record_restore_results(projects, results if apply_history else (),
                   attempt_id=as_text(binding["attempt_id"]),
                   decision_sha256=_digest(binding.get("decision_sha256"), optional=True),
                   previous_attempt_sha256=_digest(binding.get("previous_attempt_sha256"), optional=True)), len(results)
    binding = _object(binding, ("labels", "capacity"), ("extra",))
    labels = []
    for value in as_array(binding["labels"]):
        value = _object(value, ("text",), ("slot",))
        label = {"text": as_text(value["text"])}
        if "slot" in value:
            label["slot"] = as_int(value["slot"], minimum=0, maximum=4095)
        labels.append(label)
    extra = _object(binding.get("extra", {}), (), ("note",))
    extra = {name: as_text(value) for name, value in extra.items()}
    return component.prepare_label_transfer(labels, as_int(binding["capacity"], minimum=1, maximum=4096), extra), 0


def _result(operation, surface, report, *, outcome, validation_passed, issues=(), history_count=0):
    return {"format": "cbus-offline-transfer-restore-result-v1", "workflow": "transfer-restore",
            "operation": operation, "surface": surface, "outcome": outcome,
            "validation_passed": validation_passed, "component_report": report,
            "issues": list(issues), "history_applied": operation != "inspect",
            "supplied_history_count": history_count,
            "binding_check_scope": "declared_inputs_only",
            "preparation_only": True, "execution_admitted": False,
            "original_workflow_verified": False, "native_mutations": 0,
            "queue_commands": [], "automatic_replay_authorized": False}


def evaluate(document: dict, operation: str) -> dict:
    """Inspect, validate or plan one explicitly selected pure input surface.

    Invalid JSON schema/types raise InputError. Structurally valid input rejected
    by a component returns refused; unsupported and uncertain native contracts
    stay distinct. No caller output report or receipt is accepted as input.
    """
    if operation not in OPERATIONS:
        raise InputError("Unknown transfer/restore operation")
    document = _object(document, ("format", "surface", "bindings"),
                       ("history", "choices", "expect_binding_sha256"))
    if document["format"] != FORMAT:
        raise InputError("Unsupported transfer/restore input format", code="unsupported_format")
    surface = as_text(document["surface"])
    if surface not in SURFACES:
        raise InputError("Unknown transfer/restore surface", code="unsupported_surface")
    if surface == "transfer-direction":
        if "choices" not in document or "history" in document:
            raise InputError("Direction requires its own choices object and admits no other surface history")
    elif "choices" in document:
        raise InputError("Choices object belongs only to the direction surface")
    if surface == "label-transfer" and "history" in document:
        raise InputError("The structural label planner admits no event history")
    expected = _digest(document.get("expect_binding_sha256"), optional=True)
    try:
        prepared, count = _prepare(document, operation)
    except InputError:
        raise
    except (ValueError, TypeError) as error:
        return _result(operation, surface, None, outcome="refused", validation_passed=False,
                       issues=({"code": "component_refused", "message": str(error)},))
    report = prepared.as_dict()
    if expected is not None and expected != report["binding_sha256"]:
        return _result(operation, surface, report, outcome="refused", validation_passed=False,
                       issues=({"code": "stale_binding", "expected": expected,
                                "actual": report["binding_sha256"]},), history_count=count)
    if operation == "inspect":
        return _result(operation, surface, report, outcome="inspected", validation_passed=True, history_count=count)
    cancelled = report.get("terminal_choice") == "cancel" or (
        surface == "transfer-direction" and document["choices"]["decision"] == "cancel")
    outcome = "cancelled" if cancelled else {
        "confirmed_noop": "prepared", "not_applicable": "prepared", "prepared": "prepared",
        "unsupported": "unsupported", "uncertain": "uncertain",
    }[report["outcome"]]
    return _result(operation, surface, report, outcome=outcome,
                   validation_passed=outcome in ("prepared", "cancelled"),
                   issues=report["issues"], history_count=count)
