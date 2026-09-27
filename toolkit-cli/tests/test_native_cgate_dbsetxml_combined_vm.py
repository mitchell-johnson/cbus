"""Retained, exact-wire original C-Gate combined-Network XML oracle.

The Windows VM capture is deliberately read-only in this test. It describes
the original mapper, including behavior not yet reproduced by Rust.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "rust/testdata/fixtures/native_cgate_dbsetxml_combined_vm.json"
EXPERIMENT = ROOT / "toolkit-cli/research/experiments/2026-09-28"
PINNED = {
    FIXTURE: "7d850980d52a05103796bfcb01ca49a4fda5db23177387c0ad1d72978953abae",
    EXPERIMENT / "cgate-dbsetxml-vm-capture.ps1":
        "eea936de6596082a17720ffb9e1ee2198df44dac254a34a7a2c53dbfe2e8d1c6",
    EXPERIMENT / "cgate-dbsetxml-vm-service.ps1":
        "37b9515a1ab7d0fe1e66b43390f7d12d5ad9cd4cb9b78abb809566f2fd15525d",
    EXPERIMENT / "cgate-dbsetxml-vm-cleanup.json":
        "787757b68ea62b44623f4081eca7c07714a3337f1b89e8f3860aba4529614724",
}


def capture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def by_tag():
    return {row["tag"]: row for row in capture()["cases"]}


def readback(row):
    tag = row["tag"]
    lines = row["response_lines"]
    assert lines[0] == f"[{tag}] 343-Begin XML snippet\r\n"
    assert lines[1] == f'[{tag}] 347-<?xml version="1.0" encoding="utf-8"?>\n'
    assert lines[2].startswith(f"[{tag}] 347-") and lines[2].endswith("\r\n")
    assert lines[3] == f"[{tag}] 344 End XML snippet\r\n"
    return ET.fromstring(lines[2][len(f"[{tag}] 347-"):-2])


def test_source_bound_fixture_and_disposable_guest_cleanup():
    for path, expected in PINNED.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    data = capture()
    assert data["format"] == "native-cgate-dbsetxml-vm-fixture-v1"
    assert data["raw_capture_sha256"] == "7d9c5ba9e7c15a8efc78b6796f8e599356969cf7405c4d907fe0c5e8bc91ea45"
    assert data["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert data["java_sha256"] == "37048fe85e763554aa104d6711531b185271905a81ff7fb055978acf8eaea5f7"
    assert data["capture_script_sha256"] == PINNED[EXPERIMENT / "cgate-dbsetxml-vm-capture.ps1"]
    assert data["service_listeners"] == [f"127.0.0.1:{port}" for port in (24100, 24101, 24102, 24103, 24110, 24111)]
    assert data["default_route_count"] == 0
    assert data["greeting"] == "201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001) #cmd-syntax=1.0\r\n"
    cleanup = json.loads((EXPERIMENT / "cgate-dbsetxml-vm-cleanup.json").read_text(encoding="utf-8"))
    assert cleanup["process_exit_confirmed"] is True
    assert cleanup["work_removed"] is True
    assert cleanup["original_home_restored"] is True
    assert cleanup["default_route_count"] == 0
    assert cleanup["captured_utc"] > data["captured_utc"]


def test_all_sixteen_native_requests_have_exact_numeric_tagged_wire():
    rows = capture()["cases"]
    assert [r["tag"] for r in rows] == [str(n) for n in range(900, 916)]
    assert len(rows) == 16
    for row in rows:
        tag = row["tag"]
        request = row["request"]
        assert request.startswith(f"[{tag}] {row['command']}\r\n")
        if "DBSETXML" in row["command"]:
            assert request.endswith(f"\r\nEND{tag}\r\n")
            assert request.count(f"\r\nEND{tag}\r\n") == 1
        else:
            assert request == f"[{tag}] {row['command']}\r\n"
        assert row["response_lines"]
        for line in row["response_lines"]:
            assert line.startswith(f"[{tag}] ")
            assert line.endswith("\n")
            assert line.endswith("\r\n") or line.startswith(
                f'[{tag}] 347-<?xml version="1.0" encoding="utf-8"?>'
            )
    for tag in ("901", "903", "905", "906", "907", "909", "911", "913"):
        readback(rows[int(tag) - 900])


def test_combined_graph_acceptance_mapper_drop_and_omission_are_separate_cases():
    rows = by_tag()
    data = capture()
    oid = data["network_oid"]
    assert rows["900"]["response_lines"] == ["[900] 200 OK.\r\n"]
    for tag in ("902", "904", "908", "910", "912"):
        assert rows[tag]["response_lines"] == [f"[{tag}] 301 OID={oid}\r\n"]

    # The local Network is reset to a known empty baseline before the new
    # combined document, so these observations do not depend on prior state.
    baseline = readback(rows["903"])
    assert baseline.tag == "Network"
    assert [child.tag for child in baseline] == ["OID", "TagName", "Address", "NetworkNumber", "Interface"]
    assert baseline.findtext("OID") == oid
    assert baseline.findtext("Interface/InterfaceAddress") == "127.0.0.1:1"

    combined = readback(rows["905"])
    assert [child.tag for child in combined][-2:] == ["Application", "Unit"]
    assert combined.findtext("Application/Address") == "56"
    assert combined.findtext("Unit/Address") == "20"
    assert combined.findtext("Unit/UnitName") == "Room"
    assert readback(rows["906"]).tag == "Unit"
    assert readback(rows["907"]).tag == "Application"
    assert [child.tag for child in combined.find("Unit")] == [
        "OID", "TagName", "Address", "UnitType", "UnitName", "FirmwareVersion"
    ]

    # Both namespaced, unknown submissions get 301, but the original mapper
    # omits their extension markup on subsequent Network readback.
    for submission, result in (("908", "909"), ("910", "911")):
        assert "urn:cbus:oracle:2026" in rows[submission]["request"]
        observed = readback(rows[result])
        assert ET.tostring(observed) == ET.tostring(combined)
        assert "Diagnostic" not in rows[result]["response_lines"][2]
        assert "flag" not in rows[result]["response_lines"][2]

    omitted = readback(rows["913"])
    assert omitted.find("Application") is None
    assert omitted.findtext("Unit/UnitName") == "Room"
    assert rows["914"]["response_lines"] == [
        "[914] 401 Bad object or device ID: Element 56 not found.\r\n"
    ]
    assert rows["915"]["response_lines"] == [
        "[915] 131 network=254 State=new InterfaceState=closed\r\n"
    ]
