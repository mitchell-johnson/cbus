"""Strict JSON adapter for pure catalogue selection and local Group drafts.

The caller supplies the complete catalogue bytes as hex, exact source IDs and
all baseline facts. This adapter never resolves a file reference or creates a
Unit, programming defaults, replacement graph, command or database writer.
"""
from __future__ import annotations

from typing import Any

from .catalogue_groups import (
    CatalogueGroupsError, CatalogueIndex,
    GroupDraft, GroupPolicy, GroupRow, validate_group_draft,
)
from .cli_support import InputError, as_array, as_int, as_text, hex_bytes, object_fields
from ..unitspec import MAX_SPEC_BYTES

INPUT_FORMAT = "cbus-offline-catalogue-groups-input-v1"
RESULT_FORMAT = "cbus-offline-catalogue-groups-result-v1"


def _row(value: Any) -> GroupRow:
    fields = object_fields(value, ("row_id", "address", "tag_name"))
    address = fields["address"]
    # Retain invalid lexical/range values for whole-draft diagnostics; never
    # silently coerce Boolean, floating-point or string aliases into an integer.
    if type(address) not in (int, str):
        raise InputError("Group address must be an integer or a text value")
    return GroupRow(as_text(fields["row_id"], "row_id"), address,
                    as_text(fields["tag_name"], "tag_name", allow_empty=True))


def _rows(value: Any, label: str) -> tuple[GroupRow, ...]:
    return tuple(_row(item) for item in as_array(value, label))


def _policy(value: Any) -> GroupPolicy:
    fields = object_fields(value, ("profile", "allowed_addresses", "capacity", "duplicate_names"),
                           ("max_tag_name_chars",))
    profile = as_text(fields["profile"], "policy.profile")
    addresses = tuple(as_int(item, "policy.allowed_addresses item", maximum=255)
                      for item in as_array(fields["allowed_addresses"], "policy.allowed_addresses", max_items=256))
    name_limit = None
    if "max_tag_name_chars" in fields:
        name_limit = as_int(fields["max_tag_name_chars"], "policy.max_tag_name_chars", minimum=1, maximum=4096)
    return GroupPolicy(addresses, as_int(fields["capacity"], "policy.capacity", maximum=256),
                       as_text(fields["duplicate_names"], "policy.duplicate_names"), name_limit, profile)


def _selection(value: Any) -> dict[str, str]:
    fields = object_fields(value, ("mode", "profile"), ("item_id", "unit_id", "firmware"))
    mode = as_text(fields["mode"], "selection.mode")
    if mode == "explicit":
        fields = object_fields(value, ("mode", "profile", "item_id", "firmware"))
    elif mode == "default":
        fields = object_fields(value, ("mode", "profile", "unit_id"))
    else:
        raise CatalogueGroupsError("Unsupported selection mode; original chooser behavior is unverified",
                                    code="unsupported_selection_mode")
    return {name: as_text(item, "selection." + name) for name, item in fields.items()}


def _operations(value: Any) -> tuple[dict[str, Any], ...]:
    operations: list[dict[str, Any]] = []
    for item in as_array(value, "groups.operations"):
        fields = object_fields(item, ("op",), ("row", "row_id", "address", "tag_name"))
        op = as_text(fields["op"], "operation.op")
        if op == "add":
            fields = object_fields(item, ("op", "row"))
            operations.append({"op": op, "row": _row(fields["row"]).as_dict()})
        elif op == "edit":
            fields = object_fields(item, ("op", "row_id", "address", "tag_name"))
            row = _row({name: fields[name] for name in ("row_id", "address", "tag_name")})
            operations.append({"op": op, **row.as_dict()})
        elif op == "delete":
            fields = object_fields(item, ("op", "row_id"))
            operations.append({"op": op, "row_id": as_text(fields["row_id"], "operation.row_id")})
        elif op == "cancel":
            object_fields(item, ("op",))
            operations.append({"op": op})
        else:
            raise CatalogueGroupsError("Unsupported Group operation; native paste/allocation is unverified",
                                        code="unsupported_group_operation")
    return tuple(operations)



def _index(data: bytes) -> CatalogueIndex:
    try:
        return CatalogueIndex.from_bytes(data)
    except CatalogueGroupsError:
        raise
    except (ValueError, RecursionError) as exc:
        # The existing version comparison deliberately reuses C-Gate numeric
        # parsing. Bound its Python numeric/recursion failure for raw user input.
        raise CatalogueGroupsError("Catalogue exceeds supported parsing/component bounds",
                                    code="invalid_catalogue") from exc


def _draft_facts(draft: GroupDraft) -> dict[str, Any]:
    return {"state": draft.state, "rows": [row.as_dict() for row in draft.rows]}


def _apply(draft: GroupDraft, operations: tuple[dict[str, Any], ...]) -> GroupDraft:
    # A failed sequence returns no partially prepared draft to the caller.
    for item in operations:
        if item["op"] == "add":
            draft = draft.add(GroupRow(**item["row"]))
        elif item["op"] == "edit":
            draft = draft.edit(item["row_id"], address=item["address"], tag_name=item["tag_name"])
        elif item["op"] == "delete":
            draft = draft.delete(item["row_id"])
        else:
            draft = draft.cancel()
    return draft


def _base(operation: str) -> dict[str, Any]:
    return {"format": RESULT_FORMAT, "workflow": "catalogue-groups", "operation": operation,
            "validation_passed": False, "outcome": "refused", "accepted_rows": [],
            "unit_creation_admitted": False, "default_pp_admitted": False,
            "replacement_graph_admitted": False, "native_compatibility_verified": False,
            "external_effects_performed": False}


def _outcome(codes: list[str]) -> str:
    return "unsupported" if any(code.startswith("unsupported_") for code in codes) else "refused"


def evaluate(document: dict, operation: str) -> dict:
    """Inspect supplied facts, validate initial inputs, or plan ordered local edits.

    ``InputError`` identifies malformed JSON shapes/types. Admitted model refusals
    are result records, with no accepted rows or executable creation artifacts.
    Baseline digest/rows are caller assertions, not observations of a project.
    """
    if operation not in ("inspect", "validate", "plan"):
        raise InputError("Operation must be inspect, validate or plan", code="unsupported_operation")
    result = _base(operation)
    try:
        fields = object_fields(document, ("format", "catalogue_hex", "groups"), ("selection",))
        if as_text(fields["format"], "format") != INPUT_FORMAT:
            raise InputError("Unsupported catalogue/Group input format", code="unsupported_format")
        group_fields = object_fields(fields["groups"],
            ("rows", "existing_groups", "policy", "target_identity", "baseline_sha256"), ("operations",))
        initial = GroupDraft(_rows(group_fields["rows"], "groups.rows"))
        existing = _rows(group_fields["existing_groups"], "groups.existing_groups")
        policy = _policy(group_fields["policy"])
        operations = _operations(group_fields.get("operations", []))
        selection_input = _selection(fields["selection"]) if "selection" in fields else None
        target = as_text(group_fields["target_identity"], "groups.target_identity")
        baseline = as_text(group_fields["baseline_sha256"], "groups.baseline_sha256")
        index = _index(hex_bytes(fields["catalogue_hex"], "catalogue_hex", max_bytes=MAX_SPEC_BYTES))
        result.update({"catalogue": index.as_dict(), "initial_draft": _draft_facts(initial),
                       "target_identity": target, "baseline_sha256": baseline,
                       "baseline_facts_verified": False})
        if operation == "inspect":
            result.update({"outcome": "inspected", "draft": _draft_facts(initial),
                "declared_operations": [dict(item, **({"row": dict(item["row"])} if "row" in item else {}))
                                        for item in operations],
                "declared_selection": dict(selection_input) if selection_input else None,
                "existing_groups": [row.as_dict() for row in existing],
                "policy": {"profile": policy.profile, "allowed_addresses": list(policy.allowed_addresses),
                           "capacity": policy.capacity, "duplicate_names": policy.duplicate_names,
                           "max_tag_name_chars": policy.max_tag_name_chars}})
            return result
        draft = _apply(initial, operations) if operation == "plan" else initial
        if draft.state == "cancelled":
            result.update({"outcome": "cancelled", "draft": _draft_facts(draft), "selection_evaluated": False})
            return result
        if selection_input is None:
            raise InputError("selection is required for validate and noncancelled plan")
        errors: list[dict[str, Any]] = []
        selection = None
        try:
            if selection_input["mode"] == "explicit":
                selection = index.select_revision(selection_input["item_id"], selection_input["firmware"],
                                                   profile=selection_input["profile"])
            else:
                selection = index.select_default(selection_input["unit_id"], profile=selection_input["profile"])
        except CatalogueGroupsError as exc:
            errors.append({"component": "catalogue_selection", "code": exc.code, "message": str(exc)})
        except (ValueError, RecursionError):
            errors.append({"component": "catalogue_selection", "code": "invalid_firmware",
                           "message": "Firmware exceeds supported numeric/component bounds"})
        checked = validate_group_draft(draft, existing_groups=existing, policy=policy,
                                      target_identity=target, baseline_sha256=baseline)
        result.update({"draft": _draft_facts(draft), "group_validation": checked.as_dict(),
                       "catalogue_selection": selection.as_dict() if selection is not None else None,
                       "selection_evaluated": True})
        for row_id, code in checked.errors:
            errors.append({"component": "group_draft", "row_id": row_id, "code": code})
        # A locally valid subset is never exposed as accepted if the other
        # component refuses. Retain diagnostics/proposed rows for review.
        if errors:
            result["group_validation"]["accepted_rows"] = []
            result.update({"outcome": _outcome([error["code"] for error in errors]), "errors": errors})
        else:
            result.update({"validation_passed": True, "outcome": "prepared",
                           "accepted_rows": [row.as_dict() for row in draft.rows]})
        return result
    except CatalogueGroupsError as exc:
        result.update({"outcome": _outcome([exc.code]),
                       "errors": [{"code": exc.code, "message": str(exc)}]})
        return result
