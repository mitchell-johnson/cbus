"""Owned original C-Gate evidence for repeated-OID leaf Applications."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "rust/testdata/fixtures/native_cgate_dbsetxml_application_shapes.json"
VECTOR = ROOT / "rust/testdata/vectors/cgate_dbsetxml_application_shapes.jsonl"
SCRIPT = ROOT / "toolkit-cli/research/cgate_dbsetxml_application_shapes.py"
EXCHANGE = ROOT / "toolkit-cli/research/cgate_dbsetxml_duplicate_applications.py"
HARNESS = ROOT / "toolkit-cli/research/local_cgate.py"
SHARED = "33333333-3333-4333-8333-333333333333"


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
    assert lines[2].startswith(f"[{tag}] 347-") and lines[2].endswith("\r\n")
    return lines[2][len(f"[{tag}] 347-"):-2]


def test_repeated_application_capture_is_source_bound_and_owned():
    evidence = capture()
    assert evidence["schema"] == "native-cgate-dbsetxml-application-shapes-v1"
    assert evidence["capture_script_sha256"] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert evidence["exchange_helper_sha256"] == hashlib.sha256(EXCHANGE.read_bytes()).hexdigest()
    assert evidence["service_harness_sha256"] == hashlib.sha256(HARNESS.read_bytes()).hexdigest()
    oracle = evidence["oracle"]
    assert oracle["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert oracle["java_sha256"] == "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
    assert oracle["version"] == "3.4.0 build 2001"
    for key in ("owned_loopback_listeners", "cleanup_complete", "process_exit_confirmed", "work_removed"):
        assert oracle[key] is True
    assert oracle["physical_endpoint"] is False
    assert len(oracle["listeners"]) == 6
    assert all(listener.startswith("127.0.0.1:") for listener in oracle["listeners"])
    assert len(evidence["cases"]) == 114
    assert [row["tag"] for row in evidence["cases"]] == list(range(400, 514))
    vector = json.loads(VECTOR.read_text(encoding="utf-8"))
    assert vector["native_fixture"] == CAPTURE.name
    assert vector["basis"] == "native-owned-loopback"
    assert vector["set_tags"] == [row["tag"] for row in evidence["cases"]
                                  if row["command"].startswith(("DBSETXML ", "DBSET "))]
    assert vector["read_tags"] == [row["tag"] for row in evidence["cases"]
                                   if row["command"].startswith(("DBGETXML ", "DBGET "))]
    for row in evidence["cases"]:
        tag = row["tag"]
        assert row["response_lines"][-1].startswith(f"[{tag}] {status(row)} ")
        if row["command"].startswith("DBSETXML "):
            assert row["request"].startswith(f"[{tag}] {row['command']} << END{tag}\r\n")
            assert row["request"].endswith(f"\r\nEND{tag}\r\n")
        else:
            assert row["request"] == f"[{tag}] {row['command']}\r\n"


def test_native_reversed_triple_and_quad_order_selection_and_durability():
    evidence = capture()
    case = rows()
    shapes = evidence["shapes"]
    assert [(s["project"], s["submitted"], s["submit_tag"]) for s in shapes] == [
        ("XREVA", [57, 56], 404), ("XTRIA", [56, 57, 58], 440),
        ("XQUAD", [59, 57, 56, 58], 478),
    ]
    assert evidence["shared_oid"] == SHARED
    original_names = {56: "First", 57: "Second", 58: "Third", 59: "Fourth"}

    for shape in shapes:
        start = shape["submit_tag"]
        addresses = shape["submitted"]
        count = len(addresses)
        selected = addresses[-1]
        first = addresses[0]
        assert status(case[start]) == 301
        assert status(case[start + 2 * count + 11]) == 301  # direct path
        assert status(case[start + 2 * count + 14]) == 200  # OID TagName
        assert status(case[start + 2 * count + 17]) == 301  # OID XML
        for tag in (*range(start + count + 4, start + count + 8),
                    *range(start + 2 * count + 22, start + 2 * count + 26)):
            assert status(case[tag]) == 200

        def applications(tag):
            nodes = ET.fromstring(xml(case[tag])).findall("Application")
            assert [int(node.findtext("Address")) for node in nodes] == addresses
            assert [node.findtext("OID") for node in nodes] == [SHARED] * count
            return [node.findtext("TagName") for node in nodes]

        initial = [original_names[address] for address in addresses]
        direct_changed = initial.copy()
        direct_changed[0] = f"Changed{direct_changed[0]}"
        oid_field_changed = direct_changed.copy()
        oid_field_changed[-1] = "ByOID"
        oid_xml_changed = oid_field_changed.copy()
        oid_xml_changed[-1] = "ViaXML"
        assert applications(start + 1) == initial
        assert applications(start + count + 8) == initial
        assert xml(case[start + 1]) == xml(case[start + count + 8])
        assert applications(start + 2 * count + 12) == direct_changed
        assert applications(start + 2 * count + 15) == oid_field_changed
        assert applications(start + 2 * count + 18) == oid_xml_changed
        assert applications(start + 2 * count + 26) == oid_xml_changed
        assert xml(case[start + 2 * count + 18]) == xml(case[start + 2 * count + 26])

        assert xml(case[start + count + 2]) == xml(case[start + 2 + addresses.index(selected)])
        assert xml(case[start + 2 * count + 9]) == xml(case[start + count + 9 + addresses.index(selected)])
        for tag, name in (
            (start + count + 2, initial[-1]),
            (start + 2 * count + 9, initial[-1]),
            (start + 2 * count + 13, direct_changed[-1]),
            (start + 2 * count + 16, "ByOID"),
            (start + 2 * count + 19, "ViaXML"),
            (start + 2 * count + 27, "ViaXML"),
        ):
            selected_object = ET.fromstring(xml(case[tag]))
            assert selected_object.findtext("Address") == str(selected)
            assert selected_object.findtext("TagName") == name
        for tag in (start + count + 3, start + 2 * count + 10):
            assert case[tag]["response_lines"] == [f"[{tag}] 342 !{SHARED}/Address={selected}\r\n"]
        assert f"<Address>{first}</Address>" in xml(case[start + 2 * count + 20])
        assert f"<Address>{selected}</Address>" in xml(case[start + 2 * count + 21])
