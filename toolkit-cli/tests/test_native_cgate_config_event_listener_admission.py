"""Original event listener remains open when command admission denies peers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "rust/testdata/fixtures/native_cgate_config_event_listener_admission.json"


def receipt() -> dict:
    return json.loads(FIXTURE.read_text())


def test_event_listener_admission_receipt_is_owned_and_source_bound() -> None:
    report = receipt()
    assert report["schema"] == "native-cgate-config-event-listener-admission-v1"
    assert report["oracle"]["version"] == "3.4.0 build 2001"
    assert report["oracle"]["jar_sha256"] == (
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    )
    assert report["oracle"]["java_sha256"] == (
        "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
    )
    assert report["oracle"]["physical_endpoint"] is False
    assert "no physical endpoint" in report["scope"]
    assert set(report["cases"]) == {"plain", "mtls"}
    for name, expected in report["oracle"]["source_hashes"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    assert report["oracle"]["source_hashes_after"] == report["oracle"]["source_hashes"]
    for case in report["cases"].values():
        assert case["cleanup"] == {
            "listener_ownership_verified": True,
            "process_exit_confirmed": True,
            "cleanup_complete": True,
            "work_removed": True,
        }


def test_original_event_listener_bypasses_command_allowlist_and_mtls() -> None:
    cases = receipt()["cases"]
    assert cases["plain"]["mtls_configured"] is False
    assert cases["plain"]["baseline_tls_greeting"] is None
    assert cases["plain"]["new_tls_command"] is None
    assert cases["mtls"]["mtls_configured"] is True
    assert cases["mtls"]["baseline_tls_greeting"] == "greeting"
    assert cases["mtls"]["new_tls_command"] == "handshake-timeout"
    for name, case in cases.items():
        assert case["command_greeting"].startswith(
            "201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001)"
        )
        assert case["allowlist_set"] == "[deny] 200 OK."
        assert case["new_plain_command"] == "connected-silent"
        assert case["new_event_peer_ip"] == "127.0.0.1"
        assert case["broadcast_response"] == "[broadcast] 200 OK."
        row = case["broadcast_event_row"]
        assert row in case["event_rows"]
        assert re.fullmatch(
            r"\d{8}-\d{6}\.\d{3} 703 cmd\d+ - broadcast_event SP class event-admission-"
            + name,
            row,
        )
