"""Source-bound original C-Gate evidence for cross-kind OID mutations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "rust/testdata/fixtures/native_cgate_cross_kind_oid_mutations.json"
VECTORS = ROOT / "rust/testdata/vectors/cgate_cross_kind_oid_mutations.jsonl"
SCRIPT = ROOT / "toolkit-cli/research/cgate_cross_kind_oid_mutations.py"
HELPER = ROOT / "toolkit-cli/research/cgate_dbsetxml_duplicate_oids.py"
HARNESS = ROOT / "toolkit-cli/research/local_cgate.py"


def status(row: dict) -> int:
    return int(row["response_lines"][-1].split()[1])


def xml(row: dict) -> ET.Element:
    assert status(row) == 344
    tag = row["tag"]
    lines = row["response_lines"]
    assert lines[0] == f"[{tag}] 343-Begin XML snippet\r\n"
    assert lines[-1] == f"[{tag}] 344 End XML snippet\r\n"
    return ET.fromstring(lines[2][len(f"[{tag}] 347-") :].rstrip("\r\n"))


def test_capture_source_and_owned_sequential_wire() -> None:
    captured = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert captured["schema"] == "native-cgate-cross-kind-oid-mutations-v1"
    for source, key in (
        (SCRIPT, "capture_script_sha256"),
        (HELPER, "exchange_helper_sha256"),
        (HARNESS, "service_harness_sha256"),
    ):
        assert captured[key] == hashlib.sha256(source.read_bytes()).hexdigest()
    oracle = captured["oracle"]
    assert oracle["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert oracle["java_sha256"] == "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
    assert oracle["version"] == "3.4.0 build 2001"
    assert oracle["physical_endpoint"] is False
    for key in ("owned_loopback_listeners", "cleanup_complete", "process_exit_confirmed", "work_removed"):
        assert oracle[key] is True
    assert len(oracle["listeners"]) == 6
    assert all(item.startswith("127.0.0.1:") for item in oracle["listeners"])
    rows = list(captured["setup"])
    for case in captured["cases"]:
        rows.extend((case["reset"], *case["before"], case["oid_before"], case["applied"],
                     *case["after"], case["oid_after"], *case["lifecycle"],
                     *case["reloaded"], case["oid_reloaded"]))
    assert len(rows) == 184
    assert [row["tag"] for row in rows] == list(range(700, 884))
    for row in rows:
        tag = row["tag"]
        assert row["response_lines"][-1].startswith(f"[{tag}] {status(row)} ")
        if row["command"].startswith("DBSETXML "):
            assert row["request"].startswith(f"[{tag}] {row['command']} << END{tag}\r\n")
            assert row["request"].endswith(f"\r\nEND{tag}\r\n")
        else:
            assert row["request"] == f"[{tag}] {row['command']}\r\n"


def test_cross_kind_oid_mutations_select_unit_and_preserve_application() -> None:
    captured = json.loads(FIXTURE.read_text(encoding="utf-8"))
    vectors = [json.loads(line) for line in VECTORS.read_text(encoding="utf-8").splitlines()]
    assert len(captured["cases"]) == len(vectors) == 10
    for case, vector in zip(captured["cases"], vectors, strict=True):
        name = f"{case['submission_order']}_{case['name']}"
        assert vector["name"] == name
        assert status(case["reset"]) == 301
        submitted = case["reset"]["request"].split("\r\n", 1)[1].rsplit("\r\nEND", 1)[0]
        root = ET.fromstring(submitted)
        kinds = [child.tag for child in root if child.tag in ("Application", "Unit")]
        assert kinds == (["Application", "Unit"] if case["submission_order"] == "application_then_unit"
                         else ["Unit", "Application"])
        assert xml(case["before"][0]).tag == "Application"
        assert xml(case["before"][1]).tag == "Unit"
        assert status(case["before"][2]) == 401
        assert xml(case["oid_before"]).tag == vector["oid_before"]
        assert case["applied"]["command"].startswith(vector["command"])
        assert [status(row) for row in case["lifecycle"]] == [200] * 4
        assert xml(case["after"][0]).findtext("TagName") == "Lighting"
        assert xml(case["reloaded"][0]).findtext("TagName") == "Lighting"
        assert status(case["oid_after"]) == (401 if case["name"] == "delete" else 344)
        assert xml(case["oid_reloaded"]).tag == vector["oid_after_reload"]
        if case["name"] == "delete":
            assert status(case["applied"]) == 200
            assert status(case["after"][1]) == status(case["reloaded"][1]) == 401
        elif case["name"] == "copy_safe":
            assert status(case["applied"]) == 301
            copied = xml(case["after"][2])
            assert copied.findtext("TagName") == "Copied"
            assert copied.findtext("UnitName") == "First room"
            assert copied.find("PP").get("Value") == "20"
            assert copied.findtext("OID") != captured["shared_oid"]
        else:
            assert status(case["applied"]) == (301 if case["name"] == "set_xml" else 200)
            expected = "Changed room" if case["name"] == "set_xml" else "ByOID"
            assert xml(case["after"][1]).findtext("UnitName") == expected
            assert xml(case["reloaded"][1]).findtext("UnitName") == expected
