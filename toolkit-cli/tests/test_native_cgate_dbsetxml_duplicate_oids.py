"""Source-bound owned native evidence for duplicate DBSETXML identities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "rust/testdata/fixtures/native_cgate_dbsetxml_duplicate_oids.json"
SCRIPT = ROOT / "toolkit-cli/research/cgate_dbsetxml_duplicate_oids.py"
HARNESS = ROOT / "toolkit-cli/research/local_cgate.py"


def evidence():
    return json.loads(CAPTURE.read_text(encoding="utf-8"))


def rows():
    return {row["tag"]: row for row in evidence()["cases"]}


def status(row):
    return int(row["response_lines"][-1].split()[1])


def xml(row):
    tag = row["tag"]
    lines = row["response_lines"]
    assert lines[0] == f"[{tag}] 343-Begin XML snippet\r\n"
    assert lines[1] == f'[{tag}] 347-<?xml version="1.0" encoding="utf-8"?>\n'
    assert lines[-1] == f"[{tag}] 344 End XML snippet\r\n"
    assert len(lines) == 4
    assert lines[2].startswith(f"[{tag}] 347-") and lines[2].endswith("\r\n")
    return lines[2][len(f"[{tag}] 347-"):-2]


def test_capture_is_source_bound_and_owned():
    captured = evidence()
    assert captured["schema"] == "native-cgate-dbsetxml-duplicate-oids-v1"
    assert captured["capture_script_sha256"] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert captured["service_harness_sha256"] == hashlib.sha256(HARNESS.read_bytes()).hexdigest()
    oracle = captured["oracle"]
    assert oracle["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert oracle["java_sha256"] == "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
    assert oracle["version"] == "3.4.0 build 2001"
    for key in ("owned_loopback_listeners", "cleanup_complete", "process_exit_confirmed", "work_removed"):
        assert oracle[key] is True
    assert oracle["physical_endpoint"] is False
    assert len(oracle["listeners"]) == 6
    assert all(listener.startswith("127.0.0.1:") for listener in oracle["listeners"])
    assert [row["tag"] for row in captured["cases"]] == list(range(200, 239))
    for row in captured["cases"]:
        tag = row["tag"]
        assert row["response_lines"][-1].startswith(f"[{tag}] {status(row)} ")
        if row["command"].startswith("DBSETXML "):
            assert row["request"].startswith(f"[{tag}] {row['command']} << END{tag}\r\n")
            assert row["request"].endswith(f"\r\nEND{tag}\r\n")
        else:
            assert row["request"] == f"[{tag}] {row['command']}\r\n"


def test_native_duplicate_identity_readback_and_save_reload():
    case = rows()
    for tag in (204, 217, 230):
        assert status(case[tag]) == 301
    for tag in (210, 211, 212, 213, 223, 224, 225, 226, 234, 235, 236, 237):
        assert status(case[tag]) == 200

    cross_kind = ET.fromstring(xml(case[205]))
    assert cross_kind.findtext("Application/OID") == cross_kind.findtext("Unit/OID")
    assert xml(case[206]).startswith("<Application>")
    assert xml(case[208]) == xml(case[207])  # OID lookup selects the Unit.
    assert case[209]["response_lines"] == ["[209] 342 !11111111-1111-4111-8111-111111111111/Address=20\r\n"]
    reloaded_cross_kind = ET.fromstring(xml(case[214]))
    assert reloaded_cross_kind.findtext("Application/OID") == reloaded_cross_kind.findtext("Unit/OID")
    assert "<PP Name=\"UnitAddress\" Value=\"20\"/>" in xml(case[216])

    duplicate = ET.fromstring(xml(case[218]))
    units = duplicate.findall("Unit")
    assert [unit.findtext("Address") for unit in units] == ["20", "21"]
    assert [unit.findtext("UnitName") for unit in units] == ["First room", "Second room"]
    assert [unit.find("PP").get("Value") for unit in units] == ["20", "21"]
    assert units[0].findtext("OID") == units[1].findtext("OID")
    assert xml(case[221]) == xml(case[220])  # Last Unit wins an ambiguous OID read.
    assert case[222]["response_lines"] == ["[222] 342 !11111111-1111-4111-8111-111111111111/Address=21\r\n"]
    after_reload = ET.fromstring(xml(case[227])).findall("Unit")
    assert [unit.findtext("UnitName") for unit in after_reload] == ["First room", "Second room"]
    assert [unit.find("PP").get("Value") for unit in after_reload] == ["20", "21"]
    assert xml(case[231]) == xml(case[228])
    assert ET.fromstring(xml(case[232])).findtext("UnitName") == "Changed room"
    final = ET.fromstring(xml(case[238])).findall("Unit")
    assert [unit.findtext("UnitName") for unit in final] == ["First room", "Changed room"]
    assert [unit.find("PP").get("Value") for unit in final] == ["20", "21"]
