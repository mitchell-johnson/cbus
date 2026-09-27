"""Source-bound, exact-wire direct and combined Unit XML mapper oracle."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "rust/testdata/fixtures/native_cgate_dbsetxml_unit_vm.json"
COMBINED = ROOT / "rust/testdata/fixtures/native_cgate_dbsetxml_combined_vm.json"
EXPERIMENT = ROOT / "toolkit-cli/research/experiments/2026-09-28"
PINNED = {
    NATIVE: "6ae63e7a36de13cdd5af034ba132dcda9b452dc5bc3a5e403a3213423e9ce70d",
    COMBINED: "7d850980d52a05103796bfcb01ca49a4fda5db23177387c0ad1d72978953abae",
    EXPERIMENT / "cgate-dbsetxml-unit-vm-capture.ps1":
        "2f82dfd8ede8d350b91497b814825b783788675c93967c5d3edf529026a07e7a",
    EXPERIMENT / "cgate-dbsetxml-unit-vm-offline.ps1":
        "a56c3f9ed1e1f94ebd6d94b7884178e6116a0b06415bae1d1d4a7fa9bd958641",
    EXPERIMENT / "cgate-dbsetxml-unit-vm-offline.json":
        "2fb3b48dd954009776a75b1fe2350869c9b2283b3cf1e3536c4de9e58fa6101c",
    EXPERIMENT / "cgate-dbsetxml-unit-vm-cleanup.json":
        "ed7edf996f56433aa4fd242c8a14e8ecd165827babef79d3f12ed667ad31ff92",
}


def data():
    return json.loads(NATIVE.read_text(encoding="utf-8"))


def cases():
    return {row["tag"]: row for row in data()["cases"]}


def xml_payload(row):
    tag = row["tag"]
    lines = row["response_lines"]
    assert lines[0] == f"[{tag}] 343-Begin XML snippet\r\n"
    assert lines[1] == f'[{tag}] 347-<?xml version="1.0" encoding="utf-8"?>\n'
    assert lines[2].startswith(f"[{tag}] 347-") and lines[2].endswith("\r\n")
    assert lines[3] == f"[{tag}] 344 End XML snippet\r\n"
    payload = lines[2][len(f"[{tag}] 347-"):-2]
    ET.fromstring(payload)
    return payload


def test_original_identity_and_owned_vm_cleanup_are_source_bound():
    for path, expected in PINNED.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    native = data()
    assert native["format"] == "native-cgate-dbsetxml-unit-vm-fixture-v1"
    assert native["raw_capture_sha256"] == "783ba91dd449c90c0ef8ae3c724f9517e681883f01f2588d504e0e94fc8c03a9"
    assert native["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert native["capture_script_sha256"] == PINNED[EXPERIMENT / "cgate-dbsetxml-unit-vm-capture.ps1"]
    assert native["default_route_count"] == 0
    assert native["service_listeners"] == [
        f"127.0.0.1:{port}" for port in (24100, 24101, 24102, 24103, 24110, 24111)
    ]
    assert native["greeting"] == (
        "201 Service ready: Schneider Electric C-Gate Version: v3.4.0 "
        "(build 2001) #cmd-syntax=1.0\r\n"
    )
    offline = json.loads((EXPERIMENT / "cgate-dbsetxml-unit-vm-offline.json").read_text())
    cleanup = json.loads((EXPERIMENT / "cgate-dbsetxml-unit-vm-cleanup.json").read_text())
    assert offline["default_routes_before"] == 1
    assert offline["default_routes_after"] == 0
    assert offline["captured_utc"] < native["captured_utc"] < cleanup["captured_utc"]
    assert cleanup == {
        "captured_utc": cleanup["captured_utc"],
        "process_exit_confirmed": True,
        "work_removed": True,
        "default_route_count": 0,
        "original_home_restored": True,
    }


def test_twenty_one_original_commands_preserve_tag_status_and_line_framing():
    rows = data()["cases"]
    assert [row["tag"] for row in rows] == [str(tag) for tag in range(800, 821)]
    for row in rows:
        tag = row["tag"]
        request = row["request"]
        assert request.startswith(f"[{tag}] {row['command']}\r\n")
        if row["command"].startswith("DBSETXML "):
            assert request.endswith(f"\r\nEND{tag}\r\n")
            assert request.count(f"\r\nEND{tag}\r\n") == 1
        else:
            assert request == f"[{tag}] {row['command']}\r\n"
        assert row["response_lines"]
        for line in row["response_lines"]:
            assert line.startswith(f"[{tag}] ")
            assert line.endswith("\r\n") or line == (
                f'[{tag}] 347-<?xml version="1.0" encoding="utf-8"?>\n'
            )
    for tag in ("802", "807", "809", "811", "812", "814", "815", "817", "819"):
        xml_payload(rows[int(tag) - 800])


def test_direct_unit_and_combined_network_mapper_drop_the_same_unknown_namespaced_markup():
    rows = cases()
    original = xml_payload(rows["809"])
    assert ET.fromstring(original).findtext("UnitName") == "Room"
    for set_tag, read_tag in (("810", "811"), ("813", "814"), ("816", "817"), ("818", "819")):
        request = rows[set_tag]["request"]
        assert "urn:cbus:oracle:2026" in request
        assert "ext:flag" in request or "ext:Diagnostic" in request
        assert rows[set_tag]["response_lines"] == [
            f"[{set_tag}] 301 OID=" + (
                "11111111-1111-4111-8111-111111111111" if set_tag in ("810", "813")
                else data()["network_oid"]
            ) + "\r\n"
        ]
        assert xml_payload(rows[read_tag]) == original
    assert "xmlns:ext" not in xml_payload(rows["812"])
    assert "xmlns:ext" not in xml_payload(rows["815"])
    assert "<Application>" in xml_payload(rows["812"])
    assert rows["804"]["response_lines"] == [
        "[804] 131 network=254 State=new InterfaceState=closed\r\n"
    ]
    assert rows["820"]["response_lines"] == [
        "[820] 131 network=254 State=new InterfaceState=closed\r\n"
    ]
    prior = json.loads(COMBINED.read_text(encoding="utf-8"))
    assert xml_payload(prior["cases"][6]) == original  # prior tag 906, plain Unit
