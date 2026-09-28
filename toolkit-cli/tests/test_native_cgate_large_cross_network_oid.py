"""Source-bound original C-Gate evidence for large and cross-Network OID collisions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "rust/testdata/fixtures/native_cgate_large_cross_network_oid.json"
LARGE_VECTORS = ROOT / "rust/testdata/vectors/cgate_large_unit_oid.jsonl"
CROSS_VECTORS = ROOT / "rust/testdata/vectors/cgate_cross_network_oid.jsonl"
SCRIPT = ROOT / "toolkit-cli/research/cgate_large_cross_network_oid.py"
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
    return ET.fromstring("".join(line.split("347-", 1)[1] for line in lines if "347-" in line))


def all_rows(data: dict) -> list[dict]:
    rows = list(data["setup"])
    for case in data["cardinality"]:
        rows += [case["reset"], *case["before"], case["oid_before"], case["applied"],
                 *case["after"], case["oid_after"], *case["lifecycle"],
                 *case["reloaded"], case["oid_reloaded"]]
    rows += [data["created_second_network"], data["second_network_baseline"]]
    for case in data["cross_network"]:
        rows += [*case["cleared"], *case["inserts"], *case["before"], case["oid_before"]]
        if case["accepted"]:
            rows += [case["applied"], *case["after"], case["oid_after"],
                     *case["lifecycle"], *case["reloaded"], case["oid_reloaded"]]
    return rows


def test_capture_is_source_bound_owned_and_sequential() -> None:
    data = json.loads(FIXTURE.read_text())
    assert data["schema"] == "native-cgate-large-cross-network-oid-v1"
    for source, key in ((SCRIPT, "capture_script_sha256"),
                        (HELPER, "exchange_helper_sha256"),
                        (HARNESS, "service_harness_sha256")):
        assert data[key] == hashlib.sha256(source.read_bytes()).hexdigest()
    oracle = data["oracle"]
    assert oracle["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert oracle["java_sha256"] == "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
    assert oracle["version"] == "3.4.0 build 2001"
    assert oracle["physical_endpoint"] is False
    for key in ("owned_loopback_listeners", "cleanup_complete", "process_exit_confirmed", "work_removed"):
        assert oracle[key] is True
    assert len(oracle["listeners"]) == 6
    assert all(item.startswith("127.0.0.1:") for item in oracle["listeners"])
    rows = all_rows(data)
    assert len(rows) == data["request_count"] == 1551
    assert [row["tag"] for row in rows] == list(range(1000, 2551))
    for row in rows:
        tag = row["tag"]
        assert row["response_lines"][-1].startswith(f"[{tag}] {status(row)} ")
        if row["command"].startswith("DBSETXML "):
            assert row["request"].startswith(f"[{tag}] {row['command']} << END{tag}\r\n")
            assert row["request"].endswith(f"\r\nEND{tag}\r\n")
        else:
            assert row["request"] == f"[{tag}] {row['command']}\r\n"


def test_seven_and_eight_units_select_final_submitted_unit() -> None:
    data = json.loads(FIXTURE.read_text())
    vectors = [json.loads(line) for line in LARGE_VECTORS.read_text().splitlines()]
    assert len(data["cardinality"]) == len(vectors) == 10
    for case, vector in zip(data["cardinality"], vectors):
        addresses = case["submitted_addresses"]
        assert len(addresses) in (7, 8)
        assert addresses[-1] == case["selected_address"] == vector["selected_address"] == 22
        assert addresses == vector["submitted_addresses"]
        assert status(case["reset"]) == 301
        document = case["reset"]["request"].split("\r\n", 1)[1].rsplit("\r\nEND", 1)[0]
        assert [int(node.findtext("Address")) for node in ET.fromstring(document).findall("Unit")] == addresses
        assert xml(case["oid_before"]).findtext("Address") == "22"
        assert case["applied"]["command"].startswith(vector["command"])
        assert case["applied"]["response_lines"][-1].split("] ", 1)[1].strip() == vector["receipt"]
        assert [status(row) for row in case["lifecycle"]] == [200] * 4
        before = {int(xml(row).findtext("Address")): xml(row).findtext("UnitName")
                  for row in case["before"] if status(row) == 344}
        assert sorted(before) == sorted(addresses)
        for phase in (case["after"], case["reloaded"]):
            for row in phase:
                if status(row) != 344:
                    continue
                node = xml(row)
                address = int(node.findtext("Address"))
                if address in before and address != 22:
                    assert node.findtext("UnitName") == before[address]
        if case["name"] == "delete":
            assert status(case["oid_after"]) == 401
            assert xml(case["oid_reloaded"]).findtext("Address") == "23"
        else:
            assert xml(case["oid_after"]).findtext("Address") == "22"
            assert xml(case["oid_reloaded"]).findtext("Address") == "22"


def test_cross_network_precedence_and_five_verbs() -> None:
    data = json.loads(FIXTURE.read_text())
    vectors = [json.loads(line) for line in CROSS_VECTORS.read_text().splitlines()]
    assert len(data["cross_network"]) == len(vectors) == 40
    for case, vector in zip(data["cross_network"], vectors):
        assert case["accepted"] is True
        assert [status(row) for row in case["inserts"]] == [301, 301]
        assert case["network_order"] == vector["network_order"]
        assert case["selected_network"] == vector["selected_network"] == 253
        assert case["selected_kind"] == vector["selected_kind"]
        selected = xml(case["oid_before"])
        assert selected.tag == vector["selected_kind"]
        assert int(selected.findtext("Address")) == vector["selected_address"]
        assert case["applied"]["command"].startswith(vector["command"])
        assert case["applied"]["response_lines"][-1].split("] ", 1)[1].strip() == vector["receipt"]
        assert [status(row) for row in case["lifecycle"]] == [200] * 4
        if case["name"] == "delete":
            assert status(case["oid_after"]) == 401
            survivor = xml(case["oid_reloaded"])
            assert survivor.tag == vector["fallback_kind"]
            assert int(survivor.findtext("Address")) == vector["fallback_address"]
        else:
            assert xml(case["oid_after"]).tag == vector["selected_kind"]
            assert xml(case["oid_reloaded"]).tag == vector["selected_kind"]
        if case["name"] == "copy_safe":
            copied = [(path, xml(row)) for path, row in zip(case["paths"], case["after"])
                      if status(row) == 344 and path.endswith("/30")]
            assert len(copied) == 1
            path, node = copied[0]
            assert path == f"//XULARGE/253/{'p/' if vector['copied_kind'] == 'Unit' else ''}30"
            assert node.tag == vector["copied_kind"]
            assert node.findtext("TagName") == "Copied"
            assert node.findtext("OID") != data["shared_oid"]
