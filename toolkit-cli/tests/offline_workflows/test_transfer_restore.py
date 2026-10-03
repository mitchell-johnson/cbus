"""Focused preparation contracts; no native, vendor, transport or file fixtures."""
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest

from cbus_toolkit.offline_workflows import transfer_restore as tr
from cbus_toolkit.label_transfer_plan import plan_transfer

SHA = "1" * 64
OTHER_SHA = "2" * 64
THIRD_SHA = "3" * 64


def unit(row_id="u1", **changes):
    values = dict(row_id=row_id, source_identity="source/" + row_id,
                  source_snapshot_sha256=SHA, destination_identity="destination/" + row_id,
                  destination_snapshot_sha256=OTHER_SHA, staged_data_sha256=THIRD_SHA,
                  source_address="0x01", serial="SERIAL-" + row_id, unit_type="KEY1",
                  firmware="1.2.67", route=("network-a", "network-b"),
                  destination_state="present", action="clear")
    values.update(changes)
    return tr.TransferRow(**values)


def project(row_id="p1", **changes):
    values = dict(row_id=row_id, member_identity="member/" + row_id,
                  source_project="OLD" if row_id == "p1" else "NEW",
                  source_snapshot_sha256=SHA)
    values.update(changes)
    return tr.RestoreProject(**values)


def restore(projects=None, **changes):
    values = dict(archive_sha256=SHA, destination_snapshot_sha256=OTHER_SHA,
                  destination_names=("OLD",))
    values.update(changes)
    return tr.prepare_restore([project()] if projects is None else projects, **values)


def codes(report):
    return {issue["code"] for issue in report.as_dict()["issues"]}


def assert_preparation(report):
    document = report.as_dict()
    assert document["execution_admitted"] is False
    assert document["preparation_only"] is True
    assert document["native_mutations"] == 0
    assert document["queue_commands"] == []
    assert document["original_workflow_verified"] is False
    assert document["automatic_replay_authorized"] is False
    assert type(report).from_dict(document).as_dict() == document


@pytest.mark.parametrize("action", ["add-only", "programming-only", "add-and-transfer"])
def test_each_advanced_action_freezes_only_intent_and_preserves_identities(action):
    row = unit(action=action)
    result = tr.prepare_advanced_transfer([row], [tr.AdvancedTransferEvent("accept")])
    document = result.as_dict()
    assert document["outcome"] == "unsupported"
    assert document["intent_frozen"] is True
    assert document["bindings"]["rows"] == [row.as_dict()]
    assert document["direction_binding"] is None
    assert "original_capture_required" in codes(result)
    assert_preparation(result)


def test_clear_reassign_retains_all_source_and_staged_bindings_and_unrelated_rows():
    rows = [unit(), unit("u2", action="programming-only")]
    history = [tr.AdvancedTransferEvent("choose-action", ["u1"], "add-and-transfer"),
               tr.AdvancedTransferEvent("clear-actions", ["u1"]),
               tr.AdvancedTransferEvent("choose-action", ["u1"], "add-only")]
    document = tr.prepare_advanced_transfer(rows, history).as_dict()
    assert document["bindings"]["rows"] == [row.as_dict() for row in rows]
    assert document["selected_actions"] == [{"row_id": "u1", "action": "add-only"},
                                             {"row_id": "u2", "action": "programming-only"}]
    assert document["clear_reassign_original_verified"] is False
    assert any(issue.get("contract") == "mixed_row_eligibility" for issue in document["issues"])


@pytest.mark.parametrize("destination_state", ["present", "absent", "mismatched", "unknown"])
def test_destination_observations_are_retained_without_guessed_row_outcomes(destination_state):
    result = tr.prepare_advanced_transfer([unit(action="add-only", destination_state=destination_state)])
    assert result.as_dict()["bindings"]["rows"][0]["destination_state"] == destination_state
    assert result.as_dict()["outcome"] == "unsupported"


def test_missing_programming_binding_is_uncertain_not_a_successful_noop():
    result = tr.prepare_advanced_transfer([unit(action="programming-only", staged_data_sha256=None)])
    assert result.as_dict()["outcome"] == "uncertain"
    assert "staged_data_binding_required" in codes(result)


def test_empty_clear_cancel_and_unsupported_are_distinct():
    assert tr.prepare_advanced_transfer([]).as_dict()["outcome"] == "not_applicable"
    assert tr.prepare_advanced_transfer([unit()]).as_dict()["outcome"] == "confirmed_noop"
    assert tr.prepare_advanced_transfer([unit(action="add-only")], [tr.AdvancedTransferEvent("cancel")]).as_dict()["outcome"] == "confirmed_noop"
    assert tr.prepare_advanced_transfer([unit(action="add-only")]).as_dict()["outcome"] == "unsupported"


@pytest.mark.parametrize("rows, match", [
    ([unit(), unit()], "Duplicate transfer row"),
    ([unit(), unit("u2", source_identity="source/u1")], "source identity"),
    ([unit(action="add-only"), unit("u2", action="add-only", destination_identity="destination/u1")], "destination identity"),
])
def test_advanced_ambiguous_rows_refused(rows, match):
    with pytest.raises(ValueError, match=match):
        tr.prepare_advanced_transfer(rows)


def test_clear_rows_do_not_invent_destination_collisions():
    result = tr.prepare_advanced_transfer([unit(), unit("u2", destination_identity="destination/u1")])
    assert result.as_dict()["outcome"] == "confirmed_noop"


def test_frozen_history_cannot_change_and_tampered_roundtrip_is_refused():
    result = tr.prepare_advanced_transfer([unit(action="add-only")], [tr.AdvancedTransferEvent("accept")])
    document = result.as_dict()
    document["bindings"]["rows"][0]["serial"] = "OTHER"
    with pytest.raises(ValueError, match="recomputed"):
        tr.AdvancedTransferPlan.from_dict(document)
    assert result.as_dict()["bindings"]["rows"][0]["serial"] == "SERIAL-u1"
    forged = result.as_dict()
    forged["execution_admitted"] = True
    with pytest.raises(ValueError, match="recomputed"):
        tr.AdvancedTransferPlan.from_dict(forged)
    with pytest.raises(ValueError, match="frozen"):
        tr.prepare_advanced_transfer([unit()], [tr.AdvancedTransferEvent("accept"),
                                              tr.AdvancedTransferEvent("clear-actions", ["u1"])])


def test_inputs_and_returned_nested_values_are_defensive_snapshots():
    route = ["A", "B"]
    row = unit(route=route)
    row_ids = ["u1"]
    event = tr.AdvancedTransferEvent("choose-action", row_ids, "add-only")
    route.append("C")
    row_ids.append("u2")
    assert row.route == ("A", "B")
    assert event.row_ids == ("u1",)
    result = tr.prepare_advanced_transfer([row], [event])
    copy = result.as_dict()
    copy["bindings"]["rows"][0]["route"].append("D")
    assert result.as_dict()["bindings"]["rows"][0]["route"] == ["A", "B"]
    with pytest.raises(FrozenInstanceError):
        row.serial = "changed"


@pytest.mark.parametrize("choice", ["rdbNetwork", "rdbDatabase"])
def test_direction_is_a_distinct_unmapped_surface(choice):
    result = tr.prepare_transfer_direction(choice, decision="accept", context_sha256=SHA)
    assert result.as_dict()["outcome"] == "unsupported"
    assert result.as_dict()["direction"] is None
    assert result.as_dict()["advanced_invocation_link_verified"] is False
    assert_preparation(result)
    with pytest.raises(ValueError):
        tr.prepare_transfer_direction("database-to-network")


def test_missing_direction_uncertain_and_cancel_noop():
    assert tr.prepare_transfer_direction().as_dict()["outcome"] == "uncertain"
    assert tr.prepare_transfer_direction("rdbDatabase", decision="cancel").as_dict()["outcome"] == "confirmed_noop"


def test_cross_surface_events_are_refused():
    with pytest.raises(ValueError, match="advanced"):
        tr.AdvancedTransferEvent("pause")
    with pytest.raises(ValueError, match="quick"):
        tr.QuickTransferEvent("choose-action", "u1")
    with pytest.raises(ValueError):
        tr.prepare_advanced_transfer([unit()], [tr.QuickTransferEvent("pause")])
    with pytest.raises(ValueError):
        tr.record_quick_transfer(["u1"], [tr.AdvancedTransferEvent("accept")], attempt_id="q1")


def test_quick_progress_completion_failure_and_controls_never_make_queue_commands():
    events = [tr.QuickTransferEvent("pause"), tr.QuickTransferEvent("resume"),
              tr.QuickTransferEvent("progress", "u1", 40),
              tr.QuickTransferEvent("completed", "u1", 100),
              tr.QuickTransferEvent("failed", "u2", 20, "supplied failure"),
              tr.QuickTransferEvent("close")]
    result = tr.record_quick_transfer(["u1", "u2"], events, attempt_id="q1", context_sha256=SHA)
    assert result.as_dict()["outcome"] == "uncertain"
    assert [row["status"] for row in result.as_dict()["observations"]] == ["completed", "failed"]
    assert result.as_dict()["native_execution_verified"] is False
    assert result.as_dict()["advanced_invocation_link_verified"] is False
    assert_preparation(result)
    recovery = tr.record_quick_transfer(["u2"], attempt_id="q2", previous_attempt_sha256=result.as_dict()["report_sha256"])
    assert recovery.as_dict()["recovery_is_separate_attempt"] is True
    assert result.as_dict()["observations"][0]["status"] == "completed"
    with pytest.raises(ValueError, match="separate recovery"):
        tr.record_quick_transfer(["u1"], [tr.QuickTransferEvent("completed", "u1"),
                                         tr.QuickTransferEvent("progress", "u1", 50)], attempt_id="q1")


def test_selected_restore_conflicts_only_and_explicit_rename():
    projects = [project(proposed_name="RENAMED"), project("p2"), project("p3", source_project="OTHER", selected=False)]
    result = restore(projects, history=[tr.RestoreEvent("choose-policy", policy="rename"), tr.RestoreEvent("accept")])
    document = result.as_dict()
    assert [row["row_id"] for row in document["decisions"]] == ["p1", "p2"]
    assert [row["destination_name"] for row in document["decisions"]] == ["RENAMED", "NEW"]
    assert document["intent_frozen"] is True
    assert document["outcome"] == "unsupported"
    assert document["automatic_rename_rule"] is None
    assert document["replace_primitive"] is None
    assert document["batch_atomicity"] is None
    assert_preparation(result)


def test_replace_rename_toggling_preserves_proposed_names_and_input_hashes():
    history = [tr.RestoreEvent("propose-name", ["p1"], proposed_name="RENAMED"),
               tr.RestoreEvent("choose-policy", policy="rename"),
               tr.RestoreEvent("choose-policy", policy="replace"),
               tr.RestoreEvent("accept")]
    result = restore(history=history)
    document = result.as_dict()
    assert document["decisions"][0]["destination_name"] == "OLD"
    assert document["decisions"][0]["proposed_name"] == "RENAMED"
    assert document["bindings"]["archive_sha256"] == SHA
    assert document["bindings"]["destination_snapshot_sha256"] == OTHER_SHA
    assert document["outcome"] == "unsupported"
    assert document["replace_primitive"] is None
    assert_preparation(result)


@pytest.mark.parametrize("history", [
    [tr.RestoreEvent("cancel")],
    [tr.RestoreEvent("choose-policy", policy="replace"), tr.RestoreEvent("cancel")],
])
def test_restore_cancel_has_zero_mutations_and_preserves_inputs(history):
    projects = [project(proposed_name="RENAMED"), project("p2")]
    result = restore(projects, history=history)
    assert result.as_dict()["bindings"]["projects"] == [row.as_dict() for row in projects]
    assert result.as_dict()["outcome"] == "confirmed_noop"
    assert result.as_dict()["intent_frozen"] is False
    assert_preparation(result)


@pytest.mark.parametrize("projects, history, code", [
    ([project()], [tr.RestoreEvent("accept")], "conflict_policy_required"),
    ([project()], [tr.RestoreEvent("choose-policy", policy="rename"), tr.RestoreEvent("accept")], "explicit_rename_name_required"),
    ([project(proposed_name="OLD")], [tr.RestoreEvent("choose-policy", policy="rename"), tr.RestoreEvent("accept")], "rename_destination_exists"),
    ([project(proposed_name="NEW"), project("p2")], [tr.RestoreEvent("choose-policy", policy="rename"), tr.RestoreEvent("accept")], "duplicate_destination_names"),
])
def test_unresolved_or_duplicate_restore_targets_refuse_acceptance(projects, history, code):
    result = restore(projects, history=history)
    assert result.as_dict()["outcome"] == "uncertain"
    assert result.as_dict()["intent_frozen"] is False
    assert code in codes(result)
    assert_preparation(result)


def test_empty_selection_and_unsupported_profile_remain_distinct():
    assert restore(history=[tr.RestoreEvent("select-none")]).as_dict()["outcome"] == "not_applicable"
    assert restore(history=[tr.RestoreEvent("select-none"), tr.RestoreEvent("accept")]).as_dict()["outcome"] == "confirmed_noop"
    result = restore(name_profile="unknown-vendor-profile")
    assert result.as_dict()["outcome"] == "unsupported"
    assert result.as_dict()["intent_frozen"] is False
    assert "unsupported_name_profile" in codes(result)


def test_duplicate_members_invalid_tokens_and_case_collisions_refused():
    with pytest.raises(ValueError, match="member identity"):
        restore([project(), project("p2", member_identity="member/p1", selected=False)])
    with pytest.raises(ValueError, match="row ID"):
        restore([project(), project()])
    with pytest.raises(ValueError, match="Project names"):
        project(proposed_name="TOO_LONG_NAME")
    with pytest.raises(ValueError, match="Ambiguous destination"):
        restore(destination_names=("OLD", "old"))


def test_restore_result_history_is_separate_and_keeps_partial_failure_and_untouched_row():
    projects = [project(), project("p2"), project("p3", source_project="THIRD", selected=False)]
    decision = restore(projects, history=[tr.RestoreEvent("choose-policy", policy="replace"), tr.RestoreEvent("accept")])
    results = tr.record_restore_results(projects, [tr.RestoreResult("p1", "completed"),
                                                  tr.RestoreResult("p2", "failed", "supplied error")],
                                        attempt_id="r1", decision_sha256=decision.as_dict()["report_sha256"])
    document = results.as_dict()
    assert [row["status"] for row in document["observations"]] == ["completed", "failed", "not-attempted"]
    assert document["native_execution_verified"] is False
    assert document["rollback_verified"] is False
    assert document["batch_atomicity"] is None
    assert decision.as_dict()["execution_admitted"] is False
    assert_preparation(results)
    with pytest.raises(ValueError, match="unselected"):
        tr.record_restore_results(projects, [tr.RestoreResult("p3", "completed")], attempt_id="r1")
    with pytest.raises(ValueError, match="Duplicate"):
        tr.record_restore_results(projects, [tr.RestoreResult("p1", "failed"), tr.RestoreResult("p1", "completed")], attempt_id="r1")


def test_serialized_surface_and_authority_substitution_refused():
    result = restore(history=[tr.RestoreEvent("cancel")])
    forged = result.as_dict()
    forged["native_mutations"] = 1
    with pytest.raises(ValueError, match="recomputed"):
        tr.RestoreDecisionPlan.from_dict(forged)
    with pytest.raises(ValueError, match="recomputed"):
        tr.RestoreResultsHistory.from_dict(result.as_dict())


def test_label_preparation_reuses_existing_allocation_and_freezes_echo():
    labels = [{"text": "A", "slot": 1}, {"text": "B", "slot": 1}, {"text": "C"}]
    extra = {"metadata": {"languages": ["caller supplied"]}}
    expected = plan_transfer(labels, 2, extra)
    result = tr.prepare_label_transfer(labels, 2, extra)
    labels[0]["text"] = "CHANGED"
    extra["metadata"]["languages"].append("changed")
    document = result.as_dict()
    assert document["assignments"] == [list(row) for row in expected.assignments]
    assert document["escalated"] == list(expected.escalated)
    assert document["behavioral_comparison"] == "unassessed"
    assert document["outcome"] == "uncertain"
    assert document["bindings"]["extra"] == expected.echo
    assert_preparation(result)


def test_all_public_preparation_surfaces_perform_zero_io():
    rows, projects = [unit(action="programming-only")], [project(proposed_name="RENAMED")]
    def forbidden(*args, **kwargs):
        raise AssertionError("Preparation attempted I/O or native execution")
    with patch("builtins.open", forbidden), patch("pathlib.Path.open", forbidden), \
         patch("socket.socket", forbidden), patch("subprocess.Popen", forbidden), \
         patch("cbus_toolkit.native.NativeProjects.__init__", forbidden), \
         patch("cbus_toolkit.programming.Programmer.__init__", forbidden):
        reports = [
            tr.prepare_advanced_transfer(rows, [tr.AdvancedTransferEvent("accept")]),
            tr.prepare_transfer_direction("rdbNetwork", decision="accept"),
            tr.record_quick_transfer(["u1"], [tr.QuickTransferEvent("pause")], attempt_id="q1"),
            restore(projects, history=[tr.RestoreEvent("choose-policy", policy="rename"), tr.RestoreEvent("accept")]),
            tr.record_restore_results(projects, [tr.RestoreResult("p1", "completed")], attempt_id="r1"),
            tr.prepare_label_transfer([{"text": "A"}], 1),
        ]
        for report in reports:
            assert_preparation(report)


@pytest.mark.parametrize("kind", [tr.AdvancedTransferPlan, tr.TransferDirectionPlan, tr.QuickTransferHistory, tr.RestoreDecisionPlan, tr.RestoreResultsHistory, tr.LabelTransferPreparation])
def test_report_constructors_cannot_fabricate_authority(kind):
    with pytest.raises(TypeError, match="preparation function or from_dict"):
        kind('{"execution_admitted":true}')
    with pytest.raises(TypeError, match="preparation function or from_dict"):
        kind(_document='{"execution_admitted":true}')
