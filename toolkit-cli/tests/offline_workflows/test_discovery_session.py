"""Synthetic safety histories, not original Toolkit or hardware acceptance."""
from dataclasses import FrozenInstanceError, replace
import builtins
import socket

import pytest

from cbus_toolkit.offline_workflows.discovery_session import (
    LOCAL_PROFILE, Callback, Context, DiscoveryAction, EditorSnapshot, Outcome,
    RowSpec, ScriptedFakeAdapter, SessionAction, Surface, UnsupportedContract,
    cni_outcome, new_discovery, new_open_networks, new_session,
    reduce_discovery, reduce_open_networks, reduce_session,
)


def context(project=None, object_identity=None):
    return Context("synthetic-flow", "synthetic-form-1", "fake://session-a",
                   project=project, object_identity=object_identity)


def rows():
    return tuple(RowSpec(f"row-{n}", f"fake://endpoint-{n}") for n in range(1, 4))


def opening_rows():
    return tuple(RowSpec(f"row-{n}", f"fake://endpoint-{n}", "SYNTHETIC", f"//SYNTHETIC/{n}") for n in range(1, 4))


def dispatch_scan(state, row_id):
    return reduce_discovery(state, DiscoveryAction("dispatch", (row_id,)))


def scan_callback(state, effect, outcome):
    fake = ScriptedFakeAdapter((outcome,))
    return reduce_discovery(state, DiscoveryAction("callback", callback=fake.observe(effect, 0))).state


def dispatch_open(state, row_id):
    return reduce_open_networks(state, DiscoveryAction("dispatch", (row_id,)))


def open_callback(state, effect, outcome):
    return reduce_open_networks(state, DiscoveryAction("callback", callback=Callback(effect.token, outcome))).state


def select(state, project="A", endpoint_object="//A/254/p/1", model_generation=1):
    return reduce_session(state, SessionAction("select", project=project,
                          object_identity=endpoint_object, model_generation=model_generation)).state


def session_request(state, operation_id, operation_kind):
    state = reduce_session(state, SessionAction("schedule", operation_id=operation_id,
                          operation_kind=operation_kind)).state
    return reduce_session(state, SessionAction("dispatch", operation_id=operation_id))


def session_callback(state, effect, outcome=Outcome("completed")):
    return reduce_session(state, SessionAction("callback", callback=Callback(effect.token, outcome))).state


def project_selected(state, operation_id="select-project"):
    dispatched = session_request(state, operation_id, "project_use")
    return session_callback(dispatched.state, dispatched.effects[0], Outcome("completed", code=200))


def test_dn1_serial_mixed_outcomes_and_pending_are_explicit():
    state = new_discovery(context(), Surface.COM_SCAN, rows())
    one = dispatch_scan(state, "row-1")
    state = scan_callback(one.state, one.effects[0], Outcome("present"))
    two = dispatch_scan(state, "row-2")
    state = scan_callback(two.state, two.effects[0], Outcome("not_found"))
    three = dispatch_scan(state, "row-3")
    assert [row.phase for row in three.state.rows] == ["completed", "completed", "collecting"]
    assert [row.terminal.kind if row.terminal else None for row in three.state.rows] == ["present", "not_found", None]
    assert three.effects[0].token.row_id == "row-3"
    assert not three.state.absence_proven


@pytest.mark.parametrize("completed", [0, 1])
def test_dn2_com_cancel_before_dispatch_and_after_one_completion(completed):
    state = new_discovery(context(), Surface.COM_SCAN, rows())
    if completed:
        sent = dispatch_scan(state, "row-1")
        state = scan_callback(sent.state, sent.effects[0], Outcome("present"))
    result = reduce_discovery(state, DiscoveryAction("com_cancel"))
    assert result.effects == ()
    assert [row.phase for row in result.state.rows] == (["completed"] if completed else []) + ["cancelled_before_dispatch"] * (3 - completed)
    with pytest.raises(UnsupportedContract):
        dispatch_scan(result.state, "row-3")


def test_dn2_cancel_pending_retains_late_reply_without_new_dispatch():
    state = new_discovery(context(), Surface.COM_SCAN, rows())
    one = dispatch_scan(state, "row-1")
    state = scan_callback(one.state, one.effects[0], Outcome("present"))
    pending = dispatch_scan(state, "row-2")
    state = reduce_discovery(pending.state, DiscoveryAction("com_cancel")).state
    late = Callback(pending.effects[0].token, Outcome("present", "synthetic late receipt"))
    state = reduce_discovery(state, DiscoveryAction("callback", callback=late)).state
    assert [row.phase for row in state.rows] == ["completed", "interrupted", "cancelled_before_dispatch"]
    assert state.journal[-1].callback == late
    assert not state.journal[-1].presented
    assert state.journal[-1].reason == "cancelled_result"
    assert state.rows[1].terminal is None


def test_dn3_cni_pause_keeps_active_window_but_no_guessed_resume():
    state = new_discovery(context(), Surface.CNI_SCAN, rows())
    one = dispatch_scan(state, "row-1")
    state = scan_callback(one.state, one.effects[0], Outcome("devices_observed"))
    two = dispatch_scan(state, "row-2")
    paused = reduce_discovery(two.state, DiscoveryAction("cni_pause"))
    assert paused.effects == ()
    assert paused.state.active_at_pause == (two.effects[0].token,)
    assert two.effects[0].window_seconds == 2
    assert [row.phase for row in paused.state.rows] == ["completed", "collecting", "queued"]
    state = scan_callback(paused.state, two.effects[0], Outcome("no_reply_by_deadline"))
    assert state.rows[1].phase == "completed"
    assert state.rows[1].terminal.kind == "no_reply_by_deadline"
    assert not state.absence_proven
    for action in (DiscoveryAction("resume"), DiscoveryAction("dispatch", ("row-3",))):
        with pytest.raises(UnsupportedContract):
            reduce_discovery(state, action)
    closed = reduce_discovery(state, DiscoveryAction("close"))
    assert closed.effects == () and closed.state.closed
    assert closed.state.rows[2].phase == "cancelled_before_dispatch"


@pytest.mark.parametrize("surface,wrong_action", [
    (Surface.COM_SCAN, "scan_cancel"), (Surface.COM_SCAN, "cni_pause"),
    (Surface.CNI_SCAN, "com_cancel"), (Surface.NETWORK_SCAN, "com_cancel"),
    (Surface.NETWORK_SCAN, "discover_project_cancel"),
])
def test_scan_surfaces_do_not_share_cancel_handlers(surface, wrong_action):
    state = new_discovery(context(), surface, rows())
    with pytest.raises(UnsupportedContract):
        reduce_discovery(state, DiscoveryAction(wrong_action))
    assert not state.stopped


def test_network_progress_cancel_is_independent_and_outer_cancel_detaches():
    scan = new_discovery(context(), Surface.NETWORK_SCAN, rows())
    assert reduce_discovery(scan, DiscoveryAction("scan_cancel")).state.stopped
    com = new_discovery(context(), Surface.COM_SCAN, rows())
    assert reduce_discovery(com, DiscoveryAction("discover_project_cancel")).state.closed


@pytest.mark.parametrize("complete,devices,hidden,malformed,expected", [
    (False, 1, 1, 1, "datagram_limit"), (True, 1, 1, 1, "devices_observed"),
    (True, 0, 1, 1, "filtered_replies_by_deadline"), (True, 0, 1, 0, "hidden_replies_by_deadline"),
    (True, 0, 0, 1, "no_valid_reply_by_deadline"), (True, 0, 0, 0, "no_reply_by_deadline"),
])
def test_cni_uses_existing_leaf_outcome_order(complete, devices, hidden, malformed, expected):
    assert cni_outcome(collection_complete=complete, devices=devices, hidden_ignored=hidden, malformed=malformed).kind == expected


def test_serial_absence_cannot_be_a_cni_result():
    sent = dispatch_scan(new_discovery(context(), Surface.CNI_SCAN, rows()), "row-1")
    with pytest.raises(UnsupportedContract):
        scan_callback(sent.state, sent.effects[0], Outcome("absent"))


def test_dn4_acceptance_is_not_readiness_and_stop_never_closes_networks():
    one = dispatch_open(new_open_networks(context(), opening_rows()), "row-1")
    state = open_callback(one.state, one.effects[0], Outcome("accepted"))
    assert state.rows[0].phase == "accepted"
    with pytest.raises(UnsupportedContract):
        open_callback(state, one.effects[0], Outcome("independently_ready"))
    state = open_callback(state, one.effects[0], Outcome("independently_ready", independent=True))
    two = dispatch_open(state, "row-2")
    state = open_callback(two.state, two.effects[0], Outcome("refused"))
    three = dispatch_open(state, "row-3")
    stopped = reduce_open_networks(three.state, DiscoveryAction("stop"))
    assert stopped.effects == ()
    assert [row.phase for row in stopped.state.rows] == ["independently_ready", "refused", "unknown_after_dispatch"]
    assert all(effect.kind == "open_network" for effect in one.effects + two.effects + three.effects)
    closed = reduce_open_networks(stopped.state, DiscoveryAction("close"))
    assert closed.effects == () and closed.state.closed
    assert closed.state.rows[0].phase == "independently_ready"


def test_dn4_explicit_retry_only_known_eligible_rows_with_fresh_attempt():
    one = dispatch_open(new_open_networks(context(), opening_rows()), "row-1")
    state = open_callback(one.state, one.effects[0], Outcome("unreachable"))
    two = dispatch_open(state, "row-2")
    state = open_callback(two.state, two.effects[0], Outcome("unknown_after_dispatch"))
    for row_ids in ((), ("row-2",), ("row-3",), ("row-1", "row-2")):
        with pytest.raises(UnsupportedContract):
            reduce_open_networks(state, DiscoveryAction("retry", row_ids))
    retried = reduce_open_networks(state, DiscoveryAction("retry", ("row-1",)))
    assert retried.effects == ()
    sent = dispatch_open(retried.state, "row-1")
    assert sent.effects[0].token.attempt == 2
    assert sent.effects[0].token != one.effects[0].token
    late = open_callback(sent.state, one.effects[0], Outcome("accepted"))
    assert late.rows[0].phase == "open_dispatched"
    assert not late.journal[-1].presented
    assert late.journal[-1].reason == "stale_attempt"
    assert late.rows[1].attempt == 1


def test_uncertain_open_after_stop_retains_late_evidence_without_replay():
    sent = dispatch_open(new_open_networks(context(), opening_rows()), "row-1")
    state = reduce_open_networks(sent.state, DiscoveryAction("stop")).state
    state = open_callback(state, sent.effects[0], Outcome("accepted"))
    assert state.rows[0].phase == "unknown_after_dispatch"
    assert not state.journal[-1].presented
    assert state.journal[-1].reason == "stopped_after_dispatch"
    with pytest.raises(UnsupportedContract):
        reduce_open_networks(state, DiscoveryAction("retry", ("row-1",)))


def test_open_ready_duplicate_and_close_are_idempotent():
    sent = dispatch_open(new_open_networks(context(), opening_rows()), "row-1")
    state = open_callback(sent.state, sent.effects[0], Outcome("accepted"))
    ready = Outcome("independently_ready", independent=True)
    state = open_callback(state, sent.effects[0], ready)
    duplicate = open_callback(state, sent.effects[0], ready)
    assert duplicate.rows == state.rows
    assert duplicate.journal[-1].reason == "duplicate_terminal"
    closed = reduce_open_networks(state, DiscoveryAction("close")).state
    assert reduce_open_networks(closed, DiscoveryAction("close")).state is closed
    late = open_callback(closed, sent.effects[0], Outcome("accepted"))
    assert late.closed and not late.journal[-1].presented


def test_cl1_focus_before_dispatch_cancels_captured_a_and_b_uses_b_identity():
    state = select(new_session(context()))
    state = reduce_session(state, SessionAction("schedule", operation_id="A-focus", operation_kind="focus_refresh")).state
    state = select(state, "B", "//B/254/p/1", 2)
    assert state.operations[0].phase == "cancelled_before_dispatch"
    with pytest.raises(UnsupportedContract):
        reduce_session(state, SessionAction("dispatch", operation_id="A-focus"))
    state = project_selected(state)
    dispatched = session_request(state, "B-focus", "focus_refresh")
    assert dispatched.effects[0].token.context.project == "B"
    assert dispatched.effects[0].token.context.object_identity == "//B/254/p/1"


def test_cl1_a_callback_after_b_focus_is_retained_and_frees_original_command():
    state = project_selected(select(new_session(context())))
    sent = session_request(state, "A-load", "load")
    state = select(sent.state, "B", "//B/254/p/1", 2)
    state = session_callback(state, sent.effects[0])
    assert state.context.project == "B"
    assert state.project_confirmed is None
    assert not state.journal[-1].presented
    assert state.journal[-1].reason == "selection_generation_mismatch"
    assert state.operations[-1].phase == "completed"
    b_project = session_request(state, "B-project", "project_use")
    assert b_project.effects[0].token.context.project == "B"


def test_same_client_project_use_requires_exact_200_before_dependent_work():
    state = select(new_session(context()))
    state = reduce_session(state, SessionAction("schedule", operation_id="load", operation_kind="load")).state
    with pytest.raises(UnsupportedContract):
        reduce_session(state, SessionAction("dispatch", operation_id="load"))
    use = session_request(state, "use", "project_use")
    with pytest.raises(UnsupportedContract):
        session_callback(use.state, use.effects[0], Outcome("completed", code=201))
    state = session_callback(use.state, use.effects[0], Outcome("completed", code=200))
    assert reduce_session(state, SessionAction("dispatch", operation_id="load")).effects[0].kind == "load"


def test_cl2_load_refresh_disconnect_preserves_dirty_snapshot_without_save():
    state = project_selected(select(new_session(context())))
    sent = session_request(state, "load", "load")
    state = reduce_session(sent.state, SessionAction("schedule", operation_id="refresh", operation_kind="focus_refresh")).state
    dirty = EditorSnapshot(state.context, b"synthetic unsaved editor")
    state = reduce_session(state, SessionAction("dirty_editor", editor=dirty)).state
    result = reduce_session(state, SessionAction("disconnect"))
    assert result.effects == ()
    assert result.state.detached_editors == (dirty,)
    assert result.state.dirty_editor is None
    assert [op.phase for op in result.state.operations[-2:]] == ["unknown_after_dispatch", "cancelled_before_dispatch"]
    late = session_callback(result.state, sent.effects[0])
    assert not late.journal[-1].presented and late.project_confirmed is None
    with pytest.raises(UnsupportedContract):
        reduce_session(late, SessionAction("save"))


@pytest.mark.parametrize("endpoint", ["fake://session-a", "fake://session-b"])
def test_cl3_reconnect_always_allocates_new_generation_and_rejects_colliding_selectors(endpoint):
    state = project_selected(select(new_session(context())))
    sent = session_request(state, "old-load", "load")
    state = reduce_session(sent.state, SessionAction("disconnect")).state
    state = reduce_session(state, SessionAction("reconnect", endpoint=endpoint)).state
    state = select(state)
    late = session_callback(state, sent.effects[0])
    assert not late.journal[-1].presented
    assert late.context.connection_generation > sent.effects[0].token.context.connection_generation
    assert late.context.endpoint == endpoint
    assert late.project_confirmed is None
    assert late.journal[-1].reason in ("endpoint_mismatch", "connection_generation_mismatch")


@pytest.mark.parametrize("operation_kind", ["focus_refresh", "group_refresh", "pp_refresh"])
def test_cl4_close_pending_callbacks_cannot_resurrect_and_repeat_close_is_idempotent(operation_kind):
    state = project_selected(select(new_session(context())))
    sent = session_request(state, "pending", operation_kind)
    state = reduce_session(sent.state, SessionAction("close")).state
    assert reduce_session(state, SessionAction("close")).state is state
    late = session_callback(state, sent.effects[0])
    duplicate = session_callback(late, sent.effects[0])
    assert duplicate.closed and not duplicate.connected
    assert duplicate.journal[-1].presented is False
    assert len(duplicate.operations) == len(state.operations)
    with pytest.raises(UnsupportedContract):
        reduce_session(duplicate, SessionAction("reconnect", endpoint="fake://session-a"))


def test_model_generation_and_forged_full_tokens_cannot_attach():
    state = project_selected(select(new_session(context())))
    sent = session_request(state, "load", "load")
    newer = replace(sent.state, context=replace(sent.state.context, model_generation=2))
    result = session_callback(newer, sent.effects[0])
    assert result.journal[-1].reason == "model_generation_mismatch"
    fake_token = replace(sent.effects[0].token, context=replace(sent.effects[0].token.context, flow_id="other-flow"))
    result = reduce_session(sent.state, SessionAction("callback", callback=Callback(fake_token, Outcome("completed")))).state
    assert result.journal[-1].reason == "unknown_token"
    assert result.operations[-1].phase == "dispatched"


def test_duplicate_terminal_callbacks_are_idempotent():
    sent = dispatch_scan(new_discovery(context(), Surface.COM_SCAN, rows()), "row-1")
    complete = scan_callback(sent.state, sent.effects[0], Outcome("present"))
    duplicate = scan_callback(complete, sent.effects[0], Outcome("present"))
    assert duplicate.rows == complete.rows
    assert duplicate.journal[-1].reason == "duplicate_terminal"


def test_callback_before_dispatch_never_confirms_project():
    state = select(new_session(context()))
    state = reduce_session(state, SessionAction("schedule", operation_id="use", operation_kind="project_use")).state
    callback = Callback(state.operations[0].token, Outcome("completed", code=200))
    result = reduce_session(state, SessionAction("callback", callback=callback)).state
    assert result.project_confirmed is None
    assert result.operations[0].phase == "scheduled"
    assert result.journal[-1].reason == "callback_before_dispatch"


def test_bound_exhaustion_is_explicit_and_cannot_silently_complete_or_dispatch():
    state = new_discovery(context(), Surface.COM_SCAN, rows(), journal_limit=1)
    sent = dispatch_scan(state, "row-1")
    state = scan_callback(sent.state, sent.effects[0], Outcome("present"))
    pending = dispatch_scan(state, "row-2")
    state = scan_callback(pending.state, pending.effects[0], Outcome("present"))
    assert state.evidence_incomplete and state.dropped_callbacks == 1
    assert len(state.journal) == 1
    assert state.rows[1].phase == "collecting"
    with pytest.raises(UnsupportedContract):
        dispatch_scan(state, "row-3")


def test_session_operation_cap_and_profile_gate():
    state = select(new_session(context(), operation_limit=1))
    state = reduce_session(state, SessionAction("schedule", operation_id="one", operation_kind="project_use")).state
    with pytest.raises(UnsupportedContract):
        reduce_session(state, SessionAction("schedule", operation_id="two", operation_kind="load"))
    for profile in ("native", "", "guessed-native-profile"):
        with pytest.raises(UnsupportedContract):
            new_session(context(), profile=profile)
        with pytest.raises(UnsupportedContract):
            new_discovery(context(), Surface.COM_SCAN, rows(), profile=profile)
    assert state.profile == LOCAL_PROFILE


@pytest.mark.parametrize("field", ["connection_generation", "selection_generation", "model_generation", "form_generation"])
def test_token_generations_require_nonnegative_integers(field):
    with pytest.raises(ValueError):
        replace(context(), **{field: True})


def test_row_preflight_and_bound_validation():
    with pytest.raises(ValueError):
        new_discovery(context(), Surface.CNI_SCAN, tuple(RowSpec(f"r{n}", f"fake://{n}") for n in range(17)))
    with pytest.raises(ValueError):
        new_discovery(context(), Surface.CNI_SCAN, (RowSpec("a", "fake://a", window_seconds=200), RowSpec("b", "fake://b", window_seconds=200)))
    with pytest.raises(ValueError):
        new_open_networks(context(), rows())
    with pytest.raises(ValueError):
        new_discovery(context(), Surface.COM_SCAN, (rows()[0], rows()[0]))
    with pytest.raises(ValueError):
        new_discovery(context(), Surface.COM_SCAN, rows(), journal_limit=True)


def test_frozen_snapshots_and_fake_adapter_prevent_caller_mutation():
    state = select(new_session(context()))
    dirty = EditorSnapshot(state.context, b"immutable")
    with pytest.raises(ValueError):
        EditorSnapshot(state.context, bytearray(b"mutable"))
    with pytest.raises(FrozenInstanceError):
        dirty.payload = b"changed"
    with pytest.raises(ValueError):
        ScriptedFakeAdapter([Outcome("present")])
    fake = ScriptedFakeAdapter((Outcome("present"),))
    sent = dispatch_scan(new_discovery(context(), Surface.COM_SCAN, rows()), "row-1")
    assert fake.observe(sent.effects[0], 0).token == sent.effects[0].token


def test_zero_io_histories(monkeypatch):
    def prohibited(*args, **kwargs):
        raise AssertionError("Pure preparation must not perform I/O")

    monkeypatch.setattr(builtins, "open", prohibited)
    monkeypatch.setattr(socket, "socket", prohibited)
    monkeypatch.setattr(socket, "create_connection", prohibited)
    state = new_discovery(context(), Surface.COM_SCAN, rows())
    sent = dispatch_scan(state, "row-1")
    state = scan_callback(sent.state, sent.effects[0], Outcome("present"))
    state = reduce_discovery(state, DiscoveryAction("com_cancel")).state
    shell = project_selected(select(new_session(context())))
    shell = reduce_session(shell, SessionAction("close")).state
    for model in (state, shell):
        assert model.preparation_only and not model.io_performed
        assert not model.native_manual_executed and not model.hardware_executed


@pytest.mark.parametrize("field,value", [
    ("rows", []), ("journal", []), ("active_at_pause", []), ("actions", []),
    ("native_manual_executed", True), ("hardware_executed", True), ("io_performed", True),
    ("preparation_only", False), ("absence_proven", True), ("journal_limit", True),
])
def test_discovery_state_cannot_accept_mutability_or_execution_authority(field, value):
    state = new_discovery(context(), Surface.COM_SCAN, rows())
    with pytest.raises(ValueError):
        replace(state, **{field: value})


@pytest.mark.parametrize("field,value", [
    ("operations", []), ("journal", []), ("detached_editors", []),
    ("native_manual_executed", True), ("hardware_executed", True), ("io_performed", True),
    ("preparation_only", False), ("operation_limit", True), ("context", {}),
])
def test_session_state_cannot_accept_mutability_or_execution_authority(field, value):
    state = new_session(context())
    with pytest.raises(ValueError):
        replace(state, **{field: value})


def test_new_discovery_requires_exact_context_and_surface_enum():
    with pytest.raises(ValueError):
        new_discovery(context(), Surface.COM_SCAN.value, rows())
    with pytest.raises(ValueError):
        new_discovery({}, Surface.COM_SCAN, rows())


@pytest.mark.parametrize("kind", ["refused", "unreachable", "unknown_after_dispatch"])
def test_accepted_open_cannot_be_overwritten_by_conflicting_terminal(kind):
    sent = dispatch_open(new_open_networks(context(), opening_rows()), "row-1")
    accepted = open_callback(sent.state, sent.effects[0], Outcome("accepted"))
    result = open_callback(accepted, sent.effects[0], Outcome(kind))
    assert result.rows[0] == accepted.rows[0]
    assert not result.journal[-1].presented
    assert result.journal[-1].reason == "conflicting_terminal"


def test_same_connection_transport_failure_invalidates_session_even_after_focus_change():
    state = project_selected(select(new_session(context())))
    sent = session_request(state, "A-load", "load")
    state = select(sent.state, "B", "//B/254/p/1", 2)
    result = session_callback(state, sent.effects[0], Outcome("transport_error"))
    assert not result.connected
    assert result.context.project == "B"
    assert result.context.connection_generation > sent.effects[0].token.context.connection_generation
    assert not result.journal[-1].presented
    assert result.operations[-1].phase == "unknown_after_dispatch"


def test_old_connection_failure_does_not_invalidate_new_connection():
    state = project_selected(select(new_session(context())))
    sent = session_request(state, "old-load", "load")
    state = reduce_session(sent.state, SessionAction("disconnect")).state
    state = reduce_session(state, SessionAction("reconnect", endpoint="fake://session-a")).state
    result = session_callback(state, sent.effects[0], Outcome("transport_error"))
    assert result.connected
    assert result.context.connection_generation == state.context.connection_generation
    assert not result.journal[-1].presented


def test_session_journal_overflow_never_accepts_unretained_completion():
    state = project_selected(select(new_session(context(), journal_limit=1)))
    sent = session_request(state, "load", "load")
    result = session_callback(sent.state, sent.effects[0])
    assert result.evidence_incomplete and result.dropped_callbacks == 1
    assert result.operations[-1].phase == "dispatched"
    assert result.operations[-1].terminal is None
    assert len(result.journal) == 1


def test_lifecycle_action_journal_is_bounded():
    sent = dispatch_open(new_open_networks(context(), opening_rows(), journal_limit=1), "row-1")
    state = open_callback(sent.state, sent.effects[0], Outcome("refused"))
    state = reduce_open_networks(state, DiscoveryAction("stop")).state
    state = reduce_open_networks(state, DiscoveryAction("retry", ("row-1",))).state
    assert state.evidence_incomplete and len(state.actions) == 1
    with pytest.raises(UnsupportedContract):
        dispatch_open(state, "row-1")
