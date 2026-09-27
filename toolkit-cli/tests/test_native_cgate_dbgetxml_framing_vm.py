"""Source-bound original C-Gate XML TCP framing, including pipelining."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = ROOT / "toolkit-cli/research/experiments/2026-09-28"
FIXTURE = ROOT / "rust/testdata/fixtures/native_cgate_dbgetxml_framing_vm.json"
VECTOR = ROOT / "rust/testdata/vectors/cgate_dbgetxml_wire.json"
PINNED = {
    FIXTURE: "c819303fbe8d38d552fa3aa9b80fbe60ca1161ae731f1aeb830323f0e7e6863a",
    VECTOR: "42b22fe1933392734d33728e224c7fef597fc1d73bd827952316e83526dd1b9e",
    EXPERIMENT / "cgate-dbgetxml-framing-vm-capture.ps1":
        "0b746a87e54be363f771d31a38b94e0ac05e794c3dce4415a63c469dd6b87c7a",
    EXPERIMENT / "cgate-dbgetxml-framing-vm-route.json":
        "7cbf9952bb1670cabc68e82facaf641448e553c2889f5baa04a6547e7beafc52",
    EXPERIMENT / "cgate-dbgetxml-framing-vm-cleanup.json":
        "37eaa8f20f9657211302e746d4f581aed7be00f78ba08dc8ad573562d8cc1131",
    EXPERIMENT / "cgate-dbsetxml-unit-vm-offline.ps1":
        "a56c3f9ed1e1f94ebd6d94b7884178e6116a0b06415bae1d1d4a7fa9bd958641",
    EXPERIMENT / "cgate-dbsetxml-vm-service.ps1":
        "37b9515a1ab7d0fe1e66b43390f7d12d5ad9cd4cb9b78abb809566f2fd15525d",
}


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def cases():
    return {row["tag"]: row for row in fixture()["cases"]}


def payload(row):
    tag = row["tag"]
    lines = row["response_lines"]
    assert lines[0] == f"[{tag}] 343-Begin XML snippet\r\n"
    assert lines[1] == f'[{tag}] 347-<?xml version="1.0" encoding="utf-8"?>\n'
    assert lines[2].startswith(f"[{tag}] 347-") and lines[2].endswith("\r\n")
    assert lines[3] == f"[{tag}] 344 End XML snippet\r\n"
    xml = lines[2][len(f"[{tag}] 347-"):-2]
    ET.fromstring(xml)
    return xml


def test_original_source_identity_offline_route_and_cleanup():
    for path, digest in PINNED.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    observed = fixture()
    route = json.loads((EXPERIMENT / "cgate-dbgetxml-framing-vm-route.json").read_text())
    cleanup = json.loads((EXPERIMENT / "cgate-dbgetxml-framing-vm-cleanup.json").read_text())
    assert observed["format"] == "native-cgate-dbgetxml-framing-vm-v1"
    assert observed["raw_capture_sha256"] == "b7e9cd47f6a05db377ff3a9ea1c2c2bcedc52eb8d18722f9bf084b1e64c8ab43"
    assert observed["route_raw_sha256"] == "a4b2d58d268aec8e7c03b07679bf5877d5126092a306e1da4af05603529ea1c8"
    assert observed["cleanup_raw_sha256"] == "b0c0c1aeaa2a9c5020587496a9def2d0e95f4eef4a73ee1672c619373e2f5c50"
    assert observed["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert observed["capture_script_sha256"] == PINNED[EXPERIMENT / "cgate-dbgetxml-framing-vm-capture.ps1"]
    assert observed["route_script_sha256"] == PINNED[EXPERIMENT / "cgate-dbsetxml-unit-vm-offline.ps1"]
    assert observed["service_script_sha256"] == PINNED[EXPERIMENT / "cgate-dbsetxml-vm-service.ps1"]
    assert observed["default_route_count"] == route["default_routes_after"] == cleanup["default_route_count"] == 0
    assert route["default_routes_before"] == 1
    assert route["captured_utc"] < observed["captured_utc"] < cleanup["captured_utc"]
    assert observed["service_listeners"] == [
        f"127.0.0.1:{port}" for port in (24100, 24101, 24102, 24103, 24110, 24111)
    ]
    assert observed["greeting"] == (
        "201 Service ready: Schneider Electric C-Gate Version: v3.4.0 "
        "(build 2001) #cmd-syntax=1.0\r\n"
    )
    assert cleanup["process_exit_confirmed"] is True
    assert cleanup["work_removed"] is True
    assert cleanup["original_home_restored"] is True


def test_xml_address_oid_error_and_pipelined_wire_rows():
    rows = cases()
    assert list(rows) == ["900", "901", *[str(n) for n in range(903, 915)]]
    for tag, row in rows.items():
        assert row["request"].startswith(f"[{tag}] {row['command']}\r\n")
        assert row["response_lines"]
        assert all(line.startswith(f"[{tag}] ") for line in row["response_lines"])
        assert all(line.endswith("\r\n") or line ==
                   f'[{tag}] 347-<?xml version="1.0" encoding="utf-8"?>\n'
                   for line in row["response_lines"])
    assert rows["905"]["response_lines"] == [f"[905] 301 OID={fixture()['network_oid']}\r\n"]
    assert rows["907"]["response_lines"] == [f"[907] 301 OID={fixture()['network_oid']}\r\n"]
    network = payload(rows["908"])
    assert "<Application>" in network and "<Unit>" in network
    unit = payload(rows["909"])
    assert unit == payload(rows["911"]) == payload(rows["913"])
    assert ET.fromstring(unit).findtext("UnitName") == "Room"
    assert ET.fromstring(payload(rows["910"])).tag == "Application"
    assert rows["912"]["response_lines"] == [
        "[912] 401 Bad object or device ID: Element 21 not found.\r\n"
    ]
    assert rows["913"]["request"] + rows["914"]["request"] == (
        "[913] DBGETXML //XFRAME/254/p/20\r\n[914] NOOP\r\n"
    )
    assert rows["914"]["response_lines"] == ["[914] 200 OK.\r\n"]
    vector = json.loads(VECTOR.read_text(encoding="utf-8"))
    assert vector["format"] == "cgate-dbgetxml-native-wire-v1"
    assert vector["native_fixture_sha256"] == PINNED[FIXTURE]
    assert vector["jar_sha256"] == fixture()["jar_sha256"]
    assert vector["cases"] == [
        {key: row[key] for key in ("tag", "command", "request", "response_lines")}
        for row in fixture()["cases"] if row["tag"] in
        {"906", "908", "909", "910", "911", "912", "913", "914"}
    ]
