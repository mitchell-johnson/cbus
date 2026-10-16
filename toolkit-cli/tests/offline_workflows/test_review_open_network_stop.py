"""PR78 regression: Retry of one row cannot revive another stopped attempt."""
from dataclasses import replace
import json
import socket

import pytest

from cbus_toolkit import cli
from cbus_toolkit.offline_workflows.discovery_session import (
    Callback, Context, DiscoveryAction, Outcome, RowSpec, UnsupportedContract,
    new_open_networks, reduce_open_networks,
)
from cbus_toolkit.offline_workflows.discovery_session_input import INPUT_FORMAT, evaluate


LATE_OUTCOMES = ("accepted", "refused", "unreachable")
SURFACE = "open_networks"


def stopped_two_rows():
    state = new_open_networks(Context("review-flow", "review-form", "fake://client"), (
        RowSpec("A", "fake://A", "SYNTHETIC", "//SYNTHETIC/A"),
        RowSpec("B", "fake://B", "SYNTHETIC", "//SYNTHETIC/B"),
    ))
    first = reduce_open_networks(state, DiscoveryAction("dispatch", ("A",)))
    refused = reduce_open_networks(first.state, DiscoveryAction("callback", callback=Callback(
        first.effects[0].token, Outcome("refused")))).state
    pending = reduce_open_networks(refused, DiscoveryAction("dispatch", ("B",)))
    stopped = reduce_open_networks(pending.state, DiscoveryAction("stop")).state
    resumed = reduce_open_networks(stopped, DiscoveryAction("retry", ("A",))).state
    return resumed, first.effects[0], pending.effects[0]


@pytest.mark.parametrize("outcome", LATE_OUTCOMES)
def test_retry_refused_a_cannot_present_reclassify_or_replay_stopped_b(outcome):
    resumed, _, pending_b = stopped_two_rows()
    assert not resumed.stopped
    assert [row.phase for row in resumed.rows] == ["queued", "unknown_after_dispatch"]
    assert resumed.rows[1].stopped_tokens == (pending_b.token,)
    late = Callback(pending_b.token, Outcome(outcome))
    result = reduce_open_networks(resumed, DiscoveryAction("callback", callback=late))
    assert result.effects == ()
    assert result.state.rows == resumed.rows
    assert result.state.rows[1].terminal is None
    assert result.state.journal[-1].callback == late
    assert not result.state.journal[-1].presented
    assert result.state.journal[-1].reason == "stopped_after_dispatch"
    with pytest.raises(UnsupportedContract):
        reduce_open_networks(result.state, DiscoveryAction("retry", ("B",)))
    with pytest.raises(UnsupportedContract):
        reduce_open_networks(result.state, DiscoveryAction("dispatch", ("B",)))
    assert result.state.preparation_only
    assert not result.state.io_performed
    assert not result.state.native_manual_executed
    assert not result.state.hardware_executed


@pytest.mark.parametrize("outcome", LATE_OUTCOMES)
def test_stop_binding_survives_actual_fresh_retry_a_dispatch_and_duplicate_b_receipts(outcome):
    resumed, first_a, pending_b = stopped_two_rows()
    retry_a = reduce_open_networks(resumed, DiscoveryAction("dispatch", ("A",)))
    assert retry_a.effects[0].token.attempt == 2
    assert retry_a.effects[0].token != first_a.token
    late = Callback(pending_b.token, Outcome(outcome))
    state = retry_a.state
    for _ in range(2):
        state = reduce_open_networks(state, DiscoveryAction("callback", callback=late)).state
    assert [row.phase for row in state.rows] == ["open_dispatched", "unknown_after_dispatch"]
    assert state.rows[1].stopped_tokens == (pending_b.token,)
    assert all(record.callback == late and not record.presented
               and record.reason == "stopped_after_dispatch" for record in state.journal[-2:])
    assert state.rows[0].tokens[-1] == retry_a.effects[0].token
    accepted_a = reduce_open_networks(state, DiscoveryAction("callback", callback=Callback(
        retry_a.effects[0].token, Outcome("accepted")))).state
    assert accepted_a.rows[0].phase == "accepted"
    assert accepted_a.journal[-1].presented
    assert accepted_a.rows[1] == state.rows[1]


def context(endpoint="fake://client", project=None, object_identity=None):
    return {"flow_id": "review-flow", "form_instance": "review-form", "endpoint": endpoint,
            "connection_generation": 0, "selection_generation": 0, "project": project,
            "object_identity": object_identity, "model_generation": 0, "form_generation": 0}


def callback(row_id, outcome):
    return {"kind": "callback", "issue_id": f"open-{row_id}",
            "token": {"context": context(f"fake://{row_id}", "SYNTHETIC", f"//SYNTHETIC/{row_id}"),
                      "surface": SURFACE, "operation_id": f"{row_id}:1", "row_id": row_id, "attempt": 1},
            "outcome": {"kind": outcome, "detail": "Synthetic PR78 stop/Retry regression",
                        "terminal": True, "independent": False, "code": None}}


def document(outcome, *, retry_b=False):
    actions = [
        {"kind": "dispatch", "issue_id": "open-A", "row_ids": ["A"]}, callback("A", "refused"),
        {"kind": "dispatch", "issue_id": "open-B", "row_ids": ["B"]}, {"kind": "stop"},
        {"kind": "retry", "row_ids": ["A"]}, callback("B", outcome),
    ]
    if retry_b:
        actions += [{"kind": "retry", "row_ids": ["B"]},
                    {"kind": "dispatch", "issue_id": "replayed-B", "row_ids": ["B"]}]
    return {"format": INPUT_FORMAT, "surface": SURFACE, "context": context(),
            "rows": [{"row_id": row_id, "endpoint": f"fake://{row_id}", "project": "SYNTHETIC",
                      "object_identity": f"//SYNTHETIC/{row_id}", "window_seconds": 2} for row_id in ("A", "B")],
            "actions": actions}


@pytest.mark.parametrize("outcome", LATE_OUTCOMES)
def test_adapter_plan_preserves_uncertainty_and_refuses_retry_stopped_b(outcome):
    result = evaluate(document(outcome), "plan")
    assert result["validation_passed"] and result["outcome"] == "uncertain"
    assert result["state"]["rows"][1]["phase"] == "unknown_after_dispatch"
    assert result["state"]["journal"][-1]["reason"] == "stopped_after_dispatch"
    assert not result["state"]["journal"][-1]["presented"]
    assert len(result["issued_operations"]) == len(result["effects"]) == 2
    assert result["effects"][1]["token"] == callback("B", outcome)["token"]
    refused = evaluate(document(outcome, retry_b=True), "plan")
    assert not refused["validation_passed"] and refused["outcome"] == "unsupported"
    assert refused["error"]["action_index"] == 6
    assert refused["state"]["rows"][1]["phase"] == "unknown_after_dispatch"
    assert len(refused["effects"]) == 2
    assert not refused["io_performed"] and not refused["native_manual_executed"] and not refused["hardware_executed"]


@pytest.mark.parametrize("outcome", LATE_OUTCOMES)
@pytest.mark.parametrize("retry_b", (False, True))
def test_public_plan_keeps_status_three_and_only_original_effects(tmp_path, capsys, monkeypatch, outcome, retry_b):
    def prohibited(*args, **kwargs):
        raise AssertionError("Offline stop/Retry regression must not open a backend")
    monkeypatch.setattr(socket, "socket", prohibited)
    monkeypatch.setattr(socket, "create_connection", prohibited)
    source = tmp_path.resolve() / "stop-retry.json"
    source.write_text(json.dumps(document(outcome, retry_b=retry_b)), encoding="utf-8")
    status = cli.main(["offline-workflows", "discovery-session", "plan", "--input", str(source), "--compact"])
    captured = capsys.readouterr()
    assert status == 3 and captured.err == ""
    envelope = json.loads(captured.out)
    result = envelope["report"]
    assert result["outcome"] == ("unsupported" if retry_b else "uncertain")
    assert result["state"]["rows"][1]["phase"] == "unknown_after_dispatch"
    assert result["state"]["journal"][-1]["reason"] == "stopped_after_dispatch"
    assert not result["state"]["journal"][-1]["presented"]
    assert len(result["effects"]) == 2
    assert envelope["execution_enabled"] is False and envelope["native_execution_enabled"] is False
    assert not result["io_performed"] and not result["hardware_executed"] and not result["native_manual_executed"]


def test_stopped_attempt_history_is_immutable_unique_and_row_owned():
    resumed, first_a, pending_b = stopped_two_rows()
    stopped_b = resumed.rows[1]
    for invalid in ([pending_b.token], (first_a.token,), (pending_b.token, pending_b.token)):
        with pytest.raises(ValueError):
            replace(stopped_b, stopped_tokens=invalid)
    assert replace(stopped_b, stopped_tokens=(pending_b.token,)) == stopped_b



def test_repeated_stop_marks_new_a_attempt_without_erasing_stopped_b():
    resumed, _, pending_b = stopped_two_rows()
    retry_a = reduce_open_networks(resumed, DiscoveryAction("dispatch", ("A",)))
    stopped = reduce_open_networks(retry_a.state, DiscoveryAction("stop")).state
    assert [row.phase for row in stopped.rows] == ["unknown_after_dispatch", "unknown_after_dispatch"]
    assert stopped.rows[0].stopped_tokens == (retry_a.effects[0].token,)
    assert stopped.rows[1].stopped_tokens == (pending_b.token,)
    assert reduce_open_networks(stopped, DiscoveryAction("stop")).state is stopped
    for effect in (retry_a.effects[0], pending_b):
        late = reduce_open_networks(stopped, DiscoveryAction("callback", callback=Callback(effect.token, Outcome("refused")))).state
        assert late.rows == stopped.rows
        assert not late.journal[-1].presented and late.journal[-1].reason == "stopped_after_dispatch"
        with pytest.raises(UnsupportedContract):
            reduce_open_networks(late, DiscoveryAction("retry", (effect.token.row_id,)))


def test_stopped_b_keeps_original_scope_when_connection_generation_changes():
    resumed, _, pending_b = stopped_two_rows()
    newer = replace(resumed, context=replace(resumed.context, connection_generation=1))
    result = reduce_open_networks(newer, DiscoveryAction("callback", callback=Callback(pending_b.token, Outcome("accepted")))).state
    assert result.rows == newer.rows
    assert result.rows[1].stopped_tokens == (pending_b.token,)
    assert result.journal[-1].callback.token == pending_b.token
    assert not result.journal[-1].presented
    assert result.journal[-1].reason == "connection_generation_mismatch"


def test_stopped_attempts_remain_unknown_when_late_evidence_hits_journal_bound():
    resumed, _, pending_b = stopped_two_rows()
    state = replace(resumed, journal_limit=2)
    late = Callback(pending_b.token, Outcome("unreachable"))
    state = reduce_open_networks(state, DiscoveryAction("callback", callback=late)).state
    assert not state.journal[-1].presented
    state = reduce_open_networks(state, DiscoveryAction("callback", callback=late)).state
    assert state.evidence_incomplete and state.dropped_callbacks == 1 and len(state.journal) == 2
    assert state.rows[1].phase == "unknown_after_dispatch" and state.rows[1].terminal is None
    assert state.rows[1].stopped_tokens == (pending_b.token,)
    with pytest.raises(UnsupportedContract):
        reduce_open_networks(state, DiscoveryAction("retry", ("B",)))



def test_constructor_cannot_erase_stop_binding_to_revive_unknown_b_callback():
    resumed, _, pending_b = stopped_two_rows()
    stopped_b = resumed.rows[1]
    with pytest.raises(ValueError, match="retain its latest stopped attempt"):
        replace(stopped_b, stopped_tokens=())
    assert stopped_b.stopped_tokens == (pending_b.token,)
    assert stopped_b.phase == "unknown_after_dispatch" and stopped_b.terminal is None


@pytest.mark.parametrize("change", [
    {"phase": "queued"},
    {"phase": "accepted", "terminal": Outcome("accepted")},
    {"terminal": Outcome("unknown_after_dispatch")},
])
def test_constructor_cannot_reclassify_latest_stopped_attempt(change):
    resumed, _, _ = stopped_two_rows()
    with pytest.raises(ValueError, match="must remain unknown"):
        replace(resumed.rows[1], **change)


def test_explicit_unknown_receipt_without_stop_does_not_require_stopped_token():
    state = new_open_networks(Context("genuine-unknown-flow", "genuine-unknown-form", "fake://client"), (
        RowSpec("A", "fake://A", "SYNTHETIC", "//SYNTHETIC/A"),
    ))
    dispatched = reduce_open_networks(state, DiscoveryAction("dispatch", ("A",)))
    unknown = reduce_open_networks(dispatched.state, DiscoveryAction("callback", callback=Callback(
        dispatched.effects[0].token, Outcome("unknown_after_dispatch")))).state
    assert unknown.rows[0].phase == "unknown_after_dispatch"
    assert unknown.rows[0].terminal == Outcome("unknown_after_dispatch")
    assert unknown.rows[0].stopped_tokens == ()
    assert replace(unknown.rows[0], stopped_tokens=()) == unknown.rows[0]
    with pytest.raises(UnsupportedContract):
        reduce_open_networks(unknown, DiscoveryAction("retry", ("A",)))
