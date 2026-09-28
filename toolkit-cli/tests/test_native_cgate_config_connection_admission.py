"""Source-bound owned native C-Gate command-admission evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "rust/testdata/fixtures/native_cgate_config_connection_admission.json"
CAPTURE = ROOT / "rust/cbus-cgate/research/native_config_connection_admission_probe.py"
HARNESS = ROOT / "toolkit-cli/research/local_cgate.py"


def test_native_command_admission_receipt_is_source_bound_and_owned() -> None:
    report = json.loads(FIXTURE.read_text())
    assert report["schema"] == "native-cgate-config-connection-admission-v1"
    oracle = report["oracle"]
    assert oracle["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert oracle["java_sha256"] == "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
    assert oracle["capture_script_sha256"] == hashlib.sha256(CAPTURE.read_bytes()).hexdigest()
    assert oracle["harness_sha256"] == hashlib.sha256(HARNESS.read_bytes()).hexdigest()
    assert oracle["physical_endpoint"] is False
    assert set(oracle["children"]) == {
        "default", "runtime", "denied", "allowed", "multiple", "hostname"
    }
    assert all(
        child[key] is True
        for child in oracle["children"].values()
        for key in (
            "listener_ownership_verified",
            "process_exit_confirmed",
            "cleanup_complete",
            "work_removed",
        )
    )
    assert "no physical endpoint" in report["scope"]


def test_native_command_admission_is_immediate_despite_restart_metadata() -> None:
    report = json.loads(FIXTURE.read_text())
    assert report["default"]["commands"] == [
        {
            "command": "CONFIG GET accept-connections-from",
            "response": ["[default] 303 accept-connections-from=all"],
        },
        {
            "command": "CONFIG INFO accept-connections-from",
            "response": [
                "[info] 304-parameter=accept-connections-from",
                "[info] 304-value=all",
                "[info] 304-description=Space separated list of IP addresses or hostnames from which to accept command connections",
                "[info] 304-defaultValue=all",
                "[info] 304-scope=global",
                "[info] 304 effective=restart",
            ],
        },
    ]
    runtime = report["runtime"]
    assert [row["response"][-1].split("] ", 1)[1] for row in runtime["commands"]] == [
        "303 accept-connections-from=127.0.0.1",
        "200 OK.",
        "303 accept-connections-from=192.0.2.55",
        "200 OK.",
        "200 OK.",
        "200 OK.",
        "200 OK.",
    ]
    assert runtime["after_set"]["outcome"] == "connected-no-greeting-timeout"
    assert runtime["after_save"]["outcome"] == "connected-no-greeting-timeout"
    assert runtime["after_reallow"]["outcome"] == "greeting"
    assert runtime["after_reload"]["outcome"] == "connected-no-greeting-timeout"
    assert report["fresh_denied"]["outcome"] == "connected-no-greeting-timeout"
    assert report["fresh_denied_long"] == {
        "passive_wait_seconds": 12,
        "after_noop_wait_seconds": 3,
        "passive_outcome": "silent-timeout",
        "after_noop_outcome": "silent-timeout",
    }
    assert report["fresh_allowed"]["outcome"] == "greeting"
    assert report["fresh_multiple"]["outcome"] == "greeting"
    assert report["fresh_hostname"]["outcome"] == "greeting"
