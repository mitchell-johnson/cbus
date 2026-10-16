"""File-shaped synthetic histories. No native/runtime/hardware acceptance."""
from copy import deepcopy
import builtins
import json
from pathlib import Path
import socket
import time

import pytest

from cbus_toolkit.offline_workflows.cli_support import InputError
from cbus_toolkit.offline_workflows.discovery_session_input import (
    INPUT_FORMAT, MAX_ACTIONS, evaluate,
)

COM = "discover_project_com_scan"
CNI = "discover_project_cni_project_scan"
NETWORK = "scan_network_progress"
OPEN = "open_networks"
SHELL = "ordinary_client_session"


def context(*, endpoint="fake://client", project=None, object_identity=None,
            connection_generation=0, selection_generation=0, model_generation=0):
    return {
        "flow_id": "synthetic-flow", "form_instance": "synthetic-form", "endpoint": endpoint,
        "connection_generation": connection_generation, "selection_generation": selection_generation,
        "project": project, "object_identity": object_identity, "model_generation": model_generation,
        "form_generation": 0,
    }


def row(row_id, endpoint=None, *, opening=False):
    return {"row_id": row_id, "endpoint": endpoint or f"fake://{row_id}",
            "project": "PROJECT" if opening else None,
            "object_identity": f"//PROJECT/{row_id}" if opening else None,
            "window_seconds": 2}


def token(surface, operation_id, row_id=None, *, attempt=1, captured=None):
    return {"surface": surface, "operation_id": operation_id, "row_id": row_id or operation_id,
            "attempt": attempt, "context": captured or context()}


def callback(issue_id, captured_token, kind="present", *, code=None, independent=False):
    return {"kind": "callback", "issue_id": issue_id, "token": captured_token,
            "outcome": {"kind": kind, "detail": "synthetic observation", "terminal": True,
                        "independent": independent, "code": code}}


def document(surface=COM, *, actions=None, selected_rows=None):
    result = {"format": INPUT_FORMAT, "surface": surface, "context": context(), "actions": actions or []}
    if surface != SHELL:
        result["rows"] = selected_rows or [row("one", opening=surface == OPEN), row("two", opening=surface == OPEN)]
    return result


def scan_dispatch(row_id="one", issue_id="issue-one"):
    return {"kind": "dispatch", "issue_id": issue_id, "row_ids": [row_id]}


def scan_token(row_id="one", surface=COM, *, attempt=1):
    return token(surface, f"{row_id}:{attempt}", row_id, attempt=attempt,
                 captured=context(endpoint=f"fake://{row_id}", project="PROJECT" if surface == OPEN else None,
                                  object_identity=f"//PROJECT/{row_id}" if surface == OPEN else None))


def session_selection(project="A", generation=1):
    return {"kind": "select", "project": project, "object_identity": f"//{project}/254/p/1", "model_generation": generation}


def selected_context(project="A", generation=1, *, connection_generation=0):
    return context(project=project, object_identity=f"//{project}/254/p/1", selection_generation=generation,
                   model_generation=generation, connection_generation=connection_generation)


def session_schedule(operation_id, operation_kind):
    return {"kind": "schedule", "operation_id": operation_id, "operation_kind": operation_kind}


def session_dispatch(operation_id, issue_id):
    return {"kind": "dispatch", "operation_id": operation_id, "issue_id": issue_id}


def project_use_actions():
    return [session_selection(), session_schedule("use-A", "project_use"), session_dispatch("use-A", "use-A-issue"),
            callback("use-A-issue", token(SHELL, "use-A", captured=selected_context()), "completed", code=200)]


def assert_authority_false(result):
    assert result["preparation_only"] is True
    for field in ("native_manual_executed", "hardware_executed", "io_performed", "physical_io_executed",
                  "runtime_executed", "native_compatible", "product_integrated"):
        assert result[field] is False


@pytest.mark.parametrize("operation", ["validate", "plan"])
def test_com_cancel_preserves_completed_and_late_callback_receipts(operation):
    actions = [scan_dispatch(), callback("issue-one", scan_token()), scan_dispatch("two", "issue-two"),
               {"kind": "com_cancel"}, callback("issue-two", scan_token("two"))]
    result = evaluate(document(actions=actions), operation)
    assert result["validation_passed"] is True and result["outcome"] == "cancelled"
    assert [item["phase"] for item in result["state"]["rows"]] == ["completed", "interrupted"]
    assert result["state"]["journal"][-1]["reason"] == "cancelled_result"
    assert result["observations"][-1]["retained_records"][0]["presented"] is False
    assert [entry["issue_id"] for entry in result["issued_operations"]] == ["issue-one", "issue-two"]
    assert result["effects"][1]["token"] == scan_token("two")
    assert_authority_false(result)
    json.dumps(result, allow_nan=False)


def test_inspect_parses_history_but_does_not_replay_dispatch_cancel_or_callback():
    source = document(actions=[scan_dispatch(), {"kind": "com_cancel"}, callback("issue-one", scan_token())])
    result = evaluate(source, "inspect")
    assert result["outcome"] == "inspected" and result["validation_passed"] is True
    assert result["summary"]["timeline_replayed"] is False
    assert result["effects"] == result["issued_operations"] == result["observations"] == result["action_history"] == []
    assert [item["phase"] for item in result["state"]["rows"]] == ["queued", "queued"]
    assert len(result["summary"]["parsed_actions"]) == 3
    assert_authority_false(result)


@pytest.mark.parametrize("surface,action", [(COM, "cni_pause"), (CNI, "com_cancel"), (NETWORK, "com_cancel"), (OPEN, "com_cancel")])
def test_wrong_surface_handlers_remain_unsupported(surface, action):
    result = evaluate(document(surface, actions=[{"kind": action}]), "plan")
    assert not result["validation_passed"] and result["outcome"] == "unsupported"
    assert result["effects"] == [] and result["error"]["action_index"] == 0
    assert_authority_false(result)


def test_callback_cannot_claim_another_surface_or_generation():
    for field, value in (("surface", CNI), ("attempt", 2)):
        captured = scan_token()
        captured[field] = value
        with pytest.raises(InputError):
            evaluate(document(actions=[scan_dispatch(), callback("issue-one", captured)]), "plan")
    captured = scan_token()
    captured["context"]["connection_generation"] = 1
    with pytest.raises(InputError):
        evaluate(document(actions=[scan_dispatch(), callback("issue-one", captured)]), "validate")


def test_same_selector_focus_stale_original_token_is_retained_without_b_attachment():
    actions = project_use_actions() + [session_schedule("load-A", "load"), session_dispatch("load-A", "load-A-issue"),
                                     session_selection("B", 2),
                                     callback("load-A-issue", token(SHELL, "load-A", captured=selected_context()), "completed")]
    result = evaluate(document(SHELL, actions=actions), "plan")
    assert result["validation_passed"] is True
    assert result["state"]["context"]["project"] == "B"
    assert result["state"]["project_confirmed"] is None
    assert result["state"]["journal"][-1]["reason"] == "selection_generation_mismatch"
    assert result["state"]["operations"][-1]["phase"] == "completed"
    assert not result["state"]["journal"][-1]["presented"]
    assert_authority_false(result)


def test_dirty_editor_disconnect_reconnect_retains_snapshot_and_rejects_old_generation():
    dirty_hex = b"synthetic unsaved editor".hex()
    actions = project_use_actions() + [session_schedule("load-A", "load"), session_dispatch("load-A", "load-issue"),
                                     {"kind": "dirty_editor", "editor": {"context": selected_context(), "payload_hex": dirty_hex}},
                                     {"kind": "disconnect"}, {"kind": "reconnect", "endpoint": "fake://client"},
                                     callback("load-issue", token(SHELL, "load-A", captured=selected_context()), "completed")]
    result = evaluate(document(SHELL, actions=actions), "plan")
    assert result["state"]["connected"] is True
    assert result["state"]["dirty_editor"] is None
    assert result["state"]["detached_editors"][0]["payload"] == {"hex": dirty_hex, "byte_count": len(bytes.fromhex(dirty_hex))}
    assert result["state"]["journal"][-1]["reason"] == "connection_generation_mismatch"
    assert result["state"]["project_confirmed"] is None
    assert [effect["kind"] for effect in result["effects"]] == ["project_use", "load"]
    assert_authority_false(result)


def test_unknown_open_stop_and_retry_never_replay_uncertain_rows():
    source = document(OPEN, actions=[scan_dispatch(), {"kind": "stop"}, callback("issue-one", scan_token(surface=OPEN), "accepted")])
    result = evaluate(source, "plan")
    assert result["validation_passed"] and result["outcome"] == "uncertain"
    assert result["state"]["rows"][0]["phase"] == "unknown_after_dispatch"
    assert result["state"]["journal"][-1]["reason"] == "stopped_after_dispatch"
    source["actions"].append({"kind": "retry", "row_ids": ["one"]})
    result = evaluate(source, "plan")
    assert not result["validation_passed"] and result["outcome"] == "unsupported"
    assert len(result["effects"]) == 1


def test_open_acknowledgement_requires_separate_user_supplied_independent_observation():
    source = document(OPEN, actions=[scan_dispatch(), callback("issue-one", scan_token(surface=OPEN), "accepted"),
                                   callback("issue-one", scan_token(surface=OPEN), "independently_ready", independent=True)])
    result = evaluate(source, "plan")
    assert result["state"]["rows"][0]["phase"] == "independently_ready"
    assert result["observation_assertions_source"] == "user_supplied_synthetic"
    assert_authority_false(result)
    source["actions"][-1]["outcome"]["independent"] = False
    result = evaluate(source, "plan")
    assert not result["validation_passed"] and result["state"]["rows"][0]["phase"] == "accepted"


def test_cni_pause_retains_active_deadline_disposition_without_absence_claim():
    source = document(CNI, actions=[scan_dispatch(), {"kind": "cni_pause"},
                                  callback("issue-one", scan_token(surface=CNI), "no_reply_by_deadline")])
    result = evaluate(source, "plan")
    assert result["state"]["paused"] and not result["state"]["absence_proven"]
    assert result["state"]["rows"][0]["terminal"]["kind"] == "no_reply_by_deadline"
    assert result["effects"][0]["window_seconds"] == 2
    source["actions"].append({"kind": "resume"})
    unsupported = evaluate(source, "plan")
    assert unsupported["outcome"] == "unsupported" and unsupported["effects"] == []


def test_overflow_reports_incompleteness_without_silently_presenting_dropped_callback():
    source = document(actions=[scan_dispatch(), callback("issue-one", scan_token()),
                               scan_dispatch("two", "issue-two"), callback("issue-two", scan_token("two"))])
    source["journal_limit"] = 1
    result = evaluate(source, "plan")
    assert result["outcome"] == "uncertain" and result["summary"]["evidence_incomplete"]
    assert result["summary"]["dropped_callbacks"] == 1
    assert result["observations"][-1]["retained_records"] == []
    assert result["state"]["rows"][1]["phase"] == "collecting"


@pytest.mark.parametrize("profile", ["native", "invented-v2"])
def test_unknown_profile_is_unsupported_without_any_effects(profile):
    source = document(actions=[scan_dispatch()])
    source["profile"] = profile
    result = evaluate(source, "plan")
    assert result["outcome"] == "unsupported" and not result["validation_passed"]
    assert result["state"] is None and result["effects"] == []
    assert_authority_false(result)


@pytest.mark.parametrize("mutation", [
    lambda value: value.update({"runtime_executed": True}),
    lambda value: value["context"].update({"connection_generation": True}),
    lambda value: value["context"].pop("selection_generation"),
    lambda value: value["rows"][0].update({"window_seconds": float("nan")}),
    lambda value: value.update({"journal_limit": 0}),
    lambda value: value.update({"operation_limit": 1}),
    lambda value: value["rows"][0].update({"native_identity_verified": True}),
])
def test_strict_schema_rejects_missing_unknown_invalid_and_authority_fields(mutation):
    source = document()
    mutation(source)
    with pytest.raises(InputError):
        evaluate(source, "validate")


def test_callbacks_require_prior_unique_issue_references_and_complete_tokens():
    with pytest.raises(InputError):
        evaluate(document(actions=[callback("unissued", scan_token())]), "inspect")
    with pytest.raises(InputError):
        evaluate(document(actions=[scan_dispatch(), scan_dispatch("two", "issue-one")]), "inspect")
    incomplete = scan_token()
    incomplete["context"].pop("form_generation")
    with pytest.raises(InputError):
        evaluate(document(actions=[scan_dispatch(), callback("issue-one", incomplete)]), "inspect")


def test_invalid_editor_snapshot_is_rejected_or_locally_refused():
    actions = [session_selection(), {"kind": "dirty_editor", "editor": {"context": selected_context(), "payload_hex": "123"}}]
    with pytest.raises(InputError):
        evaluate(document(SHELL, actions=actions), "validate")
    actions[-1]["editor"]["payload_hex"] = "00"
    actions[-1]["editor"]["context"]["selection_generation"] = 0
    result = evaluate(document(SHELL, actions=actions), "plan")
    assert not result["validation_passed"] and result["outcome"] == "refused"
    assert result["state"]["dirty_editor"] is None


def test_actions_are_bounded_and_empty_discovery_rows_are_rejected():
    with pytest.raises(InputError):
        evaluate(document(actions=[{"kind": "close"}] * (MAX_ACTIONS + 1)), "inspect")
    source = document()
    source["rows"] = []
    with pytest.raises(InputError):
        evaluate(source, "inspect")


def test_evaluate_does_not_mutate_input_and_returns_independent_json_data():
    source = document(actions=[scan_dispatch(), callback("issue-one", scan_token())])
    original = deepcopy(source)
    result = evaluate(source, "plan")
    assert source == original
    result["issued_operations"][0]["effect"]["token"]["context"]["endpoint"] = "changed"
    assert source == original


def test_actual_package_example_is_meaningful_and_valid():
    example = Path(__file__).parents[2] / "src/cbus_toolkit/offline_workflows/examples/discovery-session.json"
    source = json.loads(example.read_text())
    result = evaluate(source, "plan")
    assert result["outcome"] == "cancelled" and result["validation_passed"]
    assert len(result["effects"]) == 2 and len(result["observations"]) == 2
    assert result["state"]["journal"][-1]["reason"] == "cancelled_result"
    assert_authority_false(result)


def test_evaluate_performs_no_files_clock_socket_or_adapter_io(monkeypatch):
    source = document(actions=[scan_dispatch(), callback("issue-one", scan_token()), {"kind": "com_cancel"}])
    def prohibited(*args, **kwargs):
        raise AssertionError("Input evaluation must remain pure")
    monkeypatch.setattr(builtins, "open", prohibited)
    monkeypatch.setattr(Path, "read_text", prohibited)
    monkeypatch.setattr(Path, "read_bytes", prohibited)
    monkeypatch.setattr(socket, "socket", prohibited)
    monkeypatch.setattr(socket, "create_connection", prohibited)
    monkeypatch.setattr(time, "monotonic", prohibited)
    monkeypatch.setattr(time, "sleep", prohibited)
    for operation in ("inspect", "validate", "plan"):
        result = evaluate(source, operation)
        assert_authority_false(result)
