"""Preparation-only discovery and client-lifetime safety models.

These frozen reducers consume explicit synthetic actions and return symbolic
requests. They do not import transport leaves, query a clock, schedule callbacks,
open a client, or perform I/O. The named local profile is proposed safety policy;
original DN/CL GUI ordering, pause continuation and Retry eligibility are gated.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import math


LOCAL_PROFILE = "offline-discovery-session-safety-v1"
MAX_ROWS = 256
MAX_JOURNAL = 4096
MAX_EDITOR_BYTES = 65536


class UnsupportedContract(ValueError):
    """The requested transition has no admitted preparation contract."""


class Surface(StrEnum):
    COM_SCAN = "discover_project_com_scan"
    CNI_SCAN = "discover_project_cni_project_scan"
    NETWORK_SCAN = "scan_network_progress"
    OPEN_NETWORKS = "open_networks"
    SHELL = "ordinary_client_session"


def _text(value: str, field: str) -> None:
    if type(value) is not str or not value or len(value) > 512 or any(ord(c) < 32 for c in value):
        raise ValueError(f"{field} must be bounded nonempty text without controls")


def _generation(value: int, field: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")


def _limit(value: int, maximum: int, field: str) -> None:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{field} must be in 1..{maximum}")


def _profile(value: str) -> None:
    if value != LOCAL_PROFILE:
        raise UnsupportedContract("Only the preparation-only local safety profile is admitted")


@dataclass(frozen=True)
class Context:
    """Lexical ownership captured before dispatch; selectors alone are insufficient."""

    flow_id: str
    form_instance: str
    endpoint: str
    connection_generation: int = 0
    selection_generation: int = 0
    project: str | None = None
    object_identity: str | None = None
    model_generation: int = 0
    form_generation: int = 0

    def __post_init__(self) -> None:
        for field in ("flow_id", "form_instance", "endpoint"):
            _text(getattr(self, field), field)
        for field in ("connection_generation", "selection_generation", "model_generation", "form_generation"):
            _generation(getattr(self, field), field)
        for field in ("project", "object_identity"):
            value = getattr(self, field)
            if value is not None:
                _text(value, field)
        if self.object_identity is not None and self.project is None:
            raise ValueError("An object identity requires its lexical project identity")


@dataclass(frozen=True)
class OperationToken:
    context: Context
    surface: Surface
    operation_id: str
    row_id: str
    attempt: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.context, Context) or not isinstance(self.surface, Surface):
            raise ValueError("A captured Context and exact Surface are required")
        _text(self.operation_id, "operation_id")
        _text(self.row_id, "row_id")
        _limit(self.attempt, MAX_ROWS, "attempt")


@dataclass(frozen=True)
class Outcome:
    kind: str
    detail: str = ""
    terminal: bool = True
    # Caller-supplied synthetic observation assertion, never native/readback proof.
    independent: bool = False
    code: int | None = None

    def __post_init__(self) -> None:
        _text(self.kind, "outcome kind")
        if type(self.detail) is not str or len(self.detail) > 4096:
            raise ValueError("Outcome detail must be bounded immutable text")
        if type(self.terminal) is not bool or type(self.independent) is not bool:
            raise ValueError("Outcome flags must be booleans")
        if self.code is not None and type(self.code) is not int:
            raise ValueError("Response code must be an integer")


@dataclass(frozen=True)
class Effect:
    """Symbolic request only; never an executed command or transport receipt."""

    kind: str
    token: OperationToken
    window_seconds: float | None = None

    def __post_init__(self) -> None:
        _text(self.kind, "effect kind")
        if not isinstance(self.token, OperationToken):
            raise ValueError("Effect requires a captured immutable token")
        if self.window_seconds is not None and (type(self.window_seconds) not in (int, float)
                or not math.isfinite(self.window_seconds) or not 0 < self.window_seconds <= 300):
            raise ValueError("Effect observation window must be finite and bounded")


@dataclass(frozen=True)
class Callback:
    token: OperationToken
    outcome: Outcome

    def __post_init__(self) -> None:
        if not isinstance(self.token, OperationToken) or not isinstance(self.outcome, Outcome):
            raise ValueError("A callback requires an immutable token and outcome")


@dataclass(frozen=True)
class ObservationRecord:
    callback: Callback
    presented: bool
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.callback, Callback) or type(self.presented) is not bool:
            raise ValueError("Observation record requires immutable callback and boolean disposition")
        _text(self.reason, "suppression reason")


@dataclass(frozen=True)
class RowSpec:
    row_id: str
    endpoint: str
    project: str | None = None
    object_identity: str | None = None
    window_seconds: float = 2.0

    def __post_init__(self) -> None:
        _text(self.row_id, "row_id")
        _text(self.endpoint, "endpoint")
        for field in ("project", "object_identity"):
            value = getattr(self, field)
            if value is not None:
                _text(value, field)
        if self.object_identity is not None and self.project is None:
            raise ValueError("A row object requires its project identity")
        if (type(self.window_seconds) not in (int, float) or not math.isfinite(self.window_seconds)
                or not 0 < self.window_seconds <= 300):
            raise ValueError("A row requires a finite bounded observation window")


@dataclass(frozen=True)
class Row:
    spec: RowSpec
    phase: str = "queued"
    attempt: int = 0
    tokens: tuple[OperationToken, ...] = ()
    terminal: Outcome | None = None
    # Stop belongs to a dispatched attempt, even if Retry later resumes another row.
    stopped_tokens: tuple[OperationToken, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.spec, RowSpec):
            raise ValueError("Row requires an immutable RowSpec")
        if self.phase not in ("queued", "collecting", "completed", "interrupted", "cancelled_before_dispatch",
                              "open_dispatched", "accepted", "independently_ready", "refused", "unreachable", "unknown_after_dispatch"):
            raise ValueError("Unknown row phase")
        _generation(self.attempt, "attempt")
        if self.attempt > MAX_ROWS or type(self.tokens) is not tuple or len(self.tokens) != self.attempt:
            raise ValueError("Row attempts require an immutable bounded token history")
        if any(not isinstance(token, OperationToken) or token.attempt != index + 1
               for index, token in enumerate(self.tokens)):
            raise ValueError("Row token attempts must be sequential")
        if (type(self.stopped_tokens) is not tuple or len(self.stopped_tokens) > len(self.tokens)
                or any(not isinstance(token, OperationToken) or token not in self.tokens
                       for token in self.stopped_tokens)
                or len(set(self.stopped_tokens)) != len(self.stopped_tokens)):
            raise ValueError("Stopped attempts require immutable unique tokens from this row's bounded history")
        if self.terminal is not None and not isinstance(self.terminal, Outcome):
            raise ValueError("Row terminal observation must be immutable")
        latest_stopped = bool(self.tokens) and self.tokens[-1] in self.stopped_tokens
        if self.phase == "unknown_after_dispatch" and self.terminal is None and not latest_stopped:
            raise ValueError("Unknown opening without a terminal receipt must retain its latest stopped attempt")
        if latest_stopped and (self.phase != "unknown_after_dispatch" or self.terminal is not None):
            raise ValueError("A stopped latest attempt must remain unknown without a terminal receipt")
        if self.phase in ("collecting", "open_dispatched") and not self.tokens:
            raise ValueError("Dispatched rows require a captured token")


@dataclass(frozen=True)
class DiscoveryState:
    context: Context
    surface: Surface
    rows: tuple[Row, ...]
    profile: str = LOCAL_PROFILE
    journal_limit: int = 256
    journal: tuple[ObservationRecord, ...] = ()
    stopped: bool = False
    paused: bool = False
    closed: bool = False
    active_at_pause: tuple[OperationToken, ...] = ()
    evidence_incomplete: bool = False
    dropped_callbacks: int = 0
    actions: tuple[str, ...] = ()
    preparation_only: bool = True
    native_manual_executed: bool = False
    hardware_executed: bool = False
    io_performed: bool = False
    absence_proven: bool = False

    def __post_init__(self) -> None:
        _profile(self.profile)
        if not isinstance(self.context, Context) or not isinstance(self.surface, Surface) or self.surface == Surface.SHELL:
            raise ValueError("Discovery state requires Context and an exact discovery/opening Surface")
        maximum = 16 if self.surface == Surface.CNI_SCAN else MAX_ROWS
        if type(self.rows) is not tuple or not 1 <= len(self.rows) <= maximum or any(not isinstance(row, Row) for row in self.rows):
            raise ValueError("State rows must be immutable, typed and bounded")
        _validate_rows(tuple(row.spec for row in self.rows), maximum)
        _limit(self.journal_limit, MAX_JOURNAL, "journal_limit")
        _validate_journal(self.journal, self.journal_limit)
        if (type(self.active_at_pause) is not tuple or len(self.active_at_pause) > len(self.rows)
                or any(not isinstance(token, OperationToken) for token in self.active_at_pause)):
            raise ValueError("Paused operation tokens must be immutable and bounded")
        if type(self.actions) is not tuple or len(self.actions) > self.journal_limit:
            raise ValueError("Action observations must be immutable and bounded")
        for action in self.actions:
            _text(action, "recorded action")
        for field in ("stopped", "paused", "closed", "evidence_incomplete"):
            if type(getattr(self, field)) is not bool:
                raise ValueError("Lifecycle flags must be booleans")
        _generation(self.dropped_callbacks, "dropped_callbacks")
        _preparation_authority(self)
        if type(self.absence_proven) is not bool or self.absence_proven:
            raise ValueError("This preparation model cannot prove absence")
        if self.surface == Surface.CNI_SCAN and sum(row.spec.window_seconds for row in self.rows) > 300:
            raise ValueError("CNI aggregate observation windows exceed 300 seconds")
        if self.surface == Surface.COM_SCAN and any(not 1 <= row.spec.window_seconds <= 60 for row in self.rows):
            raise ValueError("Serial observation windows must be in 1..60 seconds")
        if self.surface == Surface.OPEN_NETWORKS and any(row.spec.project is None or row.spec.object_identity is None for row in self.rows):
            raise ValueError("Opening rows require project and qualified object identities")
        if self.paused and self.surface != Surface.CNI_SCAN:
            raise ValueError("Only the CNI-project surface admits local Pause")
        if self.surface != Surface.OPEN_NETWORKS and any(row.stopped_tokens for row in self.rows):
            raise ValueError("Stopped opening attempts belong only to the OpenNetworks surface")
        for row in self.rows:
            for token in row.tokens:
                if (token.surface != self.surface or token.row_id != row.spec.row_id
                        or token.context.endpoint != row.spec.endpoint or token.context.project != row.spec.project
                        or token.context.object_identity != row.spec.object_identity
                        or token.context.flow_id != self.context.flow_id
                        or token.context.form_instance != self.context.form_instance):
                    raise ValueError("Row token must retain its captured complete target identity")


def _preparation_authority(state) -> None:
    if type(state.preparation_only) is not bool or not state.preparation_only:
        raise ValueError("This model is always preparation-only")
    for field in ("native_manual_executed", "hardware_executed", "io_performed"):
        if type(getattr(state, field)) is not bool or getattr(state, field):
            raise ValueError("Preparation state cannot carry execution authority")


def _validate_journal(journal: tuple[ObservationRecord, ...], limit: int) -> None:
    if type(journal) is not tuple or len(journal) > limit or any(not isinstance(record, ObservationRecord) for record in journal):
        raise ValueError("Observation journal must be immutable, typed and bounded")


def _action_record(state: DiscoveryState, kind: str) -> DiscoveryState:
    if len(state.actions) == state.journal_limit:
        return replace(state, evidence_incomplete=True)
    return replace(state, actions=state.actions + (kind,))


@dataclass(frozen=True)
class DiscoveryAction:
    kind: str
    row_ids: tuple[str, ...] = ()
    callback: Callback | None = None

    def __post_init__(self) -> None:
        _text(self.kind, "action kind")
        if type(self.row_ids) is not tuple or any(type(value) is not str for value in self.row_ids):
            raise ValueError("Row IDs must be an immutable tuple")
        if len(set(self.row_ids)) != len(self.row_ids) or len(self.row_ids) > MAX_ROWS:
            raise ValueError("Row IDs must be unique and bounded")
        for value in self.row_ids:
            _text(value, "row_id")
        if self.callback is not None and not isinstance(self.callback, Callback):
            raise ValueError("callback must be a Callback")


@dataclass(frozen=True)
class Transition:
    state: DiscoveryState | SessionState
    effects: tuple[Effect, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.state, (DiscoveryState, SessionState)):
            raise ValueError("A transition requires an admitted immutable state")
        if type(self.effects) is not tuple or any(not isinstance(effect, Effect) for effect in self.effects):
            raise ValueError("Effects must be an immutable typed tuple")


def new_discovery(context: Context, surface: Surface, rows: tuple[RowSpec, ...], *,
                  profile: str = LOCAL_PROFILE, journal_limit: int = 256) -> DiscoveryState:
    _profile(profile)
    if not isinstance(context, Context) or not isinstance(surface, Surface):
        raise ValueError("A captured Context and exact Surface enum are required")
    if surface not in (Surface.COM_SCAN, Surface.CNI_SCAN, Surface.NETWORK_SCAN):
        raise UnsupportedContract("Discovery requires its exact retained scan surface")
    _validate_rows(rows, 16 if surface == Surface.CNI_SCAN else MAX_ROWS)
    if surface == Surface.CNI_SCAN and sum(row.window_seconds for row in rows) > 300:
        raise ValueError("CNI configured observation windows must total at most 300 seconds")
    if surface == Surface.COM_SCAN and any(not 1 <= row.window_seconds <= 60 for row in rows):
        raise ValueError("Serial probe windows must be in 1..60 seconds")
    _limit(journal_limit, MAX_JOURNAL, "journal_limit")
    return DiscoveryState(context, surface, tuple(Row(row) for row in rows), profile, journal_limit)


def new_open_networks(context: Context, rows: tuple[RowSpec, ...], *,
                      profile: str = LOCAL_PROFILE, journal_limit: int = 256) -> DiscoveryState:
    _profile(profile)
    if not isinstance(context, Context):
        raise ValueError("A captured Context is required")
    _validate_rows(rows, MAX_ROWS)
    if any(row.project is None or row.object_identity is None for row in rows):
        raise ValueError("Opening rows require exact project and qualified object identities")
    _limit(journal_limit, MAX_JOURNAL, "journal_limit")
    return DiscoveryState(context, Surface.OPEN_NETWORKS, tuple(Row(row) for row in rows),
                          profile, journal_limit)


def _validate_rows(rows: tuple[RowSpec, ...], maximum: int) -> None:
    if type(rows) is not tuple or not rows or len(rows) > maximum or any(not isinstance(row, RowSpec) for row in rows):
        raise ValueError(f"Rows must be an immutable sequence of 1..{maximum} RowSpec values")
    if len({row.row_id for row in rows}) != len(rows):
        raise ValueError("Row IDs must be unique")
    if len({(row.endpoint, row.project, row.object_identity) for row in rows}) != len(rows):
        raise ValueError("Duplicate row targets are not admitted")


def _row_token(state: DiscoveryState, row: Row) -> OperationToken:
    context = replace(state.context, endpoint=row.spec.endpoint, project=row.spec.project,
                      object_identity=row.spec.object_identity)
    attempt = row.attempt + 1
    return OperationToken(context, state.surface, f"{row.spec.row_id}:{attempt}", row.spec.row_id, attempt)


def _append_record(state: DiscoveryState | SessionState, record: ObservationRecord):
    if len(state.journal) == state.journal_limit:
        return replace(state, evidence_incomplete=True, dropped_callbacks=state.dropped_callbacks + 1)
    return replace(state, journal=state.journal + (record,))


def _mismatch(captured: Context, current: Context) -> str | None:
    for field in ("flow_id", "form_instance", "form_generation", "endpoint", "connection_generation",
                  "selection_generation", "project", "object_identity", "model_generation"):
        if getattr(captured, field) != getattr(current, field):
            return field + "_mismatch"
    return None


def _find_row(state: DiscoveryState, row_id: str) -> int:
    matches = [index for index, row in enumerate(state.rows) if row.spec.row_id == row_id]
    if not matches:
        raise ValueError("Unknown row identity")
    return matches[0]


def _replace_row(state: DiscoveryState, index: int, row: Row) -> DiscoveryState:
    return replace(state, rows=state.rows[:index] + (row,) + state.rows[index + 1:])


_SERIAL_OUTCOMES = frozenset(("present", "absent", "timeout", "busy", "malformed", "not_found", "rejected", "error"))
_CNI_OUTCOMES = frozenset(("transport_error", "datagram_limit", "devices_observed", "filtered_replies_by_deadline",
                           "hidden_replies_by_deadline", "no_valid_reply_by_deadline", "no_reply_by_deadline"))
_NETWORK_OUTCOMES = frozenset(("completed", "transport_error", "deadline", "incomplete"))
_OPEN_OUTCOMES = frozenset(("accepted", "independently_ready", "refused", "unreachable", "unknown_after_dispatch"))


def cni_outcome(*, collection_complete: bool, devices: int, hidden_ignored: int, malformed: int) -> Outcome:
    """The existing scan_cni aggregate classification, without its transport leaf.

    This is exactly the decision order in cni_discovery.scan_cni. No UDP silence
    result proves absence, TCP reachability, ownership or network readiness.
    """
    if type(collection_complete) is not bool:
        raise ValueError("collection_complete must be boolean")
    for value in (devices, hidden_ignored, malformed):
        _generation(value, "observation count")
    if not collection_complete:
        kind = "datagram_limit"
    elif devices:
        kind = "devices_observed"
    elif hidden_ignored and malformed:
        kind = "filtered_replies_by_deadline"
    elif hidden_ignored:
        kind = "hidden_replies_by_deadline"
    elif malformed:
        kind = "no_valid_reply_by_deadline"
    else:
        kind = "no_reply_by_deadline"
    return Outcome(kind)


def _row_callback(state: DiscoveryState, callback: Callback) -> Transition:
    if callback.token.surface != state.surface:
        return Transition(_append_record(state, ObservationRecord(callback, False, "surface_mismatch")))
    indexes = [index for index, row in enumerate(state.rows) if callback.token in row.tokens]
    if not indexes:
        return Transition(_append_record(state, ObservationRecord(callback, False, "unknown_token")))
    index = indexes[0]
    row = state.rows[index]
    allowed = {Surface.COM_SCAN: _SERIAL_OUTCOMES, Surface.CNI_SCAN: _CNI_OUTCOMES,
               Surface.NETWORK_SCAN: _NETWORK_OUTCOMES, Surface.OPEN_NETWORKS: _OPEN_OUTCOMES}[state.surface]
    if callback.outcome.kind not in allowed:
        raise UnsupportedContract("Outcome is not admitted for this exact surface")
    if state.surface == Surface.OPEN_NETWORKS:
        if not callback.outcome.terminal:
            raise UnsupportedContract("Opening callbacks require an explicit observation disposition")
        if callback.outcome.kind == "independently_ready" and not callback.outcome.independent:
            raise UnsupportedContract("Readiness requires independent observation, not NET OPEN acknowledgement")
        if callback.outcome.kind == "independently_ready" and row.phase != "accepted" and row.terminal != callback.outcome:
            raise UnsupportedContract("Readiness observation requires a matched accepted opening")
    expected = replace(state.context, endpoint=row.spec.endpoint, project=row.spec.project,
                       object_identity=row.spec.object_identity)
    reason = _mismatch(callback.token.context, expected)
    if callback.token != row.tokens[-1]:
        reason = reason or "stale_attempt"
    if state.closed:
        reason = reason or "form_closed"
    if callback.token in row.stopped_tokens:
        reason = reason or "stopped_after_dispatch"
    if row.phase in ("interrupted", "cancelled_before_dispatch"):
        reason = reason or "cancelled_result"
    terminal_duplicate = row.terminal == callback.outcome
    if terminal_duplicate and row.phase not in ("collecting", "open_dispatched"):
        reason = reason or "duplicate_terminal"
    elif row.terminal is not None and row.phase not in ("collecting", "open_dispatched"):
        if not (row.phase == "accepted" and callback.outcome.kind == "independently_ready"):
            reason = reason or "conflicting_terminal"
    if state.evidence_incomplete or len(state.journal) == state.journal_limit:
        reason = reason or "journal_overflow"
    presented = reason is None
    state = _append_record(state, ObservationRecord(callback, presented, reason or "matched"))
    if presented and callback.outcome.terminal:
        phase = callback.outcome.kind if state.surface == Surface.OPEN_NETWORKS else "completed"
        state = _replace_row(state, index, replace(row, phase=phase, terminal=callback.outcome))
    return Transition(state)


def _discovery_dispatch(state: DiscoveryState, action: DiscoveryAction) -> Transition:
    if state.closed or state.stopped or state.paused or state.evidence_incomplete:
        raise UnsupportedContract("Dispatch is blocked by this controller's local lifecycle")
    if len(action.row_ids) != 1:
        raise ValueError("Dispatch must name one exact row")
    if any(row.phase in ("collecting", "open_dispatched") for row in state.rows):
        raise UnsupportedContract("Only one bounded leaf request may be active")
    index = _find_row(state, action.row_ids[0])
    row = state.rows[index]
    if row.phase != "queued":
        raise UnsupportedContract("A nonqueued row cannot be implicitly replayed")
    token = _row_token(state, row)
    phase = "open_dispatched" if state.surface == Surface.OPEN_NETWORKS else "collecting"
    state = _replace_row(state, index, replace(row, phase=phase, attempt=token.attempt, tokens=row.tokens + (token,)))
    kind = {Surface.COM_SCAN: "probe_serial", Surface.CNI_SCAN: "collect_cni",
            Surface.NETWORK_SCAN: "scan_network", Surface.OPEN_NETWORKS: "open_network"}[state.surface]
    return Transition(state, (Effect(kind, token, row.spec.window_seconds),))


def _stop_rows(state: DiscoveryState, *, close: bool = False, opening: bool = False) -> DiscoveryState:
    rows = tuple(replace(row, phase="cancelled_before_dispatch") if row.phase == "queued"
                 else replace(row, phase="unknown_after_dispatch" if opening else "interrupted",
                              stopped_tokens=(row.stopped_tokens + (row.tokens[-1],)
                                              if opening and row.tokens[-1] not in row.stopped_tokens
                                              else row.stopped_tokens))
                 if row.phase in ("collecting", "open_dispatched") else row for row in state.rows)
    context = replace(state.context, form_generation=state.context.form_generation + 1) if close else state.context
    return replace(state, rows=rows, stopped=True, closed=close or state.closed, context=context)


def reduce_discovery(state: DiscoveryState, action: DiscoveryAction) -> Transition:
    _profile(state.profile)
    if state.surface not in (Surface.COM_SCAN, Surface.CNI_SCAN, Surface.NETWORK_SCAN):
        raise UnsupportedContract("Use the opening reducer for OpenNetworks")
    if action.kind == "callback":
        if action.callback is None or action.row_ids:
            raise ValueError("A callback action requires only its captured callback")
        return _row_callback(state, action.callback)
    if action.callback is not None:
        raise ValueError("Only callback actions may carry a callback")
    if action.kind == "dispatch":
        return _discovery_dispatch(state, action)
    if action.row_ids:
        raise ValueError("Only dispatch names scan rows")
    if action.kind == "close":
        return Transition(state if state.closed else _stop_rows(state, close=True))
    expected = {Surface.COM_SCAN: "com_cancel", Surface.CNI_SCAN: "cni_pause",
                Surface.NETWORK_SCAN: "scan_cancel"}[state.surface]
    if action.kind == expected:
        if state.closed:
            raise UnsupportedContract("The form is already closed")
        if action.kind == "cni_pause":
            active = tuple(row.tokens[-1] for row in state.rows if row.phase == "collecting")
            return Transition(_action_record(replace(state, paused=True, active_at_pause=active), action.kind) if not state.paused else state)
        return Transition(state if state.stopped else _action_record(_stop_rows(state), action.kind))
    if action.kind == "discover_project_cancel" and state.surface in (Surface.COM_SCAN, Surface.CNI_SCAN):
        return Transition(state if state.closed else _action_record(_stop_rows(state, close=True), action.kind))
    raise UnsupportedContract("Unverified or wrong-surface scan action; Resume is not admitted")


def reduce_open_networks(state: DiscoveryState, action: DiscoveryAction) -> Transition:
    _profile(state.profile)
    if state.surface != Surface.OPEN_NETWORKS:
        raise UnsupportedContract("OpenNetworks actions cannot control a discovery form")
    if action.kind == "callback":
        if action.callback is None or action.row_ids:
            raise ValueError("A callback action requires only its captured callback")
        return _row_callback(state, action.callback)
    if action.callback is not None:
        raise ValueError("Only callback actions may carry a callback")
    if action.kind == "dispatch":
        return _discovery_dispatch(state, action)
    if action.kind == "retry":
        if state.closed or state.evidence_incomplete or not action.row_ids:
            raise UnsupportedContract("Retry requires an attached, complete ledger and explicit rows")
        indexes = tuple(_find_row(state, row_id) for row_id in action.row_ids)
        if any(state.rows[index].phase not in ("refused", "unreachable") for index in indexes):
            raise UnsupportedContract("Local Retry admits only known refusal/unreachable rows; uncertain opens are never replayed")
        if any(state.rows[index].attempt >= MAX_ROWS for index in indexes):
            raise ValueError("Retry attempt bound exhausted")
        for index in indexes:
            state = _replace_row(state, index, replace(state.rows[index], phase="queued", terminal=None))
        return Transition(_action_record(replace(state, stopped=False), "retry"))
    if action.row_ids:
        raise ValueError("Only dispatch and explicit Retry name opening rows")
    if action.kind == "stop":
        return Transition(state if state.stopped else _action_record(_stop_rows(state, opening=True), "stop"))
    if action.kind == "close":
        return Transition(state if state.closed else _stop_rows(state, close=True, opening=True))
    raise UnsupportedContract("Unverified or wrong-surface OpenNetworks action")


@dataclass(frozen=True)
class EditorSnapshot:
    context: Context
    payload: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.context, Context) or type(self.payload) is not bytes or len(self.payload) > MAX_EDITOR_BYTES:
            raise ValueError("A dirty editor requires a bounded immutable bytes snapshot and captured context")


@dataclass(frozen=True)
class SessionOperation:
    token: OperationToken
    kind: str
    phase: str = "scheduled"
    terminal: Outcome | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.token, OperationToken) or self.token.surface != Surface.SHELL:
            raise ValueError("Session operations require exact shell tokens")
        if self.kind not in ("project_use", "load", "focus_refresh", "group_refresh", "pp_refresh"):
            raise UnsupportedContract("Unknown local session operation")
        if self.phase not in ("scheduled", "dispatched", "completed", "cancelled_before_dispatch", "unknown_after_dispatch"):
            raise ValueError("Unknown session operation phase")
        if self.terminal is not None and not isinstance(self.terminal, Outcome):
            raise ValueError("Session terminal observation must be immutable")


@dataclass(frozen=True)
class SessionState:
    context: Context
    profile: str = LOCAL_PROFILE
    connected: bool = True
    closed: bool = False
    project_confirmed: str | None = None
    operation_limit: int = 64
    operations: tuple[SessionOperation, ...] = ()
    journal_limit: int = 256
    journal: tuple[ObservationRecord, ...] = ()
    dirty_editor: EditorSnapshot | None = None
    detached_editors: tuple[EditorSnapshot, ...] = ()
    evidence_incomplete: bool = False
    dropped_callbacks: int = 0
    preparation_only: bool = True
    native_manual_executed: bool = False
    hardware_executed: bool = False
    io_performed: bool = False

    def __post_init__(self) -> None:
        _profile(self.profile)
        if not isinstance(self.context, Context):
            raise ValueError("Session state requires its captured immutable Context")
        _limit(self.operation_limit, MAX_ROWS, "operation_limit")
        _limit(self.journal_limit, MAX_JOURNAL, "journal_limit")
        if (type(self.operations) is not tuple or len(self.operations) > self.operation_limit
                or any(not isinstance(op, SessionOperation) for op in self.operations)):
            raise ValueError("Session operations must be immutable, typed and bounded")
        if len({op.token.operation_id for op in self.operations}) != len(self.operations):
            raise ValueError("Session operation identities must be unique")
        for op in self.operations:
            if (op.token.context.flow_id != self.context.flow_id
                    or op.token.context.form_instance != self.context.form_instance):
                raise ValueError("Session operations must retain their original owning form")
        _validate_journal(self.journal, self.journal_limit)
        if (type(self.detached_editors) is not tuple or len(self.detached_editors) > self.operation_limit
                or any(not isinstance(editor, EditorSnapshot) for editor in self.detached_editors)):
            raise ValueError("Detached editor snapshots must be immutable, typed and bounded")
        if self.dirty_editor is not None and (not isinstance(self.dirty_editor, EditorSnapshot)
                                             or self.dirty_editor.context != self.context):
            raise ValueError("Attached editor must retain its exact current context")
        for field in ("connected", "closed", "evidence_incomplete"):
            if type(getattr(self, field)) is not bool:
                raise ValueError("Lifecycle flags must be booleans")
        if self.closed and self.connected:
            raise ValueError("A closed form cannot retain an attached client")
        if self.project_confirmed is not None and (self.project_confirmed != self.context.project
                                                   or not self.connected or self.closed):
            raise ValueError("Confirmed project requires the current attached selection")
        _generation(self.dropped_callbacks, "dropped_callbacks")
        _preparation_authority(self)


@dataclass(frozen=True)
class SessionAction:
    kind: str
    operation_id: str | None = None
    operation_kind: str | None = None
    project: str | None = None
    object_identity: str | None = None
    model_generation: int | None = None
    endpoint: str | None = None
    callback: Callback | None = None
    editor: EditorSnapshot | None = None

    def __post_init__(self) -> None:
        _text(self.kind, "action kind")
        for field in ("operation_id", "operation_kind", "project", "object_identity", "endpoint"):
            value = getattr(self, field)
            if value is not None:
                _text(value, field)
        if self.model_generation is not None:
            _generation(self.model_generation, "model_generation")
        if self.callback is not None and not isinstance(self.callback, Callback):
            raise ValueError("callback must be immutable Callback")
        if self.editor is not None and not isinstance(self.editor, EditorSnapshot):
            raise ValueError("editor must be immutable EditorSnapshot")


def new_session(context: Context, *, profile: str = LOCAL_PROFILE, operation_limit: int = 64,
                journal_limit: int = 256) -> SessionState:
    _profile(profile)
    if not isinstance(context, Context):
        raise ValueError("A captured Context is required")
    _limit(operation_limit, MAX_ROWS, "operation_limit")
    _limit(journal_limit, MAX_JOURNAL, "journal_limit")
    return SessionState(context, profile, operation_limit=operation_limit, journal_limit=journal_limit)


_SESSION_KINDS = frozenset(("project_use", "load", "focus_refresh", "group_refresh", "pp_refresh"))


def _replace_operation(state: SessionState, index: int, operation: SessionOperation) -> SessionState:
    return replace(state, operations=state.operations[:index] + (operation,) + state.operations[index + 1:])


def _invalidate_operations(state: SessionState, *, disconnected: bool) -> tuple[SessionOperation, ...]:
    return tuple(replace(op, phase="cancelled_before_dispatch") if op.phase == "scheduled"
                 else replace(op, phase="unknown_after_dispatch") if disconnected and op.phase == "dispatched"
                 else op for op in state.operations)


def _session_callback(state: SessionState, callback: Callback) -> Transition:
    indexes = [index for index, op in enumerate(state.operations) if op.token == callback.token]
    if callback.token.surface != Surface.SHELL or not indexes:
        reason = "surface_mismatch" if callback.token.surface != Surface.SHELL else "unknown_token"
        return Transition(_append_record(state, ObservationRecord(callback, False, reason)))
    index = indexes[0]
    op = state.operations[index]
    if callback.outcome.kind not in ("completed", "refused", "transport_error", "unknown_after_dispatch") or not callback.outcome.terminal:
        raise UnsupportedContract("Session callbacks require an explicit terminal local disposition")
    reason = _mismatch(callback.token.context, state.context)
    if state.closed or not state.connected:
        reason = reason or ("form_closed" if state.closed else "disconnected")
    if op.phase in ("scheduled", "cancelled_before_dispatch"):
        reason = reason or "callback_before_dispatch"
    if op.terminal is not None:
        reason = reason or ("duplicate_terminal" if op.terminal == callback.outcome else "conflicting_terminal")
    if op.kind == "project_use" and callback.outcome.kind == "completed" and callback.outcome.code != 200:
        raise UnsupportedContract("Same-client project selection requires exact 200 PROJECT USE")
    if state.evidence_incomplete or len(state.journal) == state.journal_limit:
        reason = reason or "journal_overflow"
    presented = reason is None
    retained = not state.evidence_incomplete and len(state.journal) < state.journal_limit
    current_connection = state.connected and not state.closed and all(
        getattr(callback.token.context, field) == getattr(state.context, field)
        for field in ("flow_id", "form_instance", "form_generation", "endpoint", "connection_generation"))
    state = _append_record(state, ObservationRecord(callback, presented, reason or "matched"))
    if retained and op.phase in ("dispatched", "unknown_after_dispatch") and op.terminal is None:
        phase = "unknown_after_dispatch" if callback.outcome.kind in ("transport_error", "unknown_after_dispatch") else "completed"
        state = _replace_operation(state, index, replace(op, phase=phase, terminal=callback.outcome))
    if presented and op.kind == "project_use" and callback.outcome.kind == "completed":
        state = replace(state, project_confirmed=callback.token.context.project)
    if current_connection and op.phase == "dispatched" and callback.outcome.kind in ("transport_error", "unknown_after_dispatch"):
        state = _disconnect(state)
    return Transition(state)


def _detach_editor(state: SessionState) -> tuple[EditorSnapshot, ...]:
    if state.dirty_editor is None:
        return state.detached_editors
    if len(state.detached_editors) >= state.operation_limit:
        raise ValueError("Detached editor bound exhausted; snapshot preservation cannot be dropped")
    return state.detached_editors + (state.dirty_editor,)


def _disconnect(state: SessionState, *, close: bool = False) -> SessionState:
    context = replace(state.context, connection_generation=state.context.connection_generation + 1,
                      selection_generation=state.context.selection_generation + 1,
                      form_generation=state.context.form_generation + (1 if close else 0))
    return replace(state, context=context, connected=False, closed=close or state.closed,
                   project_confirmed=None, operations=_invalidate_operations(state, disconnected=True),
                   detached_editors=_detach_editor(state), dirty_editor=None)


def reduce_session(state: SessionState, action: SessionAction) -> Transition:
    _profile(state.profile)
    if action.kind == "callback":
        if action.callback is None:
            raise ValueError("Callback action requires its captured callback")
        return _session_callback(state, action.callback)
    if action.callback is not None:
        raise ValueError("Only callback actions may carry a callback")
    if action.kind == "close":
        return Transition(state if state.closed else _disconnect(state, close=True))
    if action.kind == "disconnect":
        return Transition(state if not state.connected else _disconnect(state))
    if state.closed:
        raise UnsupportedContract("Closed forms cannot be resurrected")
    if action.kind == "reconnect":
        if state.connected or action.endpoint is None:
            raise UnsupportedContract("Reconnect requires a disconnected form and an explicit endpoint")
        _text(action.endpoint, "endpoint")
        context = replace(state.context, endpoint=action.endpoint,
                          connection_generation=state.context.connection_generation + 1,
                          selection_generation=state.context.selection_generation + 1,
                          project=None, object_identity=None)
        return Transition(replace(state, context=context, connected=True, project_confirmed=None))
    if not state.connected:
        raise UnsupportedContract("Disconnected sessions cannot dispatch or rebind")
    if action.kind == "select":
        if action.project is None or action.object_identity is None or action.model_generation is None:
            raise ValueError("Selection requires project, qualified object identity and model generation")
        context = replace(state.context, project=action.project, object_identity=action.object_identity,
                          model_generation=action.model_generation,
                          selection_generation=state.context.selection_generation + 1)
        return Transition(replace(state, context=context, project_confirmed=None,
                                  operations=_invalidate_operations(state, disconnected=False),
                                  detached_editors=_detach_editor(state), dirty_editor=None))
    if action.kind == "dirty_editor":
        if action.editor is None or action.editor.context != state.context:
            raise ValueError("Dirty editor snapshot must capture the current complete context")
        return Transition(replace(state, dirty_editor=action.editor))
    if action.kind == "schedule":
        if state.evidence_incomplete or len(state.operations) >= state.operation_limit:
            raise UnsupportedContract("Operation ledger bound exhausted or incomplete")
        if action.operation_id is None or action.operation_kind not in _SESSION_KINDS:
            raise UnsupportedContract("Only explicit local operation kinds and identities are admitted")
        if state.context.project is None or state.context.object_identity is None:
            raise ValueError("Dependent work requires a captured qualified selection")
        if any(op.token.operation_id == action.operation_id for op in state.operations):
            raise ValueError("Operation identities may not be reused")
        token = OperationToken(state.context, Surface.SHELL, action.operation_id, action.operation_id)
        op = SessionOperation(token, action.operation_kind)
        return Transition(replace(state, operations=state.operations + (op,)))
    if action.kind == "dispatch":
        indexes = [index for index, op in enumerate(state.operations) if op.token.operation_id == action.operation_id]
        if len(indexes) != 1:
            raise ValueError("Dispatch must name one recorded operation")
        index = indexes[0]
        op = state.operations[index]
        if state.evidence_incomplete or op.phase != "scheduled" or _mismatch(op.token.context, state.context):
            raise UnsupportedContract("Only current scheduled work can dispatch once")
        if any(other.phase == "dispatched" for other in state.operations):
            raise UnsupportedContract("The serialized client permits one in-flight command")
        if op.kind != "project_use" and state.project_confirmed != state.context.project:
            raise UnsupportedContract("Dependent work requires exact same-generation PROJECT USE confirmation")
        state = _replace_operation(state, index, replace(op, phase="dispatched"))
        return Transition(state, (Effect(op.kind, op.token),))
    raise UnsupportedContract("Unverified session transition; no native timer, dirty-editor save or rebind policy is inferred")


@dataclass(frozen=True)
class ScriptedFakeAdapter:
    """Immutable observations only. No transport, clock, close or dispatch calls."""

    observations: tuple[Outcome, ...]

    def __post_init__(self) -> None:
        if type(self.observations) is not tuple or len(self.observations) > MAX_JOURNAL or any(not isinstance(item, Outcome) for item in self.observations):
            raise ValueError("Fake observations must be an immutable bounded Outcome tuple")

    def observe(self, effect: Effect, index: int) -> Callback:
        if not isinstance(effect, Effect) or type(index) is not int or not 0 <= index < len(self.observations):
            raise ValueError("A scripted observation requires a recorded effect and exact script index")
        return Callback(effect.token, self.observations[index])
