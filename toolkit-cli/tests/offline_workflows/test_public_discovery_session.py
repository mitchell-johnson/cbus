"""Discovery/session preparation through the actual public Toolkit CLI main.

Caller files and symbolic observations are synthetic. No original/runtime/
hardware execution or backend acceptance follows from these public CLI checks.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from cbus_toolkit import cli
from cbus_toolkit import cgate, cni_discovery, native, networks, pci, pci_serial_probe

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
EXAMPLE = SOURCE_ROOT / "cbus_toolkit/offline_workflows/examples/discovery-session.json"
INPUT_FORMAT = "cbus-offline-discovery-session-input-v1"
COM = "discover_project_com_scan"
CNI = "discover_project_cni_project_scan"
OPEN = "open_networks"
SHELL = "ordinary_client_session"


@pytest.fixture
def tmp_path(tmp_path_factory):
    # Safe input/output boundaries reject macOS /var and /tmp symlink prefixes.
    return tmp_path_factory.mktemp("public-discovery-session").resolve()


@pytest.fixture
def backend_calls(monkeypatch):
    calls = []

    def blocked(name):
        def prohibit(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"Public offline preparation called {name}")
        return prohibit

    for module, name in ((socket, "socket"), (socket, "create_connection"),
                         (cni_discovery, "discover_cni"), (cni_discovery, "scan_cni"),
                         (cni_discovery, "scan_host_cni"), (pci_serial_probe, "probe_serial_interface"),
                         (subprocess, "Popen")):
        monkeypatch.setattr(module, name, blocked(name))
    for owner in (cgate.CGateClient, pci.PCIClient, networks.NativeNetworks, native.NativeProjects):
        monkeypatch.setattr(owner, "__init__", blocked(owner.__name__))
    return calls


def context(*, endpoint="fake://client", project=None, object_identity=None,
            connection_generation=0, selection_generation=0, model_generation=0):
    return {"flow_id": "synthetic-public-flow", "form_instance": "synthetic-public-form",
            "endpoint": endpoint, "connection_generation": connection_generation,
            "selection_generation": selection_generation, "project": project,
            "object_identity": object_identity, "model_generation": model_generation,
            "form_generation": 0}


def selected_context():
    return context(project="A", object_identity="//A/254/p/1", selection_generation=1, model_generation=1)


def captured_token(surface, operation_id, captured, row_id=None):
    return {"context": captured, "surface": surface, "operation_id": operation_id,
            "row_id": row_id or operation_id, "attempt": 1}


def callback(issue_id, token, outcome="completed", *, code=None):
    return {"kind": "callback", "issue_id": issue_id, "token": token,
            "outcome": {"kind": outcome, "detail": "Synthetic public CLI observation",
                        "terminal": True, "independent": False, "code": code}}


def session_document(actions):
    return {"format": INPUT_FORMAT, "surface": SHELL, "context": context(), "actions": actions}


def project_use_actions():
    return [
        {"kind": "select", "project": "A", "object_identity": "//A/254/p/1", "model_generation": 1},
        {"kind": "schedule", "operation_id": "use-A", "operation_kind": "project_use"},
        {"kind": "dispatch", "operation_id": "use-A", "issue_id": "use-A-issue"},
        callback("use-A-issue", captured_token(SHELL, "use-A", selected_context()), code=200),
    ]


def load_actions():
    return [{"kind": "schedule", "operation_id": "load-A", "operation_kind": "load"},
            {"kind": "dispatch", "operation_id": "load-A", "issue_id": "load-A-issue"}]


def write_input(tmp_path, document, name="input.json"):
    source = tmp_path / name
    source.write_text(json.dumps(document, allow_nan=False), encoding="utf-8")
    return source


def public_args(source, operation="plan", *, output=None, compact=False):
    arguments = ["offline-workflows", "discovery-session", operation, "--input", str(source)]
    if output is not None:
        arguments += ["--output", str(output)]
    if compact:
        arguments += ["--compact"]
    return arguments


def invoke(source, capsys, *, expected=0, operation="plan", output=None, compact=False):
    before = source.read_bytes()
    status = cli.main(public_args(source, operation, output=output, compact=compact))
    captured = capsys.readouterr()
    assert status == expected, (captured.out, captured.err)
    assert source.read_bytes() == before
    if expected in (0, 3):
        assert captured.err == ""
        envelope = json.loads(captured.out)
        assert envelope["workflow"] == "discovery-session"
        assert envelope["operation"] == operation
        assert envelope["input_sha256"] == hashlib.sha256(before).hexdigest()
    else:
        assert captured.out == ""
        envelope = json.loads(captured.err)
        assert "error" in envelope
        assert "Traceback" not in captured.err
    assert envelope["format"] == "cbus-offline-workflows-cli-v1"
    assert envelope["preparation_only"] is True
    for flag in ("execution_enabled", "native_execution_enabled", "original_compatibility_verified", "external_persistence_verified"):
        assert envelope[flag] is False
    if "report" in envelope:
        report = envelope["report"]
        assert report["preparation_only"] is True
        for flag in ("native_manual_executed", "hardware_executed", "io_performed", "physical_io_executed",
                     "runtime_executed", "native_compatible", "product_integrated"):
            assert report[flag] is False
    return envelope, captured.out


@pytest.mark.parametrize("operation", ["inspect", "validate", "plan"])
def test_public_command_routes_meaningful_com_cancel_example_without_backend(tmp_path, capsys, backend_calls, operation):
    source = write_input(tmp_path, json.loads(EXAMPLE.read_bytes()))
    envelope, _ = invoke(source, capsys, operation=operation)
    report = envelope["report"]
    assert report["validation_passed"] is True
    if operation == "inspect":
        assert report["outcome"] == "inspected"
        assert report["summary"]["timeline_replayed"] is False
        assert report["issued_operations"] == report["observations"] == []
        assert [row["phase"] for row in report["state"]["rows"]] == ["queued"] * 3
    else:
        assert report["outcome"] == "cancelled"
        assert [row["phase"] for row in report["state"]["rows"]] == ["completed", "interrupted", "cancelled_before_dispatch"]
        assert len(report["issued_operations"]) == 2
        assert report["state"]["journal"][-1]["reason"] == "cancelled_result"
        assert report["observations"][-1]["retained_records"][0]["presented"] is False
    assert backend_calls == []


def test_public_stale_focus_callback_keeps_original_identity_and_never_attaches_to_b(tmp_path, capsys, backend_calls):
    actions = project_use_actions() + load_actions() + [
        {"kind": "select", "project": "B", "object_identity": "//B/254/p/1", "model_generation": 2},
        callback("load-A-issue", captured_token(SHELL, "load-A", selected_context())),
    ]
    envelope, _ = invoke(write_input(tmp_path, session_document(actions)), capsys)
    report = envelope["report"]
    assert report["state"]["context"]["project"] == "B"
    assert report["state"]["context"]["object_identity"] == "//B/254/p/1"
    assert report["state"]["project_confirmed"] is None
    receipt = report["state"]["journal"][-1]
    assert receipt["callback"]["token"]["context"] == selected_context()
    assert receipt["reason"] == "selection_generation_mismatch" and not receipt["presented"]
    assert report["state"]["operations"][-1]["phase"] == "completed"
    assert [effect["kind"] for effect in report["effects"]] == ["project_use", "load"]
    assert backend_calls == []


@pytest.mark.parametrize("endpoint,reason", [("fake://client", "connection_generation_mismatch"),
                                               ("fake://other-client", "endpoint_mismatch")])
def test_public_reconnect_cannot_rebind_old_callback_or_dirty_editor(tmp_path, capsys, backend_calls, endpoint, reason):
    dirty = b"synthetic detached unsaved editor"
    actions = project_use_actions() + load_actions() + [
        {"kind": "dirty_editor", "editor": {"context": selected_context(), "payload_hex": dirty.hex()}},
        {"kind": "disconnect"}, {"kind": "reconnect", "endpoint": endpoint},
        callback("load-A-issue", captured_token(SHELL, "load-A", selected_context())),
    ]
    envelope, _ = invoke(write_input(tmp_path, session_document(actions)), capsys)
    state = envelope["report"]["state"]
    assert state["connected"] is True
    assert state["context"]["endpoint"] == endpoint and state["context"]["connection_generation"] == 2
    assert state["context"]["project"] is None and state["project_confirmed"] is None
    assert state["dirty_editor"] is None
    assert state["detached_editors"][0]["payload"] == {"hex": dirty.hex(), "byte_count": len(dirty)}
    assert state["journal"][-1]["reason"] == reason and not state["journal"][-1]["presented"]
    assert [effect["kind"] for effect in envelope["report"]["effects"]] == ["project_use", "load"]
    assert backend_calls == []


@pytest.mark.parametrize("field,value", [("connection_generation", 7), ("selection_generation", 7),
                                           ("endpoint", "fake://forged"), ("project", "FORGED")])
def test_public_forged_callback_context_is_schema_refusal(tmp_path, capsys, backend_calls, field, value):
    document = json.loads(EXAMPLE.read_bytes())
    document["actions"][1]["token"]["context"][field] = value
    envelope, _ = invoke(write_input(tmp_path, document), capsys, expected=2)
    assert envelope["error"]["code"] == "invalid_input"
    assert "report" not in envelope
    assert backend_calls == []


@pytest.mark.parametrize("mutation", [
    lambda document: document["context"].update({"connection_generation": True}),
    lambda document: document["actions"][1]["token"]["context"].pop("form_generation"),
    lambda document: document.update({"native_execution_enabled": True}),
])
def test_public_generation_claims_must_be_explicit_typed_and_without_authority(tmp_path, capsys, backend_calls, mutation):
    document = json.loads(EXAMPLE.read_bytes())
    mutation(document)
    envelope, _ = invoke(write_input(tmp_path, document), capsys, expected=2)
    assert envelope["error"]["code"] == "invalid_input"
    assert backend_calls == []


@pytest.mark.parametrize("change", ["unknown_surface", "native_profile", "resume", "wrong_cancel_surface"])
def test_public_unknown_native_and_wrong_surface_contracts_are_unsupported(tmp_path, capsys, backend_calls, change):
    document = json.loads(EXAMPLE.read_bytes())
    if change == "unknown_surface":
        document["surface"] = "invented-native-discovery-dialog"
    elif change == "native_profile":
        document["profile"] = "original-native-schedule-unverified"
    elif change == "resume":
        document["actions"] = [{"kind": "resume"}]
    else:
        document["surface"] = CNI
        document["actions"] = [{"kind": "com_cancel"}]
    envelope, _ = invoke(write_input(tmp_path, document), capsys, expected=3)
    report = envelope["report"]
    assert report["outcome"] == "unsupported" and report["validation_passed"] is False
    assert report["effects"] == []
    assert backend_calls == []


def test_public_unknown_open_receipt_after_stop_is_retained_without_replay_or_close(tmp_path, capsys, backend_calls):
    row = {"row_id": "one", "endpoint": "fake://network-one", "project": "PROJECT",
           "object_identity": "//PROJECT/254", "window_seconds": 2}
    captured = context(endpoint=row["endpoint"], project=row["project"], object_identity=row["object_identity"])
    document = {"format": INPUT_FORMAT, "surface": OPEN, "context": context(), "rows": [row], "actions": [
        {"kind": "dispatch", "issue_id": "open-issue", "row_ids": ["one"]}, {"kind": "stop"},
        callback("open-issue", captured_token(OPEN, "one:1", captured, "one"), "accepted"),
    ]}
    envelope, _ = invoke(write_input(tmp_path, document), capsys, expected=3)
    report = envelope["report"]
    assert report["validation_passed"] is True and report["outcome"] == "uncertain"
    assert report["state"]["rows"][0]["phase"] == "unknown_after_dispatch"
    assert report["state"]["journal"][-1]["reason"] == "stopped_after_dispatch"
    assert [effect["kind"] for effect in report["effects"]] == ["open_network"]
    assert report["action_history"][1]["effects"] == []
    assert backend_calls == []


def test_public_output_and_compact_preserve_exclusive_file_and_json_boundary(tmp_path, capsys, backend_calls):
    source = write_input(tmp_path, json.loads(EXAMPLE.read_bytes()))
    output = tmp_path / "prepared.json"
    envelope, rendered = invoke(source, capsys, output=output, compact=True)
    assert rendered.count("\n") == 1
    assert output.read_bytes() == rendered.encode("ascii")
    assert json.loads(output.read_bytes()) == envelope
    original = output.read_bytes()
    error, _ = invoke(source, capsys, expected=4, output=output, compact=True)
    assert error["error"]["code"] == "output_exists"
    assert output.read_bytes() == original
    assert backend_calls == []


def test_public_duplicate_json_is_rejected_before_model_dispatch(tmp_path, capsys, backend_calls):
    source = tmp_path / "input.json"
    source.write_bytes(b'{"format":"first","format":"duplicate"}')
    envelope, _ = invoke(source, capsys, expected=2)
    assert envelope["error"]["code"] == "duplicate_json_key"
    assert backend_calls == []


def test_actual_public_module_entrypoint_uses_selected_package_origin_and_preserves_preparation_flags(tmp_path):
    source = write_input(tmp_path, json.loads(EXAMPLE.read_bytes()))
    environment = dict(os.environ)
    selected_package_root = Path(cli.__file__).resolve().parents[1]
    environment["PYTHONPATH"] = str(selected_package_root)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    environment.pop("PYTHONSTARTUP", None)
    process = subprocess.run([sys.executable, "-S", "-m", "cbus_toolkit", *public_args(source, compact=True)],
                             cwd=tmp_path, env=environment, capture_output=True, check=False, timeout=10)
    assert process.returncode == 0, (process.stdout, process.stderr)
    assert process.stderr == b"" and process.stdout.count(b"\n") == 1
    envelope = json.loads(process.stdout)
    assert envelope["format"] == "cbus-offline-workflows-cli-v1"
    assert envelope["execution_enabled"] is False and envelope["native_execution_enabled"] is False
    assert envelope["report"]["outcome"] == "cancelled"
    assert envelope["report"]["io_performed"] is False
    assert envelope["report"]["hardware_executed"] is False
    assert envelope["report"]["native_manual_executed"] is False
