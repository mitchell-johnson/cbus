"""Strict JSON-shaped inputs for preparation-only discovery/session models.

``evaluate`` accepts decoded data, never a filename. Every callback names an
already issued ``issue_id`` and supplies its complete captured token. Inspect
checks shapes/references only; validate and plan replay explicitly listed local
model actions. Neither operation schedules native controls or executes effects.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import math

from .cli_support import InputError
from .discovery_session import (
    LOCAL_PROFILE, MAX_EDITOR_BYTES, MAX_JOURNAL, MAX_ROWS,
    Callback, Context, DiscoveryAction, DiscoveryState, EditorSnapshot, Effect,
    OperationToken, Outcome, RowSpec, SessionAction, SessionState, Surface,
    UnsupportedContract, new_discovery, new_open_networks, new_session,
    reduce_discovery, reduce_open_networks, reduce_session,
)

INPUT_FORMAT = "cbus-offline-discovery-session-input-v1"
RESULT_FORMAT = "cbus-offline-discovery-session-result-v1"
MAX_ACTIONS = 256
MAX_GENERATION = 2**63 - 1
_CONTEXT_FIELDS = ("flow_id", "form_instance", "endpoint", "connection_generation",
                   "selection_generation", "project", "object_identity", "model_generation",
                   "form_generation")
_AUTHORITY = {
    "preparation_only": True,
    "native_manual_executed": False,
    "hardware_executed": False,
    "io_performed": False,
    "physical_io_executed": False,
    "runtime_executed": False,
    "native_compatible": False,
    "product_integrated": False,
}


def _object(value, required, optional=(), *, label="object") -> dict:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise InputError(f"{label} must be a JSON object")
    missing = set(required) - value.keys()
    unknown = value.keys() - set(required) - set(optional)
    if missing:
        raise InputError(f"{label} missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise InputError(f"{label} unknown fields: {', '.join(sorted(unknown))}")
    return value


def _text(value, *, label="text", nullable=False, empty=False, maximum=512):
    if value is None and nullable:
        return None
    if (type(value) is not str or len(value) > maximum or (not empty and not value)
            or any(ord(character) < 32 for character in value)):
        raise InputError(f"{label} must be bounded text without controls")
    return value


def _integer(value, *, label="integer", minimum=0, maximum=MAX_GENERATION):
    if type(value) is not int or not minimum <= value <= maximum:
        raise InputError(f"{label} must be an integer in {minimum}..{maximum}")
    return value


def _boolean(value, label):
    if type(value) is not bool:
        raise InputError(f"{label} must be a boolean")
    return value


def _array(value, *, label, maximum=MAX_ACTIONS):
    if type(value) is not list or len(value) > maximum:
        raise InputError(f"{label} must be a JSON array with at most {maximum} items")
    return value


def _hex(value):
    value = _text(value, label="payload_hex", empty=True, maximum=MAX_EDITOR_BYTES * 2)
    if len(value) % 2 or any(character not in "0123456789abcdefABCDEF" for character in value):
        raise InputError("payload_hex must contain complete hexadecimal byte pairs")
    return bytes.fromhex(value)


def _context(value) -> Context:
    value = _object(value, _CONTEXT_FIELDS, label="context")
    arguments = {}
    for key in ("flow_id", "form_instance", "endpoint"):
        arguments[key] = _text(value[key], label=key)
    for key in ("project", "object_identity"):
        arguments[key] = _text(value[key], label=key, nullable=True)
    for key in ("connection_generation", "selection_generation", "model_generation", "form_generation"):
        arguments[key] = _integer(value[key], label=key)
    return Context(**arguments)


def _surface(value) -> Surface:
    value = _text(value, label="surface")
    try:
        return Surface(value)
    except ValueError:
        raise UnsupportedContract("Unknown discovery/session surface is unsupported") from None


def _token(value) -> OperationToken:
    value = _object(value, ("context", "surface", "operation_id", "row_id", "attempt"), label="token")
    return OperationToken(_context(value["context"]), _surface(value["surface"]),
                          _text(value["operation_id"], label="operation_id"),
                          _text(value["row_id"], label="row_id"),
                          _integer(value["attempt"], label="attempt", minimum=1, maximum=MAX_ROWS))


def _outcome(value) -> Outcome:
    value = _object(value, ("kind", "detail", "terminal", "independent", "code"), label="outcome")
    code = value["code"]
    if code is not None:
        code = _integer(code, label="response code", minimum=100, maximum=599)
    return Outcome(_text(value["kind"], label="outcome kind"),
                   _text(value["detail"], label="detail", empty=True, maximum=4096),
                   _boolean(value["terminal"], "terminal"),
                   _boolean(value["independent"], "independent"), code)


def _row(value) -> RowSpec:
    value = _object(value, ("row_id", "endpoint", "project", "object_identity", "window_seconds"), label="row")
    window = value["window_seconds"]
    if type(window) not in (int, float) or not math.isfinite(window) or not 0 < window <= 300:
        raise InputError("window_seconds must be a finite number in 0..300 exclusive of zero")
    return RowSpec(_text(value["row_id"], label="row_id"), _text(value["endpoint"], label="endpoint"),
                   _text(value["project"], label="project", nullable=True),
                   _text(value["object_identity"], label="object_identity", nullable=True), window)


def _row_ids(value) -> tuple[str, ...]:
    return tuple(_text(item, label="row_id") for item in _array(value, label="row_ids", maximum=MAX_ROWS))


@dataclass(frozen=True)
class _Action:
    action: DiscoveryAction | SessionAction
    issue_id: str | None = None


def _action(value, surface: Surface) -> _Action:
    if type(value) is not dict:
        raise InputError("Each action must be a JSON object")
    kind = _text(value.get("kind"), label="action kind")
    shell = surface == Surface.SHELL
    if kind == "callback":
        value = _object(value, ("kind", "issue_id", "token", "outcome"), label="callback action")
        callback = Callback(_token(value["token"]), _outcome(value["outcome"]))
        action_type = SessionAction if shell else DiscoveryAction
        return _Action(action_type("callback", callback=callback), _text(value["issue_id"], label="issue_id"))
    if kind == "dispatch":
        target_field = "operation_id" if shell else "row_ids"
        value = _object(value, ("kind", "issue_id", target_field), label="dispatch action")
        issue_id = _text(value["issue_id"], label="issue_id")
        action = (SessionAction("dispatch", operation_id=_text(value["operation_id"], label="operation_id"))
                  if shell else DiscoveryAction("dispatch", _row_ids(value["row_ids"])))
        return _Action(action, issue_id)
    if shell:
        if kind == "select":
            value = _object(value, ("kind", "project", "object_identity", "model_generation"), label="select action")
            return _Action(SessionAction(kind, project=_text(value["project"], label="project"),
                                        object_identity=_text(value["object_identity"], label="object_identity"),
                                        model_generation=_integer(value["model_generation"], label="model_generation")))
        if kind == "schedule":
            value = _object(value, ("kind", "operation_id", "operation_kind"), label="schedule action")
            return _Action(SessionAction(kind, operation_id=_text(value["operation_id"], label="operation_id"),
                                        operation_kind=_text(value["operation_kind"], label="operation_kind")))
        if kind == "dirty_editor":
            value = _object(value, ("kind", "editor"), label="dirty_editor action")
            editor = _object(value["editor"], ("context", "payload_hex"), label="editor snapshot")
            return _Action(SessionAction(kind, editor=EditorSnapshot(_context(editor["context"]), _hex(editor["payload_hex"]))))
        if kind == "reconnect":
            value = _object(value, ("kind", "endpoint"), label="reconnect action")
            return _Action(SessionAction(kind, endpoint=_text(value["endpoint"], label="endpoint")))
        if kind in ("disconnect", "close"):
            _object(value, ("kind",), label="lifecycle action")
            return _Action(SessionAction(kind))
    else:
        if kind == "retry":
            value = _object(value, ("kind", "row_ids"), label="retry action")
            return _Action(DiscoveryAction(kind, _row_ids(value["row_ids"])))
        if kind in ("com_cancel", "cni_pause", "scan_cancel", "discover_project_cancel", "stop", "close"):
            _object(value, ("kind",), label="lifecycle action")
            return _Action(DiscoveryAction(kind))
    raise UnsupportedContract("Unverified or wrong-family action; native schedules and Resume are unsupported")


def _encode(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: _encode(getattr(value, field.name)) for field in fields(value)}
    if type(value) is bytes:
        return {"hex": value.hex(), "byte_count": len(value)}
    if type(value) in (tuple, list):
        return [_encode(item) for item in value]
    if type(value) is dict:
        return {key: _encode(item) for key, item in value.items()}
    return value


def _result(operation: str, *, passed: bool, outcome: str, summary=None, state=None,
            issued=(), observations=(), history=(), error=None):
    summary = dict(summary or {})
    if state is not None:
        members = state.operations if isinstance(state, SessionState) else state.rows
        summary["phase_counts"] = {phase: sum(item.phase == phase for item in members)
                                   for phase in sorted({item.phase for item in members})}
        summary["evidence_incomplete"] = state.evidence_incomplete
        summary["dropped_callbacks"] = state.dropped_callbacks
        summary["suppressed_callbacks_retained"] = sum(not record.presented for record in state.journal)
    return {
        "format": RESULT_FORMAT,
        "workflow": "discovery-session",
        "operation": operation,
        "validation_passed": passed,
        "outcome": outcome,
        "summary": summary,
        "state": _encode(state),
        "issued_operations": _encode(issued),
        "effects": [_encode(entry["effect"]) for entry in issued],
        "observations": _encode(observations),
        "action_history": _encode(history),
        "error": error,
        "observation_assertions_source": "user_supplied_synthetic",
        "native_contract": "DN/CL scheduling, Pause continuation and Retry eligibility remain unverified",
        **_AUTHORITY,
    }


def _state_outcome(state: DiscoveryState | SessionState) -> str:
    if state.evidence_incomplete:
        return "uncertain"
    if isinstance(state, SessionState):
        if any(op.phase == "unknown_after_dispatch" or (op.terminal and op.terminal.kind in ("transport_error", "unknown_after_dispatch"))
               for op in state.operations):
            return "uncertain"
        if state.closed or not state.connected or any(op.phase == "cancelled_before_dispatch" for op in state.operations):
            return "cancelled"
        if any(op.terminal and op.terminal.kind == "refused" for op in state.operations):
            return "refused"
    else:
        if any(row.phase == "unknown_after_dispatch" for row in state.rows):
            return "uncertain"
        if state.stopped or state.closed:
            return "cancelled"
        if any(row.phase in ("refused", "unreachable") for row in state.rows):
            return "refused"
    return "prepared"


def evaluate(document: dict, operation: str) -> dict:
    """Parse or replay an explicit, bounded synthetic preparation document.

    Structural errors raise shared InputError. Unsupported model contracts and
    locally refused transitions produce an inspectable preparation result,
    retaining the prior state and issued requests without execution authority.
    """
    if operation not in ("inspect", "validate", "plan"):
        raise InputError("operation must be inspect, validate or plan")
    summary = {}
    state = None
    issued = []
    observations = []
    history = []
    try:
        document = _object(document, ("format", "surface", "context", "actions"),
                           ("profile", "rows", "journal_limit", "operation_limit"), label="document")
        if document["format"] != INPUT_FORMAT:
            raise InputError(f"format must be {INPUT_FORMAT}")
        surface = _surface(document["surface"])
        context = _context(document["context"])
        profile = _text(document.get("profile", LOCAL_PROFILE), label="profile")
        if profile != LOCAL_PROFILE:
            raise UnsupportedContract("Unknown/native profile is unsupported; only the named local safety profile is admitted")
        journal_limit = _integer(document.get("journal_limit", 256), label="journal_limit", minimum=1, maximum=MAX_JOURNAL)
        actions = tuple(_action(item, surface) for item in _array(document["actions"], label="actions"))
        if surface == Surface.SHELL:
            if "rows" in document:
                raise InputError("Shell input must not contain discovery rows")
            rows = ()
            operation_limit = _integer(document.get("operation_limit", 64), label="operation_limit", minimum=1, maximum=MAX_ROWS)
        else:
            if "operation_limit" in document:
                raise InputError("operation_limit is only admitted for shell sessions")
            if "rows" not in document:
                raise InputError("Discovery and opening input requires rows")
            rows = tuple(_row(item) for item in _array(document["rows"], label="rows", maximum=16 if surface == Surface.CNI_SCAN else MAX_ROWS))
            operation_limit = None
        summary = {"surface": surface.value, "context": _encode(context), "profile": profile,
                   "row_count": len(rows), "action_count": len(actions), "journal_limit": journal_limit,
                   "operation_limit": operation_limit, "timeline_replayed": operation != "inspect"}
        referenced = set()
        for parsed in actions:
            if parsed.action.kind == "dispatch":
                if parsed.issue_id in referenced:
                    raise InputError("Dispatch issue_id values must be unique")
                referenced.add(parsed.issue_id)
            elif parsed.action.kind == "callback" and parsed.issue_id not in referenced:
                raise InputError("Callback issue_id must name an earlier dispatch action")
        if surface == Surface.SHELL:
            state = new_session(context, profile=profile, operation_limit=operation_limit, journal_limit=journal_limit)
            reducer = reduce_session
        elif surface == Surface.OPEN_NETWORKS:
            state = new_open_networks(context, rows, profile=profile, journal_limit=journal_limit)
            reducer = reduce_open_networks
        else:
            state = new_discovery(context, surface, rows, profile=profile, journal_limit=journal_limit)
            reducer = reduce_discovery
        if operation == "inspect":
            summary["parsed_actions"] = [_encode(parsed) for parsed in actions]
            summary["rows"] = _encode(rows)
            return _result(operation, passed=True, outcome="inspected", summary=summary, state=state)
        by_issue = {}
        for index, parsed in enumerate(actions):
            action = parsed.action
            if action.kind == "callback":
                effect = by_issue.get(parsed.issue_id)
                if effect is None:
                    raise InputError("Callback references a dispatch that did not issue a symbolic operation")
                if action.callback.token != effect.token:
                    raise InputError("Callback token must exactly retain its previously issued operation identity")
            previous = state
            transition = reducer(state, action)
            state = transition.state
            if action.kind == "dispatch":
                if len(transition.effects) != 1:
                    raise InputError("Each dispatch must issue exactly one symbolic operation")
                effect = transition.effects[0]
                by_issue[parsed.issue_id] = effect
                issued.append({"issue_id": parsed.issue_id, "action_index": index, "effect": effect})
            if action.kind == "callback":
                retained = state.journal[len(previous.journal):]
                observations.append({"issue_id": parsed.issue_id, "action_index": index,
                                     "callback": action.callback, "retained_records": retained,
                                     "evidence_incomplete": state.evidence_incomplete,
                                     "dropped_callbacks": state.dropped_callbacks})
            history.append({"action_index": index, "action": action, "issue_id": parsed.issue_id,
                            "effects": transition.effects, "context_after": state.context})
        return _result(operation, passed=True, outcome=_state_outcome(state), summary=summary,
                       state=state, issued=issued, observations=observations, history=history)
    except InputError:
        raise
    except UnsupportedContract as error:
        return _result(operation, passed=False, outcome="unsupported", summary=summary, state=state,
                       issued=issued, observations=observations, history=history,
                       error={"code": "unsupported_contract", "message": str(error), "action_index": len(history)})
    except ValueError as error:
        if state is None:
            raise InputError(str(error)) from None
        return _result(operation, passed=False, outcome="refused", summary=summary, state=state,
                       issued=issued, observations=observations, history=history,
                       error={"code": "refused_transition", "message": str(error), "action_index": len(history)})
