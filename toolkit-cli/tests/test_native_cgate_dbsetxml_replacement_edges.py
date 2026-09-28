"""Owned native C-Gate 3.4 DBSETXML replacement evidence, without live I/O."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "rust/testdata/fixtures/native_cgate_dbsetxml_replacement_edges.json"
SCRIPT = ROOT / "toolkit-cli/research/cgate_dbsetxml_replacement_edges.py"
HARNESS = ROOT / "toolkit-cli/research/local_cgate.py"


def capture():
    return json.loads(CAPTURE.read_text(encoding="utf-8"))


def rows():
    return {row["tag"]: row for row in capture()["cases"]}


def status(row):
    return int(row["response_lines"][-1].split()[1])


def xml(row):
    tag = row["tag"]
    lines = row["response_lines"]
    assert lines[0] == f"[{tag}] 343-Begin XML snippet\r\n"
    assert lines[1] == f'[{tag}] 347-<?xml version="1.0" encoding="utf-8"?>\n'
    assert lines[-1] == f"[{tag}] 344 End XML snippet\r\n"
    assert len(lines) == 4
    prefix = f"[{tag}] 347-"
    assert lines[2].startswith(prefix) and lines[2].endswith("\r\n")
    return lines[2][len(prefix):-2]


def test_capture_is_source_bound_and_disposable():
    evidence = capture()
    assert evidence["schema"] == "native-cgate-dbsetxml-replacement-edges-v1"
    assert evidence["capture_script_sha256"] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert evidence["service_harness_sha256"] == hashlib.sha256(HARNESS.read_bytes()).hexdigest()
    oracle = evidence["oracle"]
    for key, expected in {
        "jar_sha256": "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630",
        "java_sha256": "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4",
        "version": "3.4.0 build 2001",
        "owned_loopback_listeners": True,
        "cleanup_complete": True,
        "process_exit_confirmed": True,
        "work_removed": True,
        "physical_endpoint": False,
    }.items():
        assert oracle[key] == expected
    listeners = oracle["listeners"]
    assert len(listeners) == 6
    assert all(listener.startswith("127.0.0.1:") for listener in listeners)
    assert evidence["greeting"] == (
        "201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001) "
        "#cmd-syntax=1.0\r\n"
    )
    assert len(evidence["network_oid"].split("-")) == 5
    assert len(evidence["interface_oid"].split("-")) == 5
    assert [row["tag"] for row in evidence["cases"]] == list(range(100, 137))
    for row in evidence["cases"]:
        tag = row["tag"]
        if row["command"].startswith("DBSETXML "):
            assert row["request"].startswith(f"[{tag}] {row['command']} << END{tag}\r\n")
            assert row["request"].endswith(f"\r\nEND{tag}\r\n")
        else:
            assert row["request"] == f"[{tag}] {row['command']}\r\n"
        assert all(line.startswith(f"[{tag}] ") for line in row["response_lines"])
        assert row["response_lines"][-1].startswith(f"[{tag}] {status(row)} ")


def test_mapper_omits_extensions_and_clears_missing_fields():
    case = rows()
    for tag in (104, 107, 111, 114, 116, 118, 127, 129):
        assert status(case[tag]) == 301
    assert xml(case[105]) == xml(case[108]) == xml(case[112])
    assert xml(case[106]) == xml(case[109]) == xml(case[115])
    assert xml(case[110]) == xml(case[113])
    for tag in (108, 109, 110, 112, 113, 115):
        readback = xml(case[tag])
        assert "urn:edge" not in readback
        assert "<!--" not in readback
        assert "<?edge" not in readback
        assert "Diagnostic" not in readback
    assert "<Description></Description>" in xml(case[117])
    assert "Nested" not in xml(case[117])
    minimal = ET.fromstring(xml(case[119]))
    assert [child.tag for child in minimal] == [
        "OID", "TagName", "Address", "UnitType", "UnitName", "FirmwareVersion"
    ]
    assert status(case[120]) == status(case[121]) == 401
    assert "Object is null" in case[120]["response_lines"][-1]


def test_saved_reload_and_native_conflict_boundary():
    case = rows()
    assert [status(case[tag]) for tag in (122, 123, 124)] == [200, 200, 200]
    reloaded = ET.fromstring(xml(case[125]))
    assert reloaded.findtext("Application/Address") == "56"
    assert reloaded.findtext("Unit/Address") == "20"
    assert reloaded.find("Unit/CatalogNumber") is None
    assert reloaded.find("Unit/SerialNumber") is None
    assert reloaded.find("Unit/PP") is None
    unit = ET.fromstring(xml(case[126]))
    assert unit.findtext("OID") == "11111111-1111-4111-8111-111111111111"
    assert unit.find("CatalogNumber") is None

    mixed = xml(case[128])
    assert "<Description>AB</Description>" in mixed
    assert "<Foo>" not in mixed and "Nested" not in mixed
    assert "<CatalogNumber></CatalogNumber>" in xml(case[130])
    assert "<Opaque" not in xml(case[130])

    # The native mapper accepts duplicate identities. Rust deliberately
    # rejects these because its keyed model cannot retain both objects.
    assert status(case[131]) == status(case[133]) == 301
    collision = ET.fromstring(xml(case[132]))
    assert collision.findtext("Application/OID") == collision.findtext("Unit/OID")
    duplicate = ET.fromstring(xml(case[134]))
    units = duplicate.findall("Unit")
    assert [unit.findtext("Address") for unit in units] == ["20", "21"]
    assert units[0].findtext("OID") == units[1].findtext("OID")
    assert status(case[135]) == 446
    assert xml(case[136]) == xml(case[134])
