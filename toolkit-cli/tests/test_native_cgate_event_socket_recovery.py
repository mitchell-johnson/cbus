"""Source-bound original C-Gate outbound event-socket recovery observation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "rust/testdata/fixtures/native_cgate_event_socket_recovery.json"
SCRIPT = ROOT / "rust/cbus-cgate/research/native_event_socket_recovery_probe.py"
TRANSPORT_SCRIPT = ROOT / "rust/cbus-cgate/research/native_config_event_transport_probe.py"
HARNESS = ROOT / "toolkit-cli/research/local_cgate.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def receipt() -> dict:
    return json.loads(CAPTURE.read_text())


def test_native_event_recovery_capture_is_source_bound_and_owned() -> None:
    captured = receipt()
    assert captured["schema"] == "native-cgate-event-socket-recovery-v2"
    oracle = captured["oracle"]
    assert oracle["version"] == "3.4.0 build 2001"
    assert oracle["jar_sha256"] == (
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    )
    assert oracle["capture_script_sha256"] == digest(SCRIPT)
    assert oracle["transport_probe_sha256"] == digest(TRANSPORT_SCRIPT)
    assert oracle["harness_sha256"] == digest(HARNESS)
    assert oracle["physical_endpoint"] is False
    assert set(oracle["children"]) == {"initial_sink_absent", "initial_sink_present"}
    for child in oracle["children"].values():
        assert child == {
            "listener_ownership_verified": True,
            "cleanup_complete": True,
            "process_exit_confirmed": True,
            "work_removed": True,
        }


def test_native_event_socket_does_not_retry_within_observed_60_second_bounds() -> None:
    captured = receipt()
    absent = captured["initial_sink_absent"]
    assert absent["absent"]["sink_bound_not_listening"] is True
    assert absent["absent"]["broadcast_response"] == ["[absent] 200 OK."]
    first = absent["first_connection"]
    assert first["accepted"] is False
    assert first["accept_delay_seconds"] >= 60
    assert absent["quit_response"] == ["[quit] 204 Closing connection."]

    present = captured["initial_sink_present"]
    assert present["sink_listening_before_start"] is True
    assert present["sink_peer_ip"] == "127.0.0.1"
    assert present["startup_codes"] == [800]
    assert present["connected_codes"] == [803, 703]
    assert present["connected_broadcast_response"] == ["[online] 200 OK."]
    assert present["rst_after_connected_broadcast"] is True
    assert present["disconnected_broadcast_response"] == ["[lost] 200 OK."]
    assert present["reconnected"] is False
    assert present["reconnect_delay_seconds"] >= 60
    assert present["quit_response"] == ["[quit] 204 Closing connection."]
