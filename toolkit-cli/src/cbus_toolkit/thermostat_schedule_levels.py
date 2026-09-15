"""Retained, provider-scoped thermostat CreateLevels model.

This models the observed normal flow and stops at a failed supplied save
callback. It does not execute Delphi exception unwinding, UI selection, native
storage, or server locks. Address and Value are independent fields.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable
from weakref import WeakKeyDictionary


SCHEDULE_ACTIONS = ("Enable", "Disable", "Overrd")


def _integer(value: object, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} through {high}")
    return value


def _text(value: object, limit: int, name: str, *, empty: bool = True) -> str:
    if type(value) is not str or len(value) > limit or "\0" in value or not empty and not value:
        raise ValueError(f"{name} must be bounded text without NUL")
    try:
        value.encode("utf-8", "strict")
    except UnicodeError as error:
        raise ValueError(f"{name} must contain valid Unicode") from error
    return value


def level_to_zones(address: int) -> str:
    """Original literal zone label for scheduling addresses 1 through 31."""
    _integer(address, 1, 31, "Scheduling address")
    names = [name for bit, name in ((1, "unsw"), (2, "1"), (4, "2"), (8, "3"), (16, "4")) if address & bit]
    return ("Zone:" if len(names) == 1 else "Zones:") + ",".join(names)


@dataclass(frozen=True)
class ScheduleLevel:
    identity: str
    address: int
    value: int
    tag: str

    def as_dict(self) -> dict:
        return {"identity": self.identity, "address": self.address, "value": self.value, "tag": self.tag}


@dataclass(frozen=True, eq=False)
class ScheduleLevelsState:
    levels: tuple[ScheduleLevel, ...]
    save_lock: int
    pending_save: bool
    level_save_attempts: int = 0
    level_save_completed: int = 0
    storage_attempts: int = 0
    storage_completed: int = 0
    project_requests: int = 0

    def as_dict(self) -> dict:
        return {"levels": [x.as_dict() for x in self.levels], "save_lock": self.save_lock,
                "pending_save": self.pending_save, "level_save_attempts": self.level_save_attempts,
                "level_save_completed": self.level_save_completed, "storage_attempts": self.storage_attempts,
                "storage_completed": self.storage_completed, "project_requests": self.project_requests}


@dataclass(frozen=True)
class ScheduleLevelsEvent:
    event: str
    state: ScheduleLevelsState
    level: ScheduleLevel | None = None
    address: int | None = None
    create: bool | None = None

    def as_dict(self) -> dict:
        result = {"event": self.event, "state": self.state.as_dict()}
        if self.level is not None:
            result["level"] = self.level.as_dict()
        if self.address is not None:
            result["address"] = self.address
        if self.create is not None:
            result["create"] = self.create
        return result


@dataclass(frozen=True)
class ScheduleLevelsOutcome:
    operation: str
    action: str | None
    state: ScheduleLevelsState
    events: tuple[ScheduleLevelsEvent, ...]
    complete: bool
    scope: str

    def as_dict(self) -> dict:
        return {"operation": self.operation, "action": self.action, "complete": self.complete,
                "scope": self.scope, "original_exception_unwind_executed": False,
                "state": self.state.as_dict(), "events": [e.as_dict() for e in self.events]}


LevelSave = Callable[[ScheduleLevel, ScheduleLevelsState], None]
StorageSave = Callable[[ScheduleLevelsState], None]


def _signature(state: ScheduleLevelsState) -> tuple:
    return (tuple((id(x), x.identity, x.address, x.value, x.tag) for x in state.levels),
            state.save_lock, state.pending_save, state.level_save_attempts,
            state.level_save_completed, state.storage_attempts, state.storage_completed, state.project_requests)


class _Work:
    def __init__(self, state: ScheduleLevelsState):
        self.state = state
        self.events: list[ScheduleLevelsEvent] = []

    def update(self, **changes: object) -> None:
        self.state = replace(self.state, **changes)

    def event(self, name: str, **fields: object) -> None:
        self.events.append(ScheduleLevelsEvent(name, self.state, **fields))

    def save_level(self, level: ScheduleLevel, callback: LevelSave | None) -> None:
        self.update(level_save_attempts=self.state.level_save_attempts + 1)
        self.event("level_save_requested", level=level)
        if callback is not None:
            callback(level, self.state)
        self.update(level_save_completed=self.state.level_save_completed + 1)

    def save_project(self, callback: StorageSave | None) -> None:
        self.update(project_requests=self.state.project_requests + 1)
        self.event("project_save_entry")
        if self.state.save_lock:
            self.event("storage_filter")
            self.update(pending_save=True)
        else:
            self.update(storage_attempts=self.state.storage_attempts + 1)
            self.event("storage_requested")
            if callback is not None:
                callback(self.state)
            self.update(storage_completed=self.state.storage_completed + 1)

    def end_lock(self, callback: StorageSave | None) -> None:
        self.event("EndSaveLock_entry")
        self.update(save_lock=self.state.save_lock - 1)
        if not self.state.save_lock and self.state.pending_save:
            self.save_project(callback)
            self.update(pending_save=False)


class ScheduleLevelsEngine:
    """Issue immutable states and execute the proven retained operation order.

    Existing tags are opaque retained text. Identity strings identify records
    within this model; they do not establish original pointers or native OIDs.
    Save callbacks observe immutable snapshots; their return values are ignored.
    The first callback failure is rethrown with a non-resumable partial outcome.
    """

    def __init__(self) -> None:
        self._issued: WeakKeyDictionary = WeakKeyDictionary()
        self._active = False
        self.last_outcome: ScheduleLevelsOutcome | None = None
        self.last_evidence: dict | None = None
        self.last_error: BaseException | None = None

    def _reset(self) -> None:
        if self._active:
            raise ValueError("A scheduling operation is already active")
        self.last_outcome = None
        self.last_evidence = None
        self.last_error = None

    def _issue(self, state: ScheduleLevelsState, resumable: bool) -> ScheduleLevelsState:
        self._issued[state] = (_signature(state), resumable)
        return state

    def _require(self, state: ScheduleLevelsState) -> None:
        if type(state) is not ScheduleLevelsState or state not in self._issued:
            raise ValueError("State must be issued by this scheduling engine")
        signature, resumable = self._issued[state]
        if signature != _signature(state):
            raise ValueError("Issued scheduling state has changed")
        if not resumable:
            raise ValueError("A failed partial scheduling state cannot be resumed")

    def load(self, levels: tuple[ScheduleLevel, ...] | list[ScheduleLevel], *,
             save_lock: int = 0, pending_save: bool = False) -> ScheduleLevelsState:
        self._reset()
        if type(levels) not in (tuple, list) or len(levels) > 256:
            raise ValueError("At most 256 exact byte-addressed level records are supported")
        _integer(save_lock, 0, 2, "Initial save lock")
        if type(pending_save) is not bool:
            raise ValueError("Pending-save flag must be Boolean")
        identities: set[str] = set()
        addresses: set[int] = set()
        for level in levels:
            if type(level) is not ScheduleLevel:
                raise ValueError("Exact ScheduleLevel records are required")
            _text(level.identity, 128, "Level identity", empty=False)
            _integer(level.address, 0, 255, "Existing level address")
            _integer(level.value, 0, 255, "Existing level Value")
            _text(level.tag, 128, "Existing level tag")
            if level.identity in identities or level.address in addresses:
                raise ValueError("Level identities and addresses must be unique")
            identities.add(level.identity)
            addresses.add(level.address)
        return self._issue(ScheduleLevelsState(tuple(levels), save_lock, pending_save), True)

    def _remember(self, outcome: ScheduleLevelsOutcome, error: BaseException | None) -> None:
        self.last_outcome = outcome
        self.last_error = error
        try:
            evidence = outcome.as_dict()
        except BaseException:
            evidence = {"operation": outcome.operation, "complete": outcome.complete,
                        "scope": outcome.scope, "evidence_export_failed": True}
        self.last_evidence = evidence
        if error is not None:
            try:
                error.thermostat_schedule_levels_evidence = evidence
            except BaseException:
                pass

    def _operate(self, state: ScheduleLevelsState, action: str | None,
                 level_save: LevelSave | None, storage_save: StorageSave | None,
                 operation: str) -> ScheduleLevelsOutcome:
        self._reset()
        self._require(state)
        if operation == "create_levels" and (type(action) is not str or action not in SCHEDULE_ACTIONS):
            raise ValueError("Action must be Enable, Disable, or Overrd")
        if operation == "end_save_lock" and not state.save_lock:
            raise ValueError("No outer save lock remains")
        if any(x is not None and not callable(x) for x in (level_save, storage_save)):
            raise ValueError("Save providers must be callable or absent")
        work = _Work(state)
        scope = "model_only" if level_save is None and storage_save is None else "supplied_save_callbacks"
        self._active = True
        try:
            if operation == "create_levels":
                work.event("BeginSaveLock_entry")
                work.update(save_lock=work.state.save_lock + 1)
                changed = False
                identities = {x.identity for x in state.levels}
                serial = 0
                for address in range(1, 32):
                    work.event("find_level_entry", address=address, create=False)
                    if any(x.address == address for x in work.state.levels):
                        continue
                    work.event("find_level_entry", address=address, create=True)
                    while True:
                        serial += 1
                        identity = f"schedule:{serial}"
                        if identity not in identities:
                            break
                    identities.add(identity)
                    level = ScheduleLevel(identity, address, address, f"Level {address}")
                    work.update(levels=(*work.state.levels, level))
                    work.save_level(level, level_save)
                    work.save_project(storage_save)
                    level = replace(level, tag=f"Sched {action} {level_to_zones(address)}")
                    work.update(levels=(*work.state.levels[:-1], level))
                    work.save_level(level, level_save)
                    changed = True
                if changed:
                    work.save_project(storage_save)
            work.end_lock(storage_save)
            final = self._issue(work.state, True)
            outcome = ScheduleLevelsOutcome(operation, action, final, tuple(work.events), True, scope)
            self._remember(outcome, None)
            return outcome
        except BaseException as error:
            final = self._issue(work.state, False)
            outcome = ScheduleLevelsOutcome(operation, action, final, tuple(work.events), False, scope)
            self._remember(outcome, error)
            raise
        finally:
            self._active = False

    def create_levels(self, state: ScheduleLevelsState, action: str, *,
                      level_save: LevelSave | None = None,
                      storage_save: StorageSave | None = None) -> ScheduleLevelsOutcome:
        return self._operate(state, action, level_save, storage_save, "create_levels")

    def end_save_lock(self, state: ScheduleLevelsState, *,
                      storage_save: StorageSave | None = None) -> ScheduleLevelsOutcome:
        return self._operate(state, None, None, storage_save, "end_save_lock")
