"""Source-bound original C-Gate evidence for nested same-OID Levels."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "rust/testdata/fixtures/native_cgate_dbsetxml_nested_levels.json"
VECTOR = ROOT / "rust/testdata/vectors/cgate_dbsetxml_nested_levels.jsonl"
SCRIPT = ROOT / "toolkit-cli/research/cgate_dbsetxml_nested_levels.py"
EXCHANGE = ROOT / "toolkit-cli/research/cgate_dbsetxml_duplicate_applications.py"
HARNESS = ROOT / "toolkit-cli/research/local_cgate.py"
SHARED = "33333333-3333-4333-8333-333333333333"


def evidence():
    return json.loads(CAPTURE.read_text(encoding="utf-8"))


def xml(row):
    tag = row["tag"]
    lines = row["response_lines"]
    assert lines[0] == f"[{tag}] 343-Begin XML snippet\r\n"
    assert lines[1] == f'[{tag}] 347-<?xml version="1.0" encoding="utf-8"?>\n'
    assert lines[-1] == f"[{tag}] 344 End XML snippet\r\n"
    assert len(lines) == 4
    return lines[2][len(f"[{tag}] 347-"):-2]


def test_owned_capture_and_exact_transcript():
    captured = evidence()
    vector = json.loads(VECTOR.read_text(encoding="utf-8"))
    assert captured["schema"] == "native-cgate-dbsetxml-nested-levels-v1"
    assert captured["shared_oid"] == SHARED
    assert len(captured["cases"]) == 62
    assert [row["tag"] for row in captured["cases"]] == list(range(800, 862))
    assert [(shape["project"], shape["kind"], shape["submit_tag"])
            for shape in captured["shapes"]] == [("XLGR", "Group", 804),
                                                  ("XLNV", "NetVar", 835)]
    for source, key in ((SCRIPT, "capture_script_sha256"),
                        (EXCHANGE, "exchange_helper_sha256"),
                        (HARNESS, "service_harness_sha256")):
        assert captured[key] == hashlib.sha256(source.read_bytes()).hexdigest()
    oracle = captured["oracle"]
    assert oracle["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert oracle["java_sha256"] == "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
    assert oracle["version"] == "3.4.0 build 2001"
    assert all(oracle[key] is True for key in
               ("owned_loopback_listeners", "cleanup_complete", "process_exit_confirmed", "work_removed"))
    assert oracle["physical_endpoint"] is False
    assert len(oracle["listeners"]) == 6
    assert all(listener.startswith("127.0.0.1:") for listener in oracle["listeners"])
    assert vector["native_fixture"] == CAPTURE.name
    assert vector["basis"] == "native-owned-loopback"
    assert vector["set_tags"] == [row["tag"] for row in captured["cases"]
                                  if row["command"].startswith("DBSETXML ")]
    assert vector["read_tags"] == [row["tag"] for row in captured["cases"]
                                   if row["command"].startswith("DBGETXML ")]
    assert vector["internal_error_tags"] == [839, 843, 855, 859]
    for row in captured["cases"]:
        if row["tag"] in vector["set_tags"]:
            assert row["response_lines"] == [
                f"[{row['tag']}] 301 OID={next(shape['network_oid'] for shape in captured['shapes'] if shape['submit_tag'] == row['tag'])}\r\n"
            ]
    for row in captured["cases"]:
        tag = row["tag"]
        assert row["response_lines"][-1].startswith(f"[{tag}] ")
        if row["command"].startswith("DBSETXML "):
            assert row["request"].startswith(f"[{tag}] {row['command']} << END{tag}\r\n")
            assert row["request"].endswith(f"\r\nEND{tag}\r\n")
        else:
            assert row["request"] == f"[{tag}] {row['command']}\r\n"
        if tag in vector["internal_error_tags"]:
            assert row["response_lines"] == [f"[{tag}] 500 Internal error.\r\n"]
        elif row["command"].startswith("DBGETXML "):
            ET.fromstring(xml(row))


def test_level_children_and_load_boundary():
    rows = {row["tag"]: row for row in evidence()["cases"]}
    for first, kind in ((805, "Group"), (836, "NetVar")):
        before = ET.fromstring(xml(rows[first]))
        after_save = ET.fromstring(xml(rows[first + 11]))
        after_load = ET.fromstring(xml(rows[first + 14]))
        assert [int(app.findtext("Address")) for app in before.findall("Application")] == [56, 57]
        assert [app.findtext("OID") for app in before.findall("Application")] == [SHARED, SHARED]
        for root, count in ((before, 0), (after_save, 0), (after_load, 1)):
            for app, address in zip(root.findall("Application"), (56, 57)):
                child = app.find(kind)
                assert child.findtext("OID") == f"44444444-4444-4444-8444-0000000000{address}"
                level = child.find("Level")
                assert level.attrib == {"Value": str(address)}
                assert level.findtext("OID") == f"55555555-5555-4555-8555-0000000000{address}"
                assert level.findtext("TagName") == f"Level{address}"
                assert len(level.findall("TagsDLT")) == count
        assert xml(rows[first]) == xml(rows[first + 11])
        assert xml(rows[first + 14]) == xml(rows[first + 16])

    for tag in (808, 812, 824, 828):
        assert ET.fromstring(xml(rows[tag])).tag == "Level"
    for tag in (839, 843, 855, 859):
        assert rows[tag]["response_lines"] == [f"[{tag}] 500 Internal error.\r\n"]
    for tag in (809, 813, 825, 829, 840, 844, 856, 860):
        assert ET.fromstring(xml(rows[tag])).tag == "Level"
    for tag in (814, 830, 845, 861):
        selected = ET.fromstring(xml(rows[tag]))
        assert selected.findtext("Address") == "57"
        assert selected.find(f"{'Group' if tag < 831 else 'NetVar'}/Level") is not None
