"""Strict caller-input adapter for pure offline copy/paste intent preparation.

The caller supplies every owner, selection, snapshot and conflict fact. Inspect
parses descriptors only. Validate checks the declared local history; plan returns
its offline draft result. No command, clipboard, file or persistence is executed.
"""
from __future__ import annotations

from dataclasses import dataclass

from .cli_support import InputError, as_array, as_bool, as_text, hex_bytes, object_fields
from .copy_paste import (
    CopyKind, CopyPasteError, CopyPasteProfile, CopyPhase, CopySource, CopyTarget,
    Ownership, PasteRequest, ProfileMode, Refusal, attempt_paste, cancel_intent, copy_intent,
    draft_child_profile, mark_uncertain, persistence_gate, select_target,
)


INPUT_FORMAT = "cbus-offline-copy-paste-input-v1"
RESULT_FORMAT = "cbus-offline-copy-paste-adapter-v1"
_MAX_OPERATIONS = 256


@dataclass(frozen=True)
class _Operation:
    action: str
    value: CopyTarget | PasteRequest | CopyPhase | str | None = None


def _shape(value, required, optional=()):
    object_fields(value, required, optional)
    return value


def _kind(value, label):
    text = as_text(value, label)
    try:
        return CopyKind(text)
    except ValueError as error:
        raise InputError(f"{label} is not a supported descriptor kind") from error


def _owner(value):
    value = _shape(value, ("endpoint", "repository", "project"))
    return Ownership(*(as_text(value[field], f"owner.{field}")
                       for field in ("endpoint", "repository", "project")))


def _descriptor(value, *, source=False):
    fields = ("owner", "selector", "oid", "kind")
    value = _shape(value, fields + (("snapshot_hex",) if source else ()))
    arguments = (_owner(value["owner"]), as_text(value["selector"], "selector"),
                 as_text(value["oid"], "oid"), _kind(value["kind"], "kind"))
    if source:
        return CopySource(*arguments, hex_bytes(value["snapshot_hex"], "snapshot_hex"))
    return CopyTarget(*arguments)


def _profile(value):
    value = _shape(value, ("mode",), ("source_kind",))
    mode = as_text(value["mode"], "profile.mode")
    kind = _kind(value["source_kind"], "profile.source_kind") if "source_kind" in value else None
    if mode == ProfileMode.PROPOSED_OFFLINE_DRAFT.value:
        if kind is None:
            raise InputError("proposed-offline-draft profile requires source_kind")
        try:
            return draft_child_profile(kind), mode
        except CopyPasteError:
            # Valid descriptor kinds do not establish a recovered copy contract.
            return CopyPasteProfile(f"unsupported-offline-{kind.value.lower()}-intent",
                                    source_kind=kind), mode
    # An unknown/native/original profile name never acquires a draft route.
    return CopyPasteProfile("caller-unsupported-clipboard-contract", source_kind=kind), mode


def _nullable(value, converter, label):
    return None if value is None else converter(value, label)


def _request(value):
    fields = ("address", "name", "source_sha256", "address_conflict", "name_conflict", "conflict_choice")
    value = _shape(value, (), fields)
    return PasteRequest(
        address=_nullable(value.get("address"), as_text, "request.address"),
        name=_nullable(value.get("name"), as_text, "request.name"),
        source_sha256=_nullable(value.get("source_sha256"), as_text, "request.source_sha256"),
        address_conflict=_nullable(value.get("address_conflict"), as_bool, "request.address_conflict"),
        name_conflict=_nullable(value.get("name_conflict"), as_bool, "request.name_conflict"),
        conflict_choice=as_text(value.get("conflict_choice", "refuse"), "request.conflict_choice"),
    )


def _operations(value):
    result = []
    for index, row in enumerate(as_array(value, "operations", max_items=_MAX_OPERATIONS)):
        _shape(row, ("action",), ("target", "request", "detail", "stage"))
        action = as_text(row["action"], f"operations[{index}].action")
        if action == "select-target":
            _shape(row, ("action", "target"))
            result.append(_Operation(action, _descriptor(row["target"])))
        elif action == "paste":
            _shape(row, ("action", "request"))
            result.append(_Operation(action, _request(row["request"])))
        elif action == "cancel":
            _shape(row, ("action",))
            result.append(_Operation(action))
        elif action == "uncertain":
            _shape(row, ("action", "detail"))
            detail = as_text(row["detail"], "uncertain.detail")
            result.append(_Operation(action, Refusal("uncertain_outcome", detail).detail))
        elif action == "persistence-gate":
            _shape(row, ("action", "stage"))
            stage = as_text(row["stage"], "persistence-gate.stage")
            if stage not in (CopyPhase.SAVED.value, CopyPhase.REOPENED.value):
                raise InputError("persistence-gate.stage must be saved or reopened")
            result.append(_Operation(action, CopyPhase(stage)))
        else:
            raise InputError(f"operations[{index}] has an unknown action: {action}")
    return tuple(result)


def _operation_descriptor(operation):
    value = {"action": operation.action}
    if isinstance(operation.value, CopyTarget):
        target = operation.value
        value["target"] = {"owner": vars(target.owner).copy(), "selector": target.selector,
                           "oid": target.oid, "kind": target.kind.value}
    elif isinstance(operation.value, PasteRequest):
        value["request"] = vars(operation.value).copy()
    elif isinstance(operation.value, CopyPhase):
        value["stage"] = operation.value.value
    elif isinstance(operation.value, str):
        value["detail"] = operation.value
    return value


def _outcome(intent, refusal=None):
    refusal = refusal if refusal is not None else intent.refusal
    if intent.phase is CopyPhase.UNCERTAIN:
        return "uncertain", False
    if refusal is not None:
        return ("unsupported" if refusal.code.startswith("unsupported_") else "refused"), False
    if intent.phase is CopyPhase.CANCELLED:
        return "cancelled", True
    if intent.profile.mode is ProfileMode.UNSUPPORTED:
        return "unsupported", False
    return "prepared", True


def _replay(intent, operations):
    results = []
    for index, operation in enumerate(operations):
        try:
            if operation.action == "select-target":
                intent = select_target(intent, operation.value)
            elif operation.action == "paste":
                intent = attempt_paste(intent, operation.value)
            elif operation.action == "cancel":
                intent = cancel_intent(intent)
            elif operation.action == "uncertain":
                intent = mark_uncertain(intent, operation.value)
            else:
                refusal = persistence_gate(intent, operation.value)
                results.append({"index": index, "action": operation.action, "phase": intent.phase.value,
                                "refusal": vars(refusal).copy()})
                return intent, results, refusal, len(operations) - index - 1
        except CopyPasteError as error:
            refusal = Refusal("invalid_transition", str(error))
            results.append({"index": index, "action": operation.action, "phase": intent.phase.value,
                            "refusal": vars(refusal).copy()})
            return intent, results, refusal, len(operations) - index - 1
        results.append({"index": index, "action": operation.action, "phase": intent.phase.value,
                        "refusal": None if intent.refusal is None else vars(intent.refusal).copy()})
        if intent.phase in (CopyPhase.REFUSED, CopyPhase.UNCERTAIN):
            return intent, results, intent.refusal, len(operations) - index - 1
    return intent, results, None, 0


def evaluate(document: dict, operation: str) -> dict:
    """Evaluate one strict caller document; all effects are local pure state."""
    if operation not in ("inspect", "validate", "plan"):
        raise InputError("operation must be inspect, validate or plan")
    try:
        document = _shape(document, ("format", "source", "profile", "operations"))
        if document["format"] != INPUT_FORMAT:
            raise InputError(f"format must be {INPUT_FORMAT}")
        source = _descriptor(document["source"], source=True)
        profile, requested_mode = _profile(document["profile"])
        operations = _operations(document["operations"])
        intent = copy_intent(source, profile=profile)
    except CopyPasteError as error:
        raise InputError(str(error)) from error

    result = {
        "format": RESULT_FORMAT,
        "workflow": "copy-paste",
        "operation": operation,
        "scope": "proposed-offline-draft",
        "requested_profile_mode": requested_mode,
        "execution_enabled": False,
        "native_compatibility": False,
        "plan_generated": operation == "plan",
        "operations": [_operation_descriptor(value) for value in operations],
    }
    if operation == "inspect":
        result.update(validation_passed=False, outcome="inspected", component=intent.report(),
                      operation_results=[], not_attempted_operations=len(operations), refusal=None)
        return result

    intent, results, refusal, remaining = _replay(intent, operations)
    outcome, passed = _outcome(intent, refusal)
    if outcome == "unsupported" and refusal is None:
        refusal_report = {"code": "unsupported_profile", "detail": "No offline draft route was selected"}
    else:
        refusal_report = None if refusal is None else vars(refusal).copy()
    result.update(validation_passed=passed, outcome=outcome, component=intent.report(),
                  operation_results=results, not_attempted_operations=remaining, refusal=refusal_report)
    return result
