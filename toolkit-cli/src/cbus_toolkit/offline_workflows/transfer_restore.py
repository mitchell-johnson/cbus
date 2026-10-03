"""Independent, zero-I/O transfer and restore preparation surfaces.

These reports freeze caller-supplied identities and choices. They never compile
queue commands, programming bytes, archive mutations, or an execution adapter.
Original direction/eligibility, clear/reassign, Replace/Rename and batch behavior
still require original capture. Quick progress and restore results are supplied
records, not evidence that a decision planner executed anything.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Mapping

from ..label_transfer_plan import plan_transfer as _label_plan
from ..native import _project

ACTIONS = frozenset(("clear", "add-only", "programming-only", "add-and-transfer"))
NAME_PROFILE = "cbus-toolkit-project-name-v1"
_LIMIT = 4096


def _text(value, label, *, optional=False):
    if optional and value is None:
        return value
    if type(value) is not str or not value or len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(label + " must be a nonempty bounded string without controls")
    return value


def _sha(value, label, *, optional=False):
    if optional and value is None:
        return value
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(label + " must be a lowercase SHA-256 digest")
    return value


def _tuple(value, kind, label):
    if not isinstance(value, (tuple, list)) or len(value) > _LIMIT or any(type(v) is not kind for v in value):
        raise ValueError(label + " must be a bounded sequence of " + kind.__name__)
    return tuple(value)


def _strings(value, label):
    result = _tuple(value, str, label)
    for item in result:
        _text(item, label)
    if len(set(result)) != len(result):
        raise ValueError("Duplicate " + label)
    return result


def _name(value):
    if type(value) is not str:
        raise ValueError("Project name must be a string")
    return _project(value)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _hash(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _fields(document, fields):
    if not isinstance(document, Mapping) or set(document) != set(fields):
        raise ValueError("Invalid preparation record fields")
    return {name: document[name] for name in fields}


def _issue(code, **facts):
    return {"code": code, **facts}


@dataclass(frozen=True, init=False)
class _Report:
    # A canonical JSON string is deeply immutable; as_dict returns fresh leaves.
    _document: str

    def __init__(self, *args, **kwargs):
        raise TypeError("Use a preparation function or from_dict to construct reports")

    def as_dict(self):
        return json.loads(self._document)

    @classmethod
    def from_dict(cls, document):
        if not isinstance(document, Mapping):
            raise ValueError("Preparation report must be a mapping")
        rebuilt = _rebuild(document)
        if type(rebuilt) is not cls or _canonical(document) != rebuilt._document:
            raise ValueError("Preparation report differs from its recomputed choices and bindings")
        return rebuilt


def _report(kind, surface, bindings, history, outcome, issues=(), *, intent_frozen=False, **facts):
    document = {
        "format": "cbus-offline-" + surface + "-v1",
        "surface": surface, "bindings": bindings, "history": history,
        "binding_sha256": _hash(bindings), "outcome": outcome,
        "issues": list(issues), "intent_frozen": intent_frozen,
        "preparation_only": True, "execution_admitted": False,
        "original_workflow_verified": False, "native_mutations": 0,
        "queue_commands": [], "automatic_replay_authorized": False, **facts,
    }
    document["report_sha256"] = _hash(document)
    report = object.__new__(kind)
    object.__setattr__(report, "_document", _canonical(document))
    return report


@dataclass(frozen=True)
class TransferRow:
    row_id: str
    source_identity: str
    source_snapshot_sha256: str
    destination_identity: str | None = None
    destination_snapshot_sha256: str | None = None
    staged_data_sha256: str | None = None
    source_address: str | None = None
    serial: str | None = None
    unit_type: str | None = None
    firmware: str | None = None
    route: tuple[str, ...] = ()
    destination_state: str = "unknown"
    action: str = "clear"

    def __post_init__(self):
        for field in ("row_id", "source_identity"):
            _text(getattr(self, field), field)
        for field in ("destination_identity", "source_address", "serial", "unit_type", "firmware"):
            _text(getattr(self, field), field, optional=True)
        _sha(self.source_snapshot_sha256, "source snapshot")
        _sha(self.destination_snapshot_sha256, "destination snapshot", optional=True)
        _sha(self.staged_data_sha256, "staged data", optional=True)
        object.__setattr__(self, "route", _tuple(self.route, str, "route identities"))
        for identity in self.route:
            _text(identity, "route identity")
        if self.destination_state not in ("present", "absent", "mismatched", "unknown"):
            raise ValueError("Unknown destination observation")
        if self.action not in ACTIONS:
            raise ValueError("Unknown transfer action")

    @classmethod
    def from_dict(cls, value):
        return cls(**_fields(value, cls.__dataclass_fields__))

    def as_dict(self):
        result = asdict(self)
        result["route"] = list(self.route)
        return result


@dataclass(frozen=True)
class AdvancedTransferEvent:
    kind: str
    row_ids: tuple[str, ...] = ()
    action: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "row_ids", _strings(self.row_ids, "event row IDs"))
        if self.kind not in ("choose-action", "clear-actions", "accept", "cancel"):
            raise ValueError("Event does not belong to the advanced transfer surface")
        if self.kind in ("accept", "cancel"):
            if self.row_ids or self.action is not None:
                raise ValueError("Terminal advanced choices take no row/action payload")
        elif not self.row_ids:
            raise ValueError("Advanced action choice requires explicit row IDs")
        elif self.kind == "choose-action" and self.action not in ACTIONS:
            raise ValueError("Unknown transfer action")
        elif self.kind == "clear-actions" and self.action is not None:
            raise ValueError("Clear-actions takes no action payload")

    @classmethod
    def from_dict(cls, value):
        return cls(**_fields(value, cls.__dataclass_fields__))

    def as_dict(self):
        return {"kind": self.kind, "row_ids": list(self.row_ids), "action": self.action}


@dataclass(frozen=True, init=False)
class AdvancedTransferPlan(_Report):
    """Frozen advanced intent; no direction or quick-form history is inferred."""


def prepare_advanced_transfer(rows, history=()):
    rows = _tuple(rows, TransferRow, "transfer rows")
    history = _tuple(history, AdvancedTransferEvent, "advanced history")
    ids = tuple(row.row_id for row in rows)
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate transfer row ID")
    if len({row.source_identity for row in rows}) != len(rows):
        raise ValueError("Ambiguous duplicate transfer source identity")
    actions = {row.row_id: row.action for row in rows}
    terminal = None
    for event in history:
        if terminal is not None:
            raise ValueError("Advanced intent is frozen after accept or cancel")
        if any(row_id not in actions for row_id in event.row_ids):
            raise ValueError("Advanced event references an unknown row")
        if event.kind in ("accept", "cancel"):
            terminal = event.kind
        else:
            for row_id in event.row_ids:
                actions[row_id] = "clear" if event.kind == "clear-actions" else event.action
    active = [row for row in rows if actions[row.row_id] != "clear"]
    destinations = [row.destination_identity for row in active if row.destination_identity is not None]
    if len(set(destinations)) != len(destinations):
        raise ValueError("Conflicting duplicate transfer destination identity")
    issues = []
    for row in active:
        if row.destination_identity is None:
            issues.append(_issue("destination_identity_required", row_id=row.row_id))
        if actions[row.row_id] in ("programming-only", "add-and-transfer") and row.staged_data_sha256 is None:
            issues.append(_issue("staged_data_binding_required", row_id=row.row_id))
        issues.append(_issue("original_capture_required", row_id=row.row_id,
                             contract="action_eligibility_and_destination_outcome"))
    if len({actions[row.row_id] for row in active}) > 1:
        issues.append(_issue("original_capture_required", contract="mixed_row_eligibility"))
    if terminal == "cancel":
        outcome = "confirmed_noop"
    elif not rows:
        outcome = "not_applicable"
    elif not active:
        outcome = "confirmed_noop"
    elif any(issue["code"] != "original_capture_required" for issue in issues):
        outcome = "uncertain"
    else:
        outcome = "unsupported"
    bindings = {"rows": [row.as_dict() for row in rows]}
    return _report(AdvancedTransferPlan, "advanced-transfer", bindings,
                   [event.as_dict() for event in history], outcome, issues,
                   intent_frozen=terminal == "accept",
                   terminal_choice=terminal,
                   selected_actions=[{"row_id": row.row_id, "action": actions[row.row_id]} for row in rows],
                   clear_reassign_policy="local_intent_only_preserves_source_and_staged_bindings",
                   clear_reassign_original_verified=False,
                   direction_binding=None, quick_invocation_link_verified=False)


@dataclass(frozen=True, init=False)
class TransferDirectionPlan(_Report):
    """Independent rdbNetwork/rdbDatabase choices with no direction mapping."""


def prepare_transfer_direction(choice=None, *, decision="review", context_sha256=None):
    if choice not in (None, "rdbNetwork", "rdbDatabase"):
        raise ValueError("Direction choice must name the retained radio control")
    if decision not in ("review", "accept", "cancel"):
        raise ValueError("Unknown direction decision")
    _sha(context_sha256, "direction context", optional=True)
    issues = [_issue("original_capture_required", contract="radio_control_direction_and_invocation_mapping")]
    outcome = "confirmed_noop" if decision == "cancel" else "uncertain" if choice is None else "unsupported"
    return _report(TransferDirectionPlan, "transfer-direction",
                   {"choice": choice, "context_sha256": context_sha256},
                   [{"decision": decision}], outcome, issues,
                   intent_frozen=decision == "accept" and choice is not None,
                   direction=None, advanced_invocation_link_verified=False)


@dataclass(frozen=True)
class QuickTransferEvent:
    kind: str
    row_id: str | None = None
    percentage: int | None = None
    detail: str | None = None

    def __post_init__(self):
        if self.kind not in ("pause", "resume", "close", "progress", "completed", "failed", "uncertain"):
            raise ValueError("Event does not belong to the quick transfer surface")
        _text(self.row_id, "quick row ID", optional=True)
        _text(self.detail, "quick detail", optional=True)
        if self.percentage is not None and (type(self.percentage) is not int or not 0 <= self.percentage <= 100):
            raise ValueError("Percentage must be an integer in 0..100")
        if self.kind in ("pause", "resume", "close"):
            if self.row_id is not None or self.percentage is not None or self.detail is not None:
                raise ValueError("Quick form choices take no row payload")
        elif self.row_id is None:
            raise ValueError("Quick observation requires a row ID")

    @classmethod
    def from_dict(cls, value):
        return cls(**_fields(value, cls.__dataclass_fields__))

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True, init=False)
class QuickTransferHistory(_Report):
    """Separate caller-recorded observations, without pause/resume/retry commands."""


def record_quick_transfer(row_ids, history=(), *, attempt_id, context_sha256=None,
                          previous_attempt_sha256=None):
    row_ids = _strings(row_ids, "quick row IDs")
    history = _tuple(history, QuickTransferEvent, "quick history")
    _text(attempt_id, "quick attempt ID")
    _sha(context_sha256, "quick context", optional=True)
    _sha(previous_attempt_sha256, "previous quick attempt", optional=True)
    observations = {row_id: {"row_id": row_id, "status": "unobserved", "percentage": None, "detail": None} for row_id in row_ids}
    closed = False
    for event in history:
        if closed:
            raise ValueError("Quick history is frozen after Close")
        if event.kind == "close":
            closed = True
        elif event.row_id is not None:
            if event.row_id not in observations:
                raise ValueError("Quick observation references an unknown row")
            current = observations[event.row_id]
            if current["status"] in ("completed", "failed", "uncertain"):
                raise ValueError("Terminal quick row requires a separate recovery attempt")
            if event.percentage is not None:
                current["percentage"] = event.percentage
            current["status"] = "progress" if event.kind == "progress" else event.kind
            current["detail"] = event.detail
    statuses = {row["status"] for row in observations.values()}
    outcome = "not_applicable" if not row_ids else "uncertain" if statuses & {"failed", "uncertain"} else "prepared"
    return _report(QuickTransferHistory, "quick-transfer",
                   {"row_ids": list(row_ids), "attempt_id": attempt_id,
                    "context_sha256": context_sha256, "previous_attempt_sha256": previous_attempt_sha256},
                   [event.as_dict() for event in history], outcome,
                   [_issue("original_capture_required", contract="quick_controls_and_native_queue_linkage")],
                   observations=list(observations.values()), closed=closed,
                   observation_provenance="caller_supplied", native_execution_verified=False,
                   advanced_invocation_link_verified=False, recovery_is_separate_attempt=previous_attempt_sha256 is not None)


@dataclass(frozen=True)
class RestoreProject:
    row_id: str
    member_identity: str
    source_project: str
    source_snapshot_sha256: str
    selected: bool = True
    proposed_name: str | None = None

    def __post_init__(self):
        _text(self.row_id, "restore row ID")
        _text(self.member_identity, "archive member identity")
        _name(self.source_project)
        _sha(self.source_snapshot_sha256, "archive project snapshot")
        if type(self.selected) is not bool:
            raise ValueError("Restore selection must be boolean")
        if self.proposed_name is not None:
            _name(self.proposed_name)

    @classmethod
    def from_dict(cls, value):
        return cls(**_fields(value, cls.__dataclass_fields__))

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class RestoreEvent:
    kind: str
    row_ids: tuple[str, ...] = ()
    policy: str | None = None
    proposed_name: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "row_ids", _strings(self.row_ids, "restore event row IDs"))
        if self.kind not in ("select", "deselect", "select-all", "select-none", "choose-policy", "propose-name", "accept", "cancel"):
            raise ValueError("Event does not belong to the restore decision surface")
        if self.kind in ("select", "deselect"):
            if not self.row_ids or self.policy is not None or self.proposed_name is not None:
                raise ValueError("Restore selection requires only explicit row IDs")
        elif self.kind == "choose-policy":
            if self.row_ids or self.policy not in ("replace", "rename") or self.proposed_name is not None:
                raise ValueError("Restore policy requires Replace or Rename without row payload")
        elif self.kind == "propose-name":
            if len(self.row_ids) != 1 or self.policy is not None:
                raise ValueError("Proposed restore name requires one row")
            if self.proposed_name is not None:
                _name(self.proposed_name)
        elif self.row_ids or self.policy is not None or self.proposed_name is not None:
            raise ValueError("Restore form choice takes no row/policy/name payload")

    @classmethod
    def from_dict(cls, value):
        return cls(**_fields(value, cls.__dataclass_fields__))

    def as_dict(self):
        return {"kind": self.kind, "row_ids": list(self.row_ids), "policy": self.policy, "proposed_name": self.proposed_name}


@dataclass(frozen=True, init=False)
class RestoreDecisionPlan(_Report):
    """Restore selection/conflict intention, without a replacement primitive."""


def _restore_projects(projects):
    projects = _tuple(projects, RestoreProject, "restore projects")
    if len({p.row_id for p in projects}) != len(projects):
        raise ValueError("Duplicate restore row ID")
    if len({p.member_identity for p in projects}) != len(projects):
        raise ValueError("Ambiguous duplicate archive member identity")
    return projects


def prepare_restore(projects, *, archive_sha256, destination_snapshot_sha256,
                    destination_names=(), history=(), name_profile=NAME_PROFILE):
    projects = _restore_projects(projects)
    history = _tuple(history, RestoreEvent, "restore history")
    _sha(archive_sha256, "archive")
    _sha(destination_snapshot_sha256, "destination snapshot")
    destination_names = _strings(destination_names, "destination project names")
    for name in destination_names:
        _name(name)
    # A conservative admission check; it does not assert native case semantics.
    destination_keys = {name.upper() for name in destination_names}
    if len(destination_keys) != len(destination_names):
        raise ValueError("Ambiguous destination names under the preparation name profile")
    _text(name_profile, "name profile")
    selection = {p.row_id: p.selected for p in projects}
    proposals = {p.row_id: p.proposed_name for p in projects}
    policy = terminal = None
    for event in history:
        if terminal is not None:
            raise ValueError("Restore decision is frozen after accept or cancel")
        if any(row_id not in selection for row_id in event.row_ids):
            raise ValueError("Restore event references an unknown row")
        if event.kind in ("accept", "cancel"):
            terminal = event.kind
        elif event.kind == "choose-policy":
            policy = event.policy
        elif event.kind == "propose-name":
            proposals[event.row_ids[0]] = event.proposed_name
        elif event.kind in ("select-all", "select-none"):
            selection = {row_id: event.kind == "select-all" for row_id in selection}
        else:
            for row_id in event.row_ids:
                selection[row_id] = event.kind == "select"
    decisions, issues, unresolved = [], [], False
    targets = []
    for project in projects:
        if not selection[project.row_id]:
            continue
        conflict = project.source_project.upper() in destination_keys
        target = project.source_project
        if conflict:
            if policy is None:
                target = None
                issues.append(_issue("conflict_policy_required", row_id=project.row_id))
                unresolved = True
            elif policy == "rename":
                target = proposals[project.row_id]
                if target is None:
                    issues.append(_issue("explicit_rename_name_required", row_id=project.row_id))
                    unresolved = True
                elif target.upper() in destination_keys:
                    issues.append(_issue("rename_destination_exists", row_id=project.row_id))
                    unresolved = True
            issues.append(_issue("original_capture_required", row_id=project.row_id, contract="restore_" + str(policy)))
        if target is not None:
            targets.append(target.upper())
        decisions.append({"row_id": project.row_id, "member_identity": project.member_identity,
                          "source_project": project.source_project, "conflict": conflict,
                          "policy": policy if conflict else None, "proposed_name": proposals[project.row_id],
                          "destination_name": target})
    if len(set(targets)) != len(targets):
        issues.append(_issue("duplicate_destination_names"))
        unresolved = True
    if name_profile != NAME_PROFILE:
        issues.append(_issue("unsupported_name_profile", requested=name_profile))
        unresolved = True
    if len(decisions) > 1:
        issues.append(_issue("original_capture_required", contract="restore_batch_order_failure_and_atomicity"))
    if decisions and not any(issue["code"] == "original_capture_required" for issue in issues):
        issues.append(_issue("original_capture_required", contract="restore_decision_execution_linkage"))
    if terminal == "cancel":
        outcome = "confirmed_noop"
    elif not decisions:
        outcome = "confirmed_noop" if terminal == "accept" else "not_applicable"
    elif unresolved:
        outcome = "unsupported" if name_profile != NAME_PROFILE else "uncertain"
    else:
        outcome = "unsupported"
    bindings = {"projects": [p.as_dict() for p in projects], "archive_sha256": archive_sha256,
                "destination_snapshot_sha256": destination_snapshot_sha256,
                "destination_names": list(destination_names), "name_profile": name_profile}
    return _report(RestoreDecisionPlan, "restore-decision", bindings,
                   [event.as_dict() for event in history], outcome, issues,
                   intent_frozen=terminal == "accept" and not unresolved,
                   terminal_choice=terminal, conflict_policy=policy,
                   selection=[{"row_id": p.row_id, "selected": selection[p.row_id]} for p in projects],
                   proposed_names=[{"row_id": p.row_id, "name": proposals[p.row_id]} for p in projects],
                   decisions=decisions, automatic_rename_rule=None,
                   name_comparison="conservative_uppercase_preparation_admission_only",
                   replace_primitive=None, batch_atomicity=None, results_invocation_link_verified=False)


@dataclass(frozen=True)
class RestoreResult:
    row_id: str
    status: str
    detail: str | None = None

    def __post_init__(self):
        _text(self.row_id, "restore result row ID")
        _text(self.detail, "restore result detail", optional=True)
        if self.status not in ("completed", "failed", "uncertain", "not-attempted"):
            raise ValueError("Unknown supplied restore result")

    @classmethod
    def from_dict(cls, value):
        return cls(**_fields(value, cls.__dataclass_fields__))

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True, init=False)
class RestoreResultsHistory(_Report):
    """Separate per-project records without rollback, batch or retry inference."""


def record_restore_results(projects, results=(), *, attempt_id, decision_sha256=None,
                           previous_attempt_sha256=None):
    projects = _restore_projects(projects)
    results = _tuple(results, RestoreResult, "restore results")
    _text(attempt_id, "restore attempt ID")
    _sha(decision_sha256, "restore decision", optional=True)
    _sha(previous_attempt_sha256, "previous restore attempt", optional=True)
    if len({result.row_id for result in results}) != len(results):
        raise ValueError("Duplicate restore result row ID")
    rows = {p.row_id: p for p in projects}
    for result in results:
        if result.row_id not in rows:
            raise ValueError("Restore result references an unknown project")
        if not rows[result.row_id].selected and result.status != "not-attempted":
            raise ValueError("An unselected restore row cannot have an attempted result")
    observed = {result.row_id: result.as_dict() for result in results}
    observations = [observed.get(p.row_id, {"row_id": p.row_id, "status": "unobserved" if p.selected else "not-attempted", "detail": None}) for p in projects]
    outcome = "not_applicable" if not any(p.selected for p in projects) else "uncertain" if any(r["status"] in ("failed", "uncertain") for r in observations) else "prepared"
    return _report(RestoreResultsHistory, "restore-results",
                   {"projects": [p.as_dict() for p in projects], "attempt_id": attempt_id,
                    "decision_sha256": decision_sha256, "previous_attempt_sha256": previous_attempt_sha256},
                   [result.as_dict() for result in results], outcome,
                   [_issue("original_capture_required", contract="restore_results_and_failure_recovery")],
                   observations=observations, observation_provenance="caller_supplied",
                   native_execution_verified=False, rollback_verified=False,
                   batch_atomicity=None, recovery_is_separate_attempt=previous_attempt_sha256 is not None)


@dataclass(frozen=True, init=False)
class LabelTransferPreparation(_Report):
    """Existing structural slot allocation, never generic unit programming."""


def prepare_label_transfer(labels, capacity, extra=None):
    # Materialize once so generator inputs and bindings describe the same rows.
    if isinstance(labels, (str, bytes)):
        raise TypeError("labels must be a sequence of dicts")
    labels = list(labels)
    if len(labels) > _LIMIT:
        raise ValueError("Too many labels")
    plan = _label_plan(labels, capacity, extra)
    bindings = json.loads(_canonical({"labels": labels, "capacity": capacity, "extra": plan.echo}))
    outcome = "confirmed_noop" if not labels else "uncertain" if plan.escalated else "prepared"
    return _report(LabelTransferPreparation, "label-transfer", bindings, [], outcome,
                   [_issue("original_capture_required", contract="device_label_storage_encoding_and_display")],
                   assignments=[list(row) for row in plan.assignments], escalated=list(plan.escalated),
                   behavioral_comparison=plan.behavioral_comparison,
                   planner="cbus_toolkit.label_transfer_plan.plan_transfer")


def _rebuild(document):
    """Recompute serialized reports; caller authority fields never admit execution."""
    try:
        surface, binding, history = document["surface"], document["bindings"], document["history"]
        if surface == "advanced-transfer":
            return prepare_advanced_transfer([TransferRow.from_dict(row) for row in binding["rows"]],
                                             [AdvancedTransferEvent.from_dict(event) for event in history])
        if surface == "transfer-direction":
            if len(history) != 1:
                raise ValueError("Invalid direction history")
            return prepare_transfer_direction(binding["choice"], decision=history[0]["decision"], context_sha256=binding["context_sha256"])
        if surface == "quick-transfer":
            return record_quick_transfer(binding["row_ids"], [QuickTransferEvent.from_dict(event) for event in history],
                                         attempt_id=binding["attempt_id"], context_sha256=binding["context_sha256"],
                                         previous_attempt_sha256=binding["previous_attempt_sha256"])
        if surface == "restore-decision":
            return prepare_restore([RestoreProject.from_dict(row) for row in binding["projects"]],
                                   archive_sha256=binding["archive_sha256"], destination_snapshot_sha256=binding["destination_snapshot_sha256"],
                                   destination_names=binding["destination_names"], name_profile=binding["name_profile"],
                                   history=[RestoreEvent.from_dict(event) for event in history])
        if surface == "restore-results":
            return record_restore_results([RestoreProject.from_dict(row) for row in binding["projects"]],
                                          [RestoreResult.from_dict(event) for event in history], attempt_id=binding["attempt_id"],
                                          decision_sha256=binding["decision_sha256"], previous_attempt_sha256=binding["previous_attempt_sha256"])
        if surface == "label-transfer":
            return prepare_label_transfer(binding["labels"], binding["capacity"], binding["extra"])
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Malformed preparation report") from error
    raise ValueError("Unsupported preparation surface")
