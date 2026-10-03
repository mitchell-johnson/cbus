"""Public cbus-toolkit entry point: independent transfer/restore preparation."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cbus_toolkit import cli
from cbus_toolkit.offline_workflows.transfer_restore import RestoreProject, TransferRow
from cbus_toolkit.offline_workflows.transfer_restore_input import FORMAT

SOURCE_SHA = sha256(b"synthetic source snapshot").hexdigest()
STAGED_SHA = sha256(b"synthetic staged data").hexdigest()
DESTINATION_SHA = sha256(b"synthetic destination snapshot").hexdigest()


def _unit(row_id="unit-1", **changes):
    fields = dict(row_id=row_id, source_identity="synthetic:source/" + row_id,
                  source_snapshot_sha256=SOURCE_SHA,
                  destination_identity="synthetic:destination/" + row_id,
                  destination_snapshot_sha256=DESTINATION_SHA,
                  staged_data_sha256=STAGED_SHA, source_address="0x01",
                  serial="SYNTHETIC-" + row_id, unit_type="KEY1", firmware="1.2.67",
                  route=("source-network", "bridge-network"), action="programming-only")
    fields.update(changes)
    return TransferRow(**fields).as_dict()


def _project(row_id="project-A", **changes):
    fields = dict(row_id=row_id, member_identity="synthetic:archive/" + row_id + ".xml",
                  source_project="A", source_snapshot_sha256=SOURCE_SHA,
                  proposed_name="A_REVIEW")
    fields.update(changes)
    return RestoreProject(**fields).as_dict()


def _document(surface="advanced-transfer", **changes):
    bindings = {
        "advanced-transfer": {"rows": [_unit()]},
        "transfer-direction": {"context_sha256": SOURCE_SHA},
        "quick-transfer": {"row_ids": ["unit-1", "unit-2"], "attempt_id": "synthetic-quick-attempt"},
        "restore-decision": {"projects": [_project()], "archive_sha256": STAGED_SHA,
                             "destination_snapshot_sha256": DESTINATION_SHA, "destination_names": ["A"]},
        "restore-results": {"projects": [_project()], "attempt_id": "synthetic-restore-results"},
        "label-transfer": {"labels": [{"text": "DeskLamp", "slot": 1}, {"text": "SecondLamp"}], "capacity": 4},
    }
    value = {"format": FORMAT, "surface": surface, "bindings": bindings[surface]}
    if surface == "transfer-direction":
        value["choices"] = {"choice": "rdbDatabase", "decision": "accept"}
    value.update(changes)
    return value


def _invoke(tmp_path, capsys, value, operation="plan", *, output=None, filename="input.json"):
    source = tmp_path / filename
    raw = json.dumps(value, sort_keys=True).encode("utf-8")
    source.write_bytes(raw)
    arguments = ["offline-workflows", "transfer-restore", operation, "--input", str(source), "--compact"]
    if output is not None:
        arguments.extend(("--output", str(output)))
    status = cli.main(arguments)
    captured = capsys.readouterr()
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    envelope = json.loads(captured.out)
    assert envelope["input_sha256"] == sha256(raw).hexdigest()
    assert source.read_bytes() == raw
    return status, envelope, captured.out


def _assert_gates(envelope):
    assert envelope["format"] == "cbus-offline-workflows-cli-v1"
    assert envelope["workflow"] == "transfer-restore"
    assert envelope["preparation_only"] is True
    for field in ("execution_enabled", "native_execution_enabled", "original_compatibility_verified", "external_persistence_verified"):
        assert envelope[field] is False
    report = envelope["report"]
    assert report["workflow"] == "transfer-restore"
    for result in (report, report["component_report"]):
        if result is None:
            continue
        assert result["preparation_only"] is True
        assert result["execution_admitted"] is False
        assert result["original_workflow_verified"] is False
        assert result["native_mutations"] == 0
        assert result["queue_commands"] == []
        assert result["automatic_replay_authorized"] is False


@pytest.mark.parametrize("surface", ["advanced-transfer", "transfer-direction", "quick-transfer", "restore-decision", "restore-results", "label-transfer"])
def test_public_inspect_keeps_each_surface_distinct(tmp_path, capsys, surface):
    status, envelope, _ = _invoke(tmp_path, capsys, _document(surface), "inspect")
    assert status == 0
    assert envelope["operation"] == "inspect"
    assert envelope["report"]["surface"] == surface
    assert envelope["report"]["outcome"] == "inspected"
    assert envelope["report"]["history_applied"] is False
    assert envelope["report"]["component_report"]["surface"] == surface
    _assert_gates(envelope)


def test_public_inspect_preserves_opening_descriptors_without_applying_history(tmp_path, capsys):
    value = _document(history=[{"kind": "clear-actions", "row_ids": ["unit-1"]}, {"kind": "cancel"}])
    status, envelope, _ = _invoke(tmp_path, capsys, value, "inspect")
    component = envelope["report"]["component_report"]
    assert status == 0
    assert component["history"] == []
    assert component["selected_actions"] == [{"row_id": "unit-1", "action": "programming-only"}]
    assert component["terminal_choice"] is None
    assert envelope["report"]["supplied_history_count"] == 2
    _assert_gates(envelope)


@pytest.mark.parametrize("operation", ["validate", "plan"])
def test_public_advanced_accept_cannot_admit_unverified_execution(tmp_path, capsys, operation):
    status, envelope, _ = _invoke(tmp_path, capsys, _document(history=[{"kind": "accept"}]), operation)
    component = envelope["report"]["component_report"]
    assert status == 3
    assert envelope["report"]["outcome"] == "unsupported"
    assert envelope["report"]["validation_passed"] is False
    assert component["intent_frozen"] is True
    assert component["direction_binding"] is None
    assert component["quick_invocation_link_verified"] is False
    assert component["bindings"]["rows"][0] == _unit()
    _assert_gates(envelope)


@pytest.mark.parametrize("surface", ["advanced-transfer", "transfer-direction", "restore-decision"])
def test_public_cancel_records_zero_mutation_and_exits_zero(tmp_path, capsys, surface):
    value = _document(surface)
    if surface == "transfer-direction":
        value["choices"]["decision"] = "cancel"
    else:
        value["history"] = [{"kind": "cancel"}]
    status, envelope, _ = _invoke(tmp_path, capsys, value)
    assert status == 0
    assert envelope["report"]["outcome"] == "cancelled"
    assert envelope["report"]["component_report"]["outcome"] == "confirmed_noop"
    _assert_gates(envelope)


def test_public_direction_retains_control_name_without_mapping_it_to_transfer(tmp_path, capsys):
    status, envelope, _ = _invoke(tmp_path, capsys, _document("transfer-direction"))
    component = envelope["report"]["component_report"]
    assert status == 3
    assert envelope["report"]["outcome"] == "unsupported"
    assert component["bindings"]["choice"] == "rdbDatabase"
    assert component["direction"] is None
    assert component["advanced_invocation_link_verified"] is False
    _assert_gates(envelope)


def test_public_mixed_transfer_actions_remain_capture_gated(tmp_path, capsys):
    value = _document(history=[{"kind": "accept"}])
    value["bindings"]["rows"].append(_unit("unit-2", action="add-only"))
    status, envelope, _ = _invoke(tmp_path, capsys, value)
    assert status == 3
    assert envelope["report"]["outcome"] == "unsupported"
    assert any(issue.get("contract") == "mixed_row_eligibility" for issue in envelope["report"]["component_report"]["issues"])
    _assert_gates(envelope)


def test_public_missing_staged_binding_is_uncertain(tmp_path, capsys):
    value = _document()
    value["bindings"]["rows"][0]["staged_data_sha256"] = None
    status, envelope, _ = _invoke(tmp_path, capsys, value, "validate")
    assert status == 3
    assert envelope["report"]["outcome"] == "uncertain"
    assert any(issue["code"] == "staged_data_binding_required" for issue in envelope["report"]["issues"])
    _assert_gates(envelope)


def test_public_declared_stale_binding_is_refused_with_recomputed_evidence(tmp_path, capsys):
    value = _document(history=[{"kind": "cancel"}])
    _, first, _ = _invoke(tmp_path, capsys, value, filename="first.json")
    value["expect_binding_sha256"] = first["report"]["component_report"]["binding_sha256"]
    value["bindings"]["rows"][0]["source_snapshot_sha256"] = STAGED_SHA
    status, envelope, _ = _invoke(tmp_path, capsys, value, filename="changed.json")
    assert status == 3
    assert envelope["report"]["outcome"] == "refused"
    assert envelope["report"]["issues"][0]["code"] == "stale_binding"
    assert envelope["report"]["binding_check_scope"] == "declared_inputs_only"
    assert envelope["report"]["component_report"]["bindings"]["rows"][0]["source_snapshot_sha256"] == STAGED_SHA
    _assert_gates(envelope)


def test_public_restore_decision_keeps_explicit_names_and_unselected_rows(tmp_path, capsys):
    value = _document("restore-decision", history=[{"kind": "choose-policy", "policy": "rename"}, {"kind": "accept"}])
    value["bindings"]["projects"].append(_project("project-B", source_project="B", selected=False, proposed_name=None))
    status, envelope, _ = _invoke(tmp_path, capsys, value)
    component = envelope["report"]["component_report"]
    assert status == 3
    assert envelope["report"]["outcome"] == "unsupported"
    assert component["intent_frozen"] is True
    assert [row["row_id"] for row in component["decisions"]] == ["project-A"]
    assert component["decisions"][0]["destination_name"] == "A_REVIEW"
    assert component["automatic_rename_rule"] is None
    assert component["replace_primitive"] is None
    assert component["results_invocation_link_verified"] is False
    _assert_gates(envelope)


def test_public_restore_missing_name_and_unknown_profile_are_distinct_gates(tmp_path, capsys):
    value = _document("restore-decision", history=[{"kind": "choose-policy", "policy": "rename"}, {"kind": "accept"}])
    value["bindings"]["projects"][0]["proposed_name"] = None
    status, uncertain, _ = _invoke(tmp_path, capsys, value, filename="missing-name.json")
    assert status == 3
    assert uncertain["report"]["outcome"] == "uncertain"
    assert uncertain["report"]["component_report"]["intent_frozen"] is False
    value["bindings"]["name_profile"] = "unsupported-native-profile"
    status, unsupported, _ = _invoke(tmp_path, capsys, value, filename="unknown-profile.json")
    assert status == 3
    assert unsupported["report"]["outcome"] == "unsupported"
    _assert_gates(uncertain)
    _assert_gates(unsupported)


def test_public_quick_records_do_not_become_advanced_or_queue_execution(tmp_path, capsys):
    value = _document("quick-transfer", history=[{"kind": "pause"}, {"kind": "resume"},
                      {"kind": "completed", "row_id": "unit-1", "percentage": 100},
                      {"kind": "failed", "row_id": "unit-2", "percentage": 40}, {"kind": "close"}])
    status, envelope, _ = _invoke(tmp_path, capsys, value)
    component = envelope["report"]["component_report"]
    assert status == 3
    assert envelope["report"]["outcome"] == "uncertain"
    assert [row["status"] for row in component["observations"]] == ["completed", "failed"]
    assert component["observation_provenance"] == "caller_supplied"
    assert component["native_execution_verified"] is False
    assert component["advanced_invocation_link_verified"] is False
    assert component["closed"] is True
    _assert_gates(envelope)


def test_public_restore_results_retain_partial_failure_without_rollback_claim(tmp_path, capsys):
    value = _document("restore-results", history=[{"row_id": "project-A", "status": "completed"},
                      {"row_id": "project-B", "status": "failed", "detail": "supplied failure"}])
    value["bindings"]["projects"].extend((_project("project-B", source_project="B"),
                                          _project("project-C", source_project="C", selected=False)))
    status, envelope, _ = _invoke(tmp_path, capsys, value)
    component = envelope["report"]["component_report"]
    assert status == 3
    assert envelope["report"]["outcome"] == "uncertain"
    assert [row["status"] for row in component["observations"]] == ["completed", "failed", "not-attempted"]
    assert component["native_execution_verified"] is False
    assert component["rollback_verified"] is False
    assert component["batch_atomicity"] is None
    _assert_gates(envelope)


def test_public_new_output_matches_stdout_and_never_overwrites(tmp_path, capsys):
    value = _document(history=[{"kind": "cancel"}])
    output = tmp_path / "review.json"
    status, envelope, stdout = _invoke(tmp_path, capsys, value, output=output)
    assert status == 0
    assert output.read_bytes() == stdout.encode("ascii")
    before = output.read_bytes()
    status = cli.main(["offline-workflows", "transfer-restore", "plan", "--input", str(tmp_path / "input.json"), "--output", str(output), "--compact"])
    captured = capsys.readouterr()
    assert status == 4
    assert captured.out == ""
    failure = json.loads(captured.err)
    assert failure["error"]["code"] == "output_exists"
    assert output.read_bytes() == before
    _assert_gates(envelope)


def test_public_tampered_output_is_not_valid_input_authority(tmp_path, capsys):
    value = _document()
    value["component_report"] = {"execution_admitted": True}
    source = tmp_path / "forged.json"
    source.write_text(json.dumps(value))
    output = tmp_path / "must-not-exist.json"
    status = cli.main(["offline-workflows", "transfer-restore", "plan", "--input", str(source), "--output", str(output), "--compact"])
    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "invalid_input"
    assert not output.exists()


def test_public_packaged_cancellation_example_is_runnable(tmp_path, capsys):
    source = Path(__file__).parents[2] / "src/cbus_toolkit/offline_workflows/examples/transfer-restore.json"
    status = cli.main(["offline-workflows", "transfer-restore", "plan", "--input", str(source), "--compact"])
    captured = capsys.readouterr()
    assert status == 0
    assert captured.err == ""
    envelope = json.loads(captured.out)
    assert envelope["report"]["outcome"] == "cancelled"
    _assert_gates(envelope)


def test_public_all_surfaces_avoid_backend_calls(tmp_path, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Public offline command attempted backend execution")
    with patch("socket.socket", forbidden), patch("subprocess.Popen", forbidden), \
         patch("cbus_toolkit.native.NativeProjects.__init__", forbidden), \
         patch("cbus_toolkit.programming.Programmer.__init__", forbidden):
        for surface in ("advanced-transfer", "transfer-direction", "quick-transfer", "restore-decision", "restore-results", "label-transfer"):
            status, envelope, _ = _invoke(tmp_path, capsys, _document(surface), "inspect", filename=surface + ".json")
            assert status == 0
            _assert_gates(envelope)
