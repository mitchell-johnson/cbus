"""Validate explicit JSON and prepare a local Neo editor history, without I/O.

All profile, decoded specification, PP, known memory, graph and group facts
come from the caller. The packaged example is optional input, never a default.
Apply remains the existing PROPOSED local acceptance policy, not persistence.
"""
from __future__ import annotations

from copy import deepcopy
import re

from ..memory import MAX_MEMORY_BYTES, MemoryImage
from ..unitspec import ParameterSpec, UnitSpec
from .neo_editor import NeoEditor, NeoProfile, NeoSnapshot
from .cli_support import InputError


INPUT_FORMAT = "cbus-offline-neo-editor-input-v1"
RESULT_FORMAT = "cbus-offline-neo-editor-result-v1"
_MAX_ITEMS = 4096
_MAX_OPERATIONS = 128
_MAX_TEXT = 1024 * 1024
_MAX_GRAPH_BYTES = 16 * 1024 * 1024
_PROFILE_FIELDS = ("source", "unit_type", "firmware", "catalogue", "serial", "network_state", "synthetic")
_PRESET_OPTIONS = ("key", "preset", "group", "block", "application", "timer_seconds", "expiry",
                   "recall1", "recall2", "indicator_block", "allow_shared_block")
_ACTION_FIELDS = {
    "edit-preset": (("options",), ()),
    "edit-micro-functions": (("key", "stages"), ()),
    "request-apply": ((), ()), "request-ok": ((), ()), "cancel-destination": ((), ()),
    "confirm-database": (("current",), ("destination", "entire_unit", "dlt_labels", "changed_only")),
    "cancel-editor": (("route",), ()),
}


class _InputFailure(InputError):
    def __init__(self, message, *, code="invalid_input", outcome="refused"):
        self.code, self.outcome = code, outcome
        super().__init__(message, code=code)


def _object(value, label, required, optional=()):
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise _InputFailure(label + " must be an object with string keys")
    missing, extra = set(required) - value.keys(), value.keys() - set(required) - set(optional)
    if missing:
        raise _InputFailure(label + " is missing: " + ", ".join(sorted(missing)))
    if extra:
        raise _InputFailure(label + " has unknown fields: " + ", ".join(sorted(extra)))
    return value


def _array(value, label, maximum=_MAX_ITEMS):
    if not isinstance(value, list) or len(value) > maximum:
        raise _InputFailure(f"{label} must be an array of at most {maximum} entries")
    return value


def _text(value, label, *, empty=False):
    if not isinstance(value, str) or (not value and not empty) or len(value) > _MAX_TEXT:
        raise _InputFailure(label + " must be bounded text" + ("" if empty else " and nonempty"))
    return value


def _integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise _InputFailure(f"{label} must be an integer in {low}..{high}")
    return value


def _boolean(value, label):
    if type(value) is not bool:
        raise _InputFailure(label + " must be true or false")
    return value


def _strings(value, label):
    if not isinstance(value, dict) or len(value) > _MAX_ITEMS:
        raise _InputFailure(label + " must be a bounded string mapping")
    return {_text(key, label + " key"): _text(item, label + "/" + key, empty=True)
            for key, item in value.items()}


def _values(value, label, depth=0):
    if depth > 32:
        raise _InputFailure(label + " exceeds the nesting limit")
    if value is None or type(value) in (bool, int):
        return value
    if isinstance(value, str):
        return _text(value, label, empty=True)
    if isinstance(value, list):
        return [_values(item, label, depth + 1) for item in _array(value, label)]
    if isinstance(value, dict) and len(value) <= _MAX_ITEMS:
        return {_text(key, label + " key"): _values(item, label + "/" + key, depth + 1)
                for key, item in value.items()}
    raise _InputFailure(label + " must contain bounded JSON strings, integers, booleans, null or containers")


def _profile(document):
    row = _object(document, "profile", _PROFILE_FIELDS)
    fields = {key: _text(row[key], "profile/" + key, empty=key == "serial")
              for key in _PROFILE_FIELDS if key != "synthetic"}
    fields["synthetic"] = _boolean(row["synthetic"], "profile/synthetic")
    return NeoProfile(**fields)


def _spec(document):
    row = _object(document, "spec", ("filename", "metadata", "sources", "parameters"))
    metadata = _strings(row["metadata"], "spec/metadata")
    if "Type" not in metadata:
        raise _InputFailure("spec/metadata must explicitly include Type")
    sources = tuple(_text(item, "spec/sources entry") for item in _array(row["sources"], "spec/sources"))
    if not sources or len(set(sources)) != len(sources):
        raise _InputFailure("spec/sources must be nonempty and contain no duplicate source identities")
    parameters = {}
    for index, parameter in enumerate(_array(row["parameters"], "spec/parameters"), 1):
        label = f"spec/parameters/{index}"
        parameter = _object(parameter, label, ("name", "type", "source", "fields", "tags"))
        name, kind, source = (_text(parameter[key], label + "/" + key) for key in ("name", "type", "source"))
        fields = _strings(parameter["fields"], label + "/fields")
        tags = tuple(_text(item, label + "/tags entry") for item in _array(parameter["tags"], label + "/tags"))
        if name in parameters:
            raise _InputFailure("Duplicate decoded parameter name: " + name)
        if source not in sources:
            raise _InputFailure(label + "/source is absent from the supplied sources")
        if fields.get("Name") != name or fields.get("Type") != kind:
            raise _InputFailure(label + " must agree with its explicit Name/Type fields")
        if kind not in ("int", "long", "bit", "string", "sixbit"):
            raise _InputFailure("Unsupported decoded parameter type", code="unsupported_schema", outcome="unsupported")
        parameters[name] = ParameterSpec(name, kind, source, fields, tags)
    if not parameters:
        raise _InputFailure("An explicit nonempty decoded specification is required")
    return UnitSpec(_text(row["filename"], "spec/filename"), metadata, sources, parameters)


def _snapshot(document):
    row = _object(document, "snapshot", ("values", "memory", "graph_hex", "existing_groups"))
    if not isinstance(row["values"], dict) or not row["values"]:
        raise _InputFailure("snapshot/values must be a nonempty complete caller PP mapping")
    values = _values(row["values"], "snapshot/values")
    memory = _object(row["memory"], "snapshot/memory", ("format", "bytes"))
    if memory["format"] != "cbus-sparse-memory-v1":
        raise _InputFailure("snapshot/memory requires cbus-sparse-memory-v1")
    if not isinstance(memory["bytes"], dict) or len(memory["bytes"]) > _MAX_ITEMS:
        raise _InputFailure("snapshot/memory/bytes must be a bounded address/byte object")
    cells = {}
    for address, value in memory["bytes"].items():
        if not isinstance(address, str) or re.fullmatch(r"0|[1-9][0-9]{0,7}", address) is None:
            raise _InputFailure("Memory addresses require canonical decimal JSON keys")
        cells[_integer(int(address), "Memory address", 0, MAX_MEMORY_BYTES - 1)] = _integer(value, "Memory byte", 0, 255)
    graph_hex = row["graph_hex"]
    if not isinstance(graph_hex, str) or not graph_hex:
        raise _InputFailure("snapshot/graph_hex must be nonempty hexadecimal text")
    if len(graph_hex) % 2 or len(graph_hex) > _MAX_GRAPH_BYTES * 2 or re.fullmatch(r"[0-9a-fA-F]+", graph_hex) is None:
        raise _InputFailure("snapshot/graph_hex must be an even, bounded hexadecimal byte string")
    groups = []
    for group in _array(row["existing_groups"], "snapshot/existing_groups"):
        group = _array(group, "group fact", 2)
        if len(group) != 2:
            raise _InputFailure("Each existing group fact requires application and group")
        groups.append((_integer(group[0], "Group application", 0, 255), _integer(group[1], "Group address", 0, 254)))
    return NeoSnapshot(values, MemoryImage(cells), bytes.fromhex(graph_hex), tuple(groups))


def _operation(document):
    if not isinstance(document, dict):
        raise _InputFailure("Each operation must be an object")
    action = _text(document.get("action"), "operation/action")
    if action not in _ACTION_FIELDS:
        raise _InputFailure("Unsupported Neo operation: " + action, code="unsupported_operation", outcome="unsupported")
    required, optional = _ACTION_FIELDS[action]
    row = _object(document, "operation", ("action", *required), optional)
    if action == "edit-preset":
        options = _object(row["options"], "edit-preset/options", ("key", "preset"), _PRESET_OPTIONS[2:])
        _integer(options["key"], "Key", 1, 4)
        _text(options["preset"], "Preset")
        for key, low, high in (("group", 0, 254), ("block", 1, 8), ("timer_seconds", 0, 65535),
                               ("recall1", 0, 255), ("recall2", 0, 255), ("indicator_block", 1, 8)):
            if key in options:
                _integer(options[key], key, low, high)
        for key in ("application", "expiry"):
            if key in options:
                _text(options[key], key)
        if "allow_shared_block" in options:
            _boolean(options["allow_shared_block"], "allow_shared_block")
    elif action == "edit-micro-functions":
        _integer(row["key"], "Key", 1, 4)
        stages = row["stages"]
        if not isinstance(stages, dict) or not stages or len(stages) > 4:
            raise _InputFailure("stages must contain one to four named micro-functions")
        for stage, value in stages.items():
            _text(stage, "Stage")
            if type(value) is int:
                _integer(value, "Micro-function", 0, 15)
            else:
                _text(value, "Micro-function")
    elif action == "confirm-database":
        current = row["current"]
        if not isinstance(current, dict) or len(current) != 1:
            raise _InputFailure("current requires exactly one explicit reference or full snapshot")
        if "reference" in current:
            if current["reference"] not in ("opening", "applied", "working"):
                raise _InputFailure("current/reference is opening, applied or working")
        elif "snapshot" in current:
            _snapshot(current["snapshot"])
        else:
            raise _InputFailure("current requires an explicit reference or snapshot")
        if "destination" in row:
            _text(row["destination"], "destination")
        for flag in ("entire_unit", "dlt_labels", "changed_only"):
            if flag in row:
                _boolean(row[flag], flag)
    elif action == "cancel-editor":
        _text(row["route"], "cancel-editor/route")
    return row


def _step(state, row):
    action = row["action"]
    if action == "edit-preset":
        return state.edit_preset(**row["options"])
    if action == "edit-micro-functions":
        return state.edit_micro_functions(key=row["key"], stages=row["stages"])
    if action == "confirm-database":
        current = row["current"]
        baseline = getattr(state, current["reference"]) if "reference" in current else _snapshot(current["snapshot"])
        options = {key: row[key] for key in ("destination", "entire_unit", "dlt_labels", "changed_only") if key in row}
        return state.confirm_database(current=baseline, **options)
    if action == "cancel-editor":
        return state.cancel_editor(route=row["route"])
    return getattr(state, action.replace("-", "_"))()


def _complete_state(state):
    if state is None:
        return None
    result = state.as_dict()
    for name in ("opening", "applied", "working"):
        result[name]["graph_hex"] = getattr(state, name).graph_bytes.hex()
    return result


def evaluate(document: dict, operation: str) -> dict:
    """Inspect descriptors or validate/plan an explicit local history.

    On refusal, stop at the first failing operation and retain the complete
    preceding local state. No input is loaded, manufactured, saved or retried.
    """
    result = {"format": RESULT_FORMAT, "workflow": "neo-editor", "operation": operation,
              "input_format": INPUT_FORMAT, "validation_passed": False, "outcome": "refused",
              "source_metadata": None, "operation_descriptors": [], "operations_executed": 0,
              "operation_semantics_validated": False, "final_state": None, "errors": [],
              "io_performed": False, "saved": False, "native_acceptance": False,
              "physical_acceptance": False, "external_persistence_verified": False}
    state, index = None, None
    try:
        if operation not in ("inspect", "validate", "plan"):
            raise _InputFailure("operation must be inspect, validate or plan", code="unsupported_operation", outcome="unsupported")
        document = _object(document, "input", ("format", "source_metadata", "profile", "spec", "snapshot", "operations"))
        if document["format"] != INPUT_FORMAT:
            raise _InputFailure("Unsupported Neo input format", code="unsupported_format", outcome="unsupported")
        metadata = _object(document["source_metadata"], "source_metadata", ("origin", "description"))
        result["source_metadata"] = {key: _text(value, "source_metadata/" + key) for key, value in metadata.items()}
        state = NeoEditor.open(_spec(document["spec"]), _profile(document["profile"]), _snapshot(document["snapshot"]))
        rows = _array(document["operations"], "operations", _MAX_OPERATIONS)
        for index, row in enumerate(rows, 1):
            row = _operation(row)
            result["operation_descriptors"].append({"index": index, "action": row["action"], "fields": sorted(row)})
            if operation != "inspect":
                state = _step(state, row)
                result["operations_executed"] += 1
        result["validation_passed"] = True
        result["operation_semantics_validated"] = operation != "inspect"
        result["outcome"] = "inspected" if operation == "inspect" else (
            "cancelled" if state.history[-1].action == "cancel_editor" else "prepared")
    except _InputFailure as error:
        if error.outcome == "refused":
            raise
        result["outcome"] = error.outcome
        result["errors"] = [{"code": error.code, "message": str(error), "operation_index": index}]
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        message = str(error)
        unsupported = any(word in message.lower() for word in ("unsupported", "only ", "outside", "requires original", "require original", "original capture", "shared block", "exact keym4", "only keym4"))
        result["outcome"] = "unsupported" if unsupported else "refused"
        result["errors"] = [{"code": "unsupported_profile_or_policy" if unsupported else "invalid_input_or_transition",
                             "message": message, "operation_index": index}]
    result["final_state"] = _complete_state(state)
    return deepcopy(result)
