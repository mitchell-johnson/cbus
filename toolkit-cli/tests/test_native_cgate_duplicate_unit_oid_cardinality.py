"""Owned build-2001 evidence for OID mutations with three and four Units."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "rust/testdata/fixtures/native_cgate_duplicate_unit_oid_cardinality.json"
VECTORS = ROOT / "rust/testdata/vectors/cgate_duplicate_unit_oid_cardinality.jsonl"
SCRIPT = ROOT / "toolkit-cli/research/cgate_duplicate_unit_oid_cardinality.py"
HELPER = ROOT / "toolkit-cli/research/cgate_dbsetxml_duplicate_oids.py"
HARNESS = ROOT / "toolkit-cli/research/local_cgate.py"


def status(row: dict) -> int:
    return int(row["response_lines"][-1].split()[1])


def unit(row: dict) -> ET.Element:
    tag = row["tag"]
    lines = row["response_lines"]
    assert lines[0] == f"[{tag}] 343-Begin XML snippet\r\n"
    assert lines[-1] == f"[{tag}] 344 End XML snippet\r\n"
    assert lines[2].startswith(f"[{tag}] 347-")
    return ET.fromstring(lines[2][len(f"[{tag}] 347-") :].rstrip("\r\n"))


def test_capture_source_and_sequential_owned_wire() -> None:
    captured = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert captured["schema"] == "native-cgate-duplicate-unit-oid-cardinality-v1"
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
    assert all(listener.startswith("127.0.0.1:") for listener in oracle["listeners"])
    rows = list(captured["setup"])
    for case in captured["cases"]:
        rows.extend((case["reset"], *case["before"], case["oid_before"], case["applied"],
                     *case["after"], case["oid_after"], *case["lifecycle"],
                     *case["reloaded"], case["oid_reloaded"]))
    assert len(rows) == 229
    assert [row["tag"] for row in rows] == list(range(400, 629))
    for row in rows:
        tag = row["tag"]
        assert row["response_lines"][-1].startswith(f"[{tag}] {status(row)} ")
        if row["command"].startswith("DBSETXML "):
            assert row["request"].startswith(f"[{tag}] {row['command']} << END{tag}\r\n")
            assert row["request"].endswith(f"\r\nEND{tag}\r\n")
        else:
            assert row["request"] == f"[{tag}] {row['command']}\r\n"


def test_three_and_four_unit_oid_mutations_select_final_submission() -> None:
    captured = json.loads(FIXTURE.read_text(encoding="utf-8"))
    vectors = [json.loads(line) for line in VECTORS.read_text(encoding="utf-8").splitlines()]
    assert len(captured["cases"]) == len(vectors) == 10
    for case, vector in zip(captured["cases"], vectors, strict=True):
        name = case["name"]
        assert vector["name"] == f"{'three' if len(case['submitted_addresses']) == 3 else 'four'}_{name}"
        addresses = case["submitted_addresses"]
        assert addresses == vector["submitted_addresses"]
        assert addresses in ([20, 21, 22], [23, 21, 20, 22])
        assert case["selected_address"] == vector["selected_address"] == addresses[-1] == 22
        assert status(case["reset"]) == 301
        reset = case["reset"]["request"]
        reset_document = ET.fromstring(reset.split("\r\n", 1)[1].rsplit("\r\nEND", 1)[0])
        assert [int(node.findtext("Address")) for node in reset_document.findall("Unit")] == addresses
        before = {}
        for row in case["before"]:
            if status(row) == 344:
                node = unit(row)
                before[int(node.findtext("Address"))] = node
        assert sorted(before) == sorted(addresses)
        assert status(case["oid_before"]) == 344
        assert unit(case["oid_before"]).findtext("Address") == "22"
        applied = case["applied"]
        assert applied["command"].startswith(vector["command"])
        assert [status(row) for row in case["lifecycle"]] == [200] * 4
        for row in case["after"]:
            if status(row) == 401:
                continue
            current = unit(row)
            address = int(current.findtext("Address"))
            if address in before and address != 22:
                assert current.findtext("UnitName") == before[address].findtext("UnitName")
        if name == "delete":
            assert status(applied) == 200
            assert status(case["oid_after"]) == vector["oid_after"] == 401
            assert status(case["oid_reloaded"]) == vector["oid_after_reload"] == 344
            assert unit(case["oid_reloaded"]).findtext("Address") == str(vector["reloaded_selected_address"])
            assert any(status(row) == 401 and row["command"].endswith("/22") for row in case["reloaded"])
            continue
        assert status(case["oid_after"]) == vector["oid_after"] == 344
        assert status(case["oid_reloaded"]) == vector["oid_after_reload"] == 344
        assert unit(case["oid_after"]).findtext("Address") == "22"
        assert unit(case["oid_reloaded"]).findtext("Address") == "22"
        if name in ("set_safe", "set_unsafe"):
            assert status(applied) == 200
            assert unit(case["oid_after"]).findtext("UnitName") == "ByOID"
        elif name == "set_xml":
            assert status(applied) == 301
            assert unit(case["oid_after"]).findtext("UnitName") == "Changed room"
        else:
            assert status(applied) == 301
            copied = next(unit(row) for row in case["after"] if row["command"].endswith("/30"))
            assert copied.findtext("TagName") == "Copied"
            assert copied.findtext("UnitName") == "Unit22 room"
            assert copied.find("PP").get("Value") == "22"
            assert copied.findtext("OID") != captured["shared_oid"]
