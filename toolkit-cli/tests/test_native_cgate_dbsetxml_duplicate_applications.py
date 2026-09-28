"""Source-bound owned native evidence for same-OID Application records."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "rust/testdata/fixtures/native_cgate_dbsetxml_duplicate_applications.json"
SCRIPT = ROOT / "toolkit-cli/research/cgate_dbsetxml_duplicate_applications.py"
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
    assert captured["schema"] == "native-cgate-dbsetxml-duplicate-applications-v1"
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
    assert [row["tag"] for row in captured["cases"]] == list(range(300, 339))
    for row in captured["cases"]:
        tag = row["tag"]
        assert row["response_lines"][-1].startswith(f"[{tag}] {status(row)} ")
        if row["command"].startswith("DBSETXML "):
            assert row["request"].startswith(f"[{tag}] {row['command']} << END{tag}\r\n")
            assert row["request"].endswith(f"\r\nEND{tag}\r\n")
        else:
            assert row["request"] == f"[{tag}] {row['command']}\r\n"


def test_native_application_identity_selection_and_mutations():
    case = rows()
    for tag in (304, 318, 334):
        assert status(case[tag]) == 301
    assert status(case[328]) == 200
    for tag in (310, 311, 312, 313, 323, 324, 325, 326):
        assert status(case[tag]) == 200

    shared = "33333333-3333-4333-8333-333333333333"
    for tag, names in ((305, ["First", "Second"]),
                       (314, ["First", "Second"]),
                       (319, ["First", "Changed"]),
                       (327, ["First", "Changed"]),
                       (329, ["First", "ByOID"]),
                       (335, ["First", "ViaXML"])):
        applications = ET.fromstring(xml(case[tag])).findall("Application")
        assert [app.findtext("Address") for app in applications] == ["56", "57"]
        assert [app.findtext("TagName") for app in applications] == names
        assert [app.findtext("OID") for app in applications] == [shared, shared]

    for network, before, after in ((305, 306, 307), (314, 315, 316),
                                   (319, 320, 321), (329, 330, 331), (335, 336, 337)):
        application_xml = [ET.tostring(node, encoding="unicode")
                           for node in ET.fromstring(xml(case[network])).findall("Application")]
        assert application_xml == [xml(case[before]), xml(case[after])]

    for oid_read, second in ((308, 307), (317, 316), (322, 321), (332, 331), (338, 337)):
        assert xml(case[oid_read]) == xml(case[second])
    assert case[309]["response_lines"] == [f"[309] 342 !{shared}/Address=57\r\n"]
    assert case[333]["response_lines"] == [f"[333] 342 !{shared}/TagName=ByOID\r\n"]
