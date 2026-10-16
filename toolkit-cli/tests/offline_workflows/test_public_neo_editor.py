"""Public cbus-toolkit entry point for explicit local Neo preparation."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from cbus_toolkit.cli import main


EXAMPLE = Path(__file__).resolve().parents[2] / "src/cbus_toolkit/offline_workflows/examples/neo-editor.json"


def supplied():
    return json.loads(EXAMPLE.read_text())


def invoke(capsys, tmp_path, operation, *, document=None, extra=(), global_compact=False):
    folder = tmp_path.resolve()
    source = folder / "neo-input.json"
    raw = json.dumps(supplied() if document is None else document, sort_keys=True).encode("utf-8")
    source.write_bytes(raw)
    args = ["offline-workflows", "neo-editor", operation, "--input", str(source), *map(str, extra)]
    if global_compact:
        args.insert(0, "--compact")
    status = main(args)
    captured = capsys.readouterr()
    assert source.read_bytes() == raw
    assert "Traceback" not in captured.err + captured.out
    stream = captured.out or captured.err
    return status, json.loads(stream), captured, raw


def assert_preparation_only(envelope):
    assert envelope["preparation_only"] is True
    for key in ("execution_enabled", "native_execution_enabled", "original_compatibility_verified",
                "external_persistence_verified"):
        assert envelope[key] is False
    if "report" in envelope:
        report = envelope["report"]
        for key in ("saved", "io_performed", "native_acceptance", "physical_acceptance",
                    "external_persistence_verified"):
            assert report[key] is False
        if report["final_state"] is not None:
            state = report["final_state"]
            assert state["pp_save_count"] == state["project_save_count"] == 0
            assert "PROPOSED" in state["policy"]
            assert state["original_terminal_semantics"] == "original terminal semantics unassessed"


@pytest.mark.parametrize("operation", ["inspect", "validate", "plan"])
def test_public_neo_editor_operations_reach_real_adapter_and_preserve_caller_input(capsys, tmp_path, operation):
    status, envelope, captured, raw = invoke(capsys, tmp_path, operation, extra=("--compact",))
    assert status == 0 and not captured.err
    assert len(captured.out.splitlines()) == 1
    assert envelope["format"] == "cbus-offline-workflows-cli-v1"
    assert envelope["workflow"] == "neo-editor" and envelope["operation"] == operation
    assert envelope["input_sha256"] == sha256(raw).hexdigest()
    report = envelope["report"]
    assert report["workflow"] == "neo-editor" and report["validation_passed"]
    state = report["final_state"]
    if operation == "inspect":
        assert report["outcome"] == "inspected" and report["operations_executed"] == 0
        assert not report["operation_semantics_validated"]
        assert state["is_open"] and not state["dirty"] and state["local_apply_count"] == 0
        assert state["opening"] == state["applied"] == state["working"]
    else:
        assert report["outcome"] == "cancelled" and report["operations_executed"] == 5
        assert not state["is_open"] and not state["dirty"] and state["local_apply_count"] == 1
        assert state["opening"] != state["applied"] == state["working"]
        assert state["working"]["memory"]["bytes"]["104"] == 0xB0
        assert state["working"]["memory"]["bytes"]["80"] == 1
        assert state["history"][-2]["action"] == "edit_preset"
        assert state["history"][-1]["action"] == "cancel_editor"
    assert_preparation_only(envelope)


def test_public_nested_destination_cancel_preserves_dirty_b_and_applied_a(capsys, tmp_path):
    document = supplied()
    document["operations"] = document["operations"][:4] + [
        {"action": "request-apply"}, {"action": "cancel-destination"},
    ]
    status, envelope, _, _ = invoke(capsys, tmp_path, "plan", document=document)
    assert status == 0 and envelope["report"]["outcome"] == "prepared"
    state = envelope["report"]["final_state"]
    assert state["is_open"] and state["dirty"] and state["destination_action"] is None
    assert state["applied"]["memory"]["bytes"]["104"] == 0xB0
    assert state["working"]["memory"]["bytes"]["104"] == 0xF0
    assert state["local_apply_count"] == 1
    assert_preparation_only(envelope)


def test_public_stale_opening_binding_refuses_before_second_local_apply(capsys, tmp_path):
    document = supplied()
    document["operations"] = document["operations"][:4] + [
        {"action": "request-apply"},
        {"action": "confirm-database", "current": {"reference": "opening"}},
        {"action": "cancel-editor", "route": "cancel"},
    ]
    status, envelope, captured, _ = invoke(capsys, tmp_path, "plan", document=document)
    assert status == 3 and not captured.err
    report = envelope["report"]
    assert report["outcome"] == "refused" and not report["validation_passed"]
    assert report["operations_executed"] == 5 and report["errors"][0]["operation_index"] == 6
    assert "baseline" in report["errors"][0]["message"]
    assert report["final_state"]["local_apply_count"] == 1
    assert report["final_state"]["dirty"] and report["final_state"]["destination_action"] == "apply"
    assert_preparation_only(envelope)


@pytest.mark.parametrize("choice", [{"destination": "physical"}, {"destination": "both"}, {"entire_unit": True}])
def test_public_unsupported_destination_never_accepts_or_executes(capsys, tmp_path, choice):
    document = supplied()
    document["operations"] = document["operations"][:3]
    document["operations"][2].update(choice)
    status, envelope, captured, _ = invoke(capsys, tmp_path, "validate", document=document)
    assert status == 3 and not captured.err
    report = envelope["report"]
    assert report["outcome"] == "unsupported" and not report["validation_passed"]
    assert report["operations_executed"] == 2 and report["final_state"]["local_apply_count"] == 0
    assert_preparation_only(envelope)


@pytest.mark.parametrize("change", [{"firmware": "2.5.01"}, {"catalogue": "5058NL"}, {"unit_type": "KEYM8"}])
def test_public_unsupported_profile_cannot_fall_back_to_demo_defaults(capsys, tmp_path, change):
    document = supplied()
    document["profile"].update(change)
    status, envelope, captured, _ = invoke(capsys, tmp_path, "plan", document=document)
    assert status == 3 and not captured.err
    report = envelope["report"]
    assert report["outcome"] == "unsupported" and not report["validation_passed"]
    assert report["final_state"] is None and report["operations_executed"] == 0
    assert_preparation_only(envelope)


def test_public_shape_error_has_json_stderr_and_status_two(capsys, tmp_path):
    document = supplied()
    del document["snapshot"]
    status, envelope, captured, _ = invoke(capsys, tmp_path, "plan", document=document)
    assert status == 2 and not captured.out
    assert envelope["error"]["code"] == "invalid_input"
    assert_preparation_only(envelope)


def test_public_output_is_complete_and_existing_destination_is_preserved(capsys, tmp_path):
    destination = tmp_path.resolve() / "neo-report.json"
    status, envelope, captured, _ = invoke(capsys, tmp_path, "plan", extra=("--output", destination, "--compact"))
    assert status == 0 and not captured.err
    complete = destination.read_bytes()
    assert complete == captured.out.encode("ascii")
    assert json.loads(complete) == envelope
    status, error, captured, _ = invoke(capsys, tmp_path, "plan", extra=("--output", destination))
    assert status == 4 and not captured.out
    assert error["error"]["code"] == "output_exists"
    assert destination.read_bytes() == complete
    assert not list(tmp_path.resolve().glob(".cbus-offline-*.tmp"))
    assert_preparation_only(error)


def test_public_global_and_suffix_compact_emit_same_single_line_report(capsys, tmp_path):
    status, envelope, suffix, _ = invoke(capsys, tmp_path, "plan", extra=("--compact",))
    other_status, other, global_form, _ = invoke(capsys, tmp_path, "plan", global_compact=True)
    assert status == other_status == 0
    assert envelope == other and suffix.out == global_form.out
    assert len(global_form.out.splitlines()) == 1


def test_public_plan_cannot_open_a_socket_or_programming_session(monkeypatch, capsys, tmp_path):
    from cbus_toolkit.extended_macros import ExtendedKeys
    from cbus_toolkit.programming import ProgrammingSession
    import socket

    calls = []
    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Public offline Neo invoked a backend")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(ProgrammingSession, "__enter__", forbidden)
    monkeypatch.setattr(ProgrammingSession, "set", forbidden)
    monkeypatch.setattr(ProgrammingSession, "save", forbidden)
    monkeypatch.setattr(ProgrammingSession, "save_to_source", forbidden)
    monkeypatch.setattr(ExtendedKeys, "apply", forbidden)
    status, envelope, _, _ = invoke(capsys, tmp_path, "plan")
    assert status == 0 and calls == []
    assert_preparation_only(envelope)
