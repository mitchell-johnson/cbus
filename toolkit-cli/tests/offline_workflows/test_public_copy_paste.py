"""Copy/paste regressions through the public cbus-toolkit main entry point.

Run with an external --basetemp. Tests resolve macOS temporary parent aliases,
use synthetic caller data, and forbid network/native/project-copy execution.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import subprocess

import pytest

from cbus_toolkit import cli
from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeDatabase
from cbus_toolkit.offline_workflows import copy_paste_input
from cbus_toolkit.project import ProjectDocument


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("public-copy-paste").resolve()


@pytest.fixture(autouse=True)
def forbid_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("public offline copy/paste invoked an execution backend")
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(CGateClient, "connect", forbidden)
    monkeypatch.setattr(NativeDatabase, "copy", forbidden)
    monkeypatch.setattr(ProjectDocument, "copy", forbidden)


@pytest.fixture
def caller_document():
    # Explicit caller fixture; examples are source-only and are not wheel resources.
    example = (Path(__file__).resolve().parents[2] / "src" / "cbus_toolkit"
               / "offline_workflows" / "examples" / "copy-paste.json")
    value = json.loads(example.read_text())
    raw = b'<!--caller-owned--><Group oid="caller-group"><Unknown ordinal="1"/><Unknown ordinal="2"/></Group>'
    owner = {"endpoint": "offline:caller-choice", "repository": "caller-repository", "project": "CALLER"}
    value["source"].update(owner=deepcopy(owner), selector="//CALLER/0009/56/7",
                           oid="caller-group", snapshot_hex=raw.hex())
    value["operations"][0]["target"].update(owner=deepcopy(owner), selector="//CALLER/0009/56",
                                            oid="caller-application")
    value["operations"][1]["request"].update(address="0093", name=" Caller-selected \u0394 ",
                                             source_sha256=hashlib.sha256(raw).hexdigest())
    return value


def input_file(tmp_path, value):
    path = tmp_path / "caller-input.json"
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def public_command(capsys, source, operation="plan", *, output=None, compact=True):
    arguments = ["offline-workflows", "copy-paste", operation, "--input", str(source)]
    if output is not None:
        arguments += ["--output", str(output)]
    if compact:
        arguments.append("--compact")
    status = cli.main(arguments)
    captured = capsys.readouterr()
    payload = captured.out if captured.out else captured.err
    return status, json.loads(payload), captured


def assert_preparation_envelope(envelope):
    assert envelope["format"] == "cbus-offline-workflows-cli-v1"
    assert envelope["preparation_only"] is True
    for name in ("execution_enabled", "native_execution_enabled", "original_compatibility_verified",
                 "external_persistence_verified"):
        assert envelope[name] is False


@pytest.mark.parametrize("operation", ["inspect", "validate", "plan"])
def test_public_main_uses_caller_data_and_emits_one_json_document(tmp_path, caller_document, capsys, operation):
    source = input_file(tmp_path, caller_document)
    before = source.read_bytes()
    status, envelope, captured = public_command(capsys, source, operation)
    assert status == 0
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    assert_preparation_envelope(envelope)
    assert envelope["workflow"] == "copy-paste"
    assert envelope["operation"] == operation
    assert envelope["input_sha256"] == hashlib.sha256(before).hexdigest()
    report = envelope["report"]
    component = report["component"]
    assert component["source"]["owner"] == caller_document["source"]["owner"]
    assert component["source"]["selector"] == "//CALLER/0009/56/7"
    assert component["source"]["oid"] == "caller-group"
    assert component["source"]["sha256"] == caller_document["operations"][1]["request"]["source_sha256"]
    assert component["commands"] == []
    assert component["external_mutation_attempted"] is False
    assert component["saved"] is False and component["reopened"] is False
    if operation == "inspect":
        assert report["outcome"] == "inspected"
        assert report["validation_passed"] is False
        assert component["phase"] == "copied"
        assert report["operation_results"] == []
        assert report["not_attempted_operations"] == 2
    else:
        assert report["outcome"] == "prepared"
        assert report["validation_passed"] is True
        assert component["phase"] == "accepted"
        assert component["request"]["address"] == "0093"
        assert component["request"]["name"] == " Caller-selected \u0394 "
    assert source.read_bytes() == before


@pytest.mark.parametrize("operation", ["validate", "plan"])
@pytest.mark.parametrize("owner_field", ["endpoint", "repository", "project"])
def test_public_mixed_owners_refuse_with_semantic_status3(tmp_path, caller_document, capsys, operation, owner_field):
    caller_document["operations"][0]["target"]["owner"][owner_field] += "-other"
    source = input_file(tmp_path, caller_document)
    before = source.read_bytes()
    status, envelope, captured = public_command(capsys, source, operation)
    assert status == 3 and captured.err == ""
    assert_preparation_envelope(envelope)
    report = envelope["report"]
    assert report["outcome"] == "refused"
    assert report["validation_passed"] is False
    assert report["refusal"]["code"] == "different_owner"
    assert report["component"]["phase"] == "refused"
    assert source.read_bytes() == before


@pytest.mark.parametrize("operation", ["validate", "plan"])
def test_public_stale_hash_retains_refusal_and_skips_dependent_cancel(tmp_path, caller_document, capsys, operation):
    caller_document["operations"][1]["request"]["source_sha256"] = "0" * 64
    caller_document["operations"].append({"action": "cancel"})
    source = input_file(tmp_path, caller_document)
    before = source.read_bytes()
    status, envelope, captured = public_command(capsys, source, operation)
    assert status == 3 and captured.err == ""
    report = envelope["report"]
    assert report["outcome"] == "refused"
    assert report["refusal"]["code"] == "source_binding"
    assert report["not_attempted_operations"] == 1
    assert report["component"]["phase"] == "refused"
    assert report["component"]["commands"] == []
    assert source.read_bytes() == before


@pytest.mark.parametrize("operation", ["validate", "plan"])
def test_public_uncertainty_blocks_later_paste_and_cancel(tmp_path, caller_document, capsys, operation):
    caller_document["operations"].insert(1, {"action": "uncertain", "detail": "Caller recorded interrupted planning"})
    caller_document["operations"].append({"action": "cancel"})
    source = input_file(tmp_path, caller_document)
    status, envelope, captured = public_command(capsys, source, operation)
    assert status == 3 and captured.err == ""
    report = envelope["report"]
    assert report["outcome"] == "uncertain"
    assert report["validation_passed"] is False
    assert report["refusal"]["code"] == "uncertain_outcome"
    assert report["not_attempted_operations"] == 2
    assert report["component"]["phase"] == "uncertain"
    assert "paste-attempted" not in report["component"]["history"]


def test_public_cancel_succeeds_only_as_local_draft_discard(tmp_path, caller_document, capsys):
    caller_document["operations"].append({"action": "cancel"})
    source = input_file(tmp_path, caller_document)
    before = source.read_bytes()
    status, envelope, captured = public_command(capsys, source)
    assert status == 0 and captured.err == ""
    report = envelope["report"]
    assert report["outcome"] == "cancelled"
    assert report["validation_passed"] is True
    assert report["component"]["cancellation_effect"] == "discarded-offline-intent-only"
    assert report["component"]["external_mutation_attempted"] is False
    assert source.read_bytes() == before


@pytest.mark.parametrize("mode", ["unsupported", "original-toolkit", "native-clipboard"])
def test_public_unproved_contracts_refuse_with_status3(tmp_path, caller_document, capsys, mode):
    caller_document["profile"] = {"mode": mode}
    source = input_file(tmp_path, caller_document)
    status, envelope, captured = public_command(capsys, source)
    assert status == 3 and captured.err == ""
    report = envelope["report"]
    assert report["outcome"] == "unsupported"
    assert report["validation_passed"] is False
    assert report["requested_profile_mode"] == mode
    assert report["refusal"]["code"] == "unsupported_profile"
    assert report["component"]["commands"] == []


@pytest.mark.parametrize("kind", ["Project", "Unit", "Trigger", "Action", "Enable", "NetVar"])
def test_public_unverified_child_routes_cannot_acquire_execution(tmp_path, caller_document, capsys, kind):
    caller_document["source"]["kind"] = kind
    caller_document["profile"]["source_kind"] = kind
    source = input_file(tmp_path, caller_document)
    status, envelope, captured = public_command(capsys, source)
    assert status == 3 and captured.err == ""
    assert envelope["report"]["outcome"] == "unsupported"
    assert envelope["report"]["validation_passed"] is False
    assert_preparation_envelope(envelope)


@pytest.mark.parametrize("stage", ["saved", "reopened"])
def test_public_save_and_reopen_requests_remain_explicit_unsupported_gates(tmp_path, caller_document, capsys, stage):
    caller_document["operations"].append({"action": "persistence-gate", "stage": stage})
    source = input_file(tmp_path, caller_document)
    status, envelope, captured = public_command(capsys, source)
    assert status == 3 and captured.err == ""
    report = envelope["report"]
    assert report["outcome"] == "unsupported"
    assert report["refusal"]["code"] == "unsupported_persistence"
    assert report["component"]["saved"] is False
    assert report["component"]["reopened"] is False
    assert report["component"]["phase"] == "accepted"


def test_public_duplicate_paste_is_refused_without_replay(tmp_path, caller_document, capsys):
    caller_document["operations"].append(deepcopy(caller_document["operations"][1]))
    source = input_file(tmp_path, caller_document)
    status, envelope, captured = public_command(capsys, source)
    assert status == 3 and captured.err == ""
    report = envelope["report"]
    assert report["outcome"] == "refused"
    assert report["refusal"]["code"] == "invalid_transition"
    assert report["component"]["history"].count("paste-attempted") == 1


def test_public_unknown_late_field_is_status2_before_any_local_operation(tmp_path, caller_document, capsys, monkeypatch):
    caller_document["operations"].append({"action": "cancel", "unknown": True})
    def forbidden(*args, **kwargs):
        raise AssertionError("public parser replayed before checking the full input")
    monkeypatch.setattr(copy_paste_input, "select_target", forbidden)
    source = input_file(tmp_path, caller_document)
    before = source.read_bytes()
    status, envelope, captured = public_command(capsys, source)
    assert status == 2 and captured.out == ""
    assert_preparation_envelope(envelope)
    assert envelope["error"]["code"] == "invalid_input"
    assert "Traceback" not in captured.err
    assert source.read_bytes() == before


def test_public_output_is_one_complete_json_file_and_existing_output_is_preserved(tmp_path, caller_document, capsys):
    source = input_file(tmp_path, caller_document)
    before = source.read_bytes()
    output = tmp_path / "new-plan.json"
    status, envelope, captured = public_command(capsys, source, output=output)
    assert status == 0 and captured.err == ""
    published = output.read_bytes()
    assert published == captured.out.encode("ascii")
    assert json.loads(published) == envelope
    assert envelope["external_persistence_verified"] is False
    assert source.read_bytes() == before
    caller_document["operations"][1]["request"]["name"] = "New requested name"
    source.write_text(json.dumps(caller_document), encoding="utf-8")
    status, failure, captured = public_command(capsys, source, output=output)
    assert status == 4 and captured.out == ""
    assert failure["error"]["code"] == "output_exists"
    assert output.read_bytes() == published


def test_public_pretty_output_still_contains_only_one_json_document(tmp_path, caller_document, capsys):
    source = input_file(tmp_path, caller_document)
    status, envelope, captured = public_command(capsys, source, compact=False)
    assert status == 0 and captured.err == ""
    assert len(captured.out.splitlines()) > 1
    assert envelope["report"]["outcome"] == "prepared"
    assert_preparation_envelope(envelope)
