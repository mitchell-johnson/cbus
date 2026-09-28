"""Source-bound original C-Gate event transport capture (no native runtime in CI)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "rust/testdata/fixtures/native_cgate_config_event_transport.json"
SCRIPT = ROOT / "rust/cbus-cgate/research/native_config_event_transport_probe.py"
HARNESS = ROOT / "toolkit-cli/research/local_cgate.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code(row: str) -> str:
    assert re.fullmatch(r"\d{8}-\d{6}\.\d{3} \d{3} .+", row), row
    return row.split(" ", 2)[1]


def test_owned_event_transport_oracle_is_source_bound_and_clean() -> None:
    receipt = json.loads(CAPTURE.read_text())
    assert receipt["schema"] == "native-cgate-config-event-transport-v1"
    assert receipt["oracle"]["jar_sha256"] == (
        "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    )
    assert receipt["oracle"]["capture_script_sha256"] == digest(SCRIPT)
    assert receipt["oracle"]["harness_sha256"] == digest(HARNESS)
    assert receipt["oracle"]["physical_endpoint"] is False
    assert len(receipt["oracle"]["children"]) == 5
    for child in receipt["oracle"]["children"].values():
        assert child == {
            "listener_ownership_verified": True,
            "cleanup_complete": True,
            "process_exit_confirmed": True,
            "work_removed": True,
        }


def test_event_server_levels_and_socket_wire_are_original_observations() -> None:
    receipt = json.loads(CAPTURE.read_text())
    server = receipt["server"]
    assert all(case["no_event_greeting"] for case in server.values())
    assert [code(row) for row in server["0"]["events"]] == []
    assert [code(row) for row in server["3"]["events"]] == ["703"]
    assert [code(row) for row in server["5"]["events"]] == ["803", "703", "804"]
    level9 = [code(row) for row in server["9"]["events"]]
    assert "761" in level9 and "766" in level9 and "703" in level9
    assert server["5"]["same_process_config"]["old_event_port_still_accepts"] is True
    assert server["5"]["same_process_config"]["new_event_port_unbound"] is True
    assert [code(row) for row in receipt["socket"]["events"]] == ["800", "803", "703", "804"]
    assert receipt["socket"]["sink_peer_ip"] == "127.0.0.1"
