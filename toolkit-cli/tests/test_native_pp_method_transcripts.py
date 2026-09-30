"""Native C-Gate 3.4 versus cmqttd PP LOAD/SET/SAVE_TO_SOURCE transcripts.

``research/native_pp_method_transcripts.py`` drives owned loopback native
C-Gate 3.4.0.2001 and cmqttd through the same PP session against a synthetic
method-memory fixture with one real catalogue unit type per programming-method
family.  The offline tests check the committed, sanitized transcript and the
reviewed difference catalogue.  The native-gated tests recapture native C-Gate
(same SAVE mutations, read set and final memory) and replay cmqttd (exact
per-phase requests and memory).  None of this is physical-device,
persistence or broad hardware evidence.
"""
import json
import os
from pathlib import Path

import pytest

from research import native_pp_method_transcripts as capture


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "rust/testdata/fixtures/native_cgate_pp_method_transcripts.json"
NATIVE = bool(os.environ.get("CBUS_LOCAL_CGATE_VENDOR") and os.environ.get("CBUS_CGATE_JAVA"))
SPECS = os.environ.get("CBUS_UNITSPEC_DIR")
CMQTTD = Path(os.environ.get("CBUS_CMQTTD_BIN", ROOT / "rust/target/debug/cmqttd"))
NATIVE_METHODS = {"direct", "paged", "ncc", "edlt", "giu", "sgiu", "dali", "gocbyt", "goc2"}
# Cases whose SAVE mutations differ by a reviewed, deliberate cmqttd contract.
REVIEWED = {
    "paged_wrd4f1_page1_and_lock": (
        ["3900", "111A", "A31A0003", "3901", "AA00010102030405060708"],
        ["3900", "111A", "A31A0003", "3901", "AA00000102030405060708"]),
    "edlt_keygl5_adjacent": (["A401420705"], ["A3014207", "A3014205"]),
    "ncc_reldn4a_no_edit": (["E3810004"], []),
    "ncc_reldn4a_same_value": (["3901", "A3000000", "E3810004"], []),
}


def load():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def phase(record, name):
    return capture.collapse([capture._parse(row) for row in record["requests"][name]])


def test_every_native_method_family_is_captured_on_both_endpoints():
    document = load()
    assert document["format"] == capture.FORMAT
    assert set(document["units"]) == NATIVE_METHODS
    assert set(document["no_native_specification"]) == {"goc"}
    assert set(document["cases"]) == set(capture.CASES)
    assert {case["native"]["method"] for case in document["cases"].values()} == NATIVE_METHODS
    assert document["oracle"]["cleanup_complete"] == ["True"]
    assert document["oracle"]["physical_endpoint"] is False
    for name, case in document["cases"].items():
        for side in ("native", "cmqttd"):
            statuses = [command["status"] for command in case[side]["commands"]]
            assert all(status < 400 for status in statuses), (name, side, statuses)
        assert document["comparison"][name]["save_status"] == {"native": 200, "cmqttd": 200}


def test_store_bytes_match_native_except_reviewed_contracts():
    document = load()
    for name, row in document["comparison"].items():
        mutations = row["save_mutations"]
        if name in REVIEWED:
            assert (mutations["native"], mutations["cmqttd"]) == REVIEWED[name], name
            continue
        assert mutations["identical"], (name, mutations)
        assert row["memory_after_save_identical"], name
    # Grouping differs for these, but the bytes each side leaves behind agree.
    assert document["comparison"]["paged_wrd4f1_page1_and_lock"]["memory_after_save_identical"]
    assert document["comparison"]["edlt_keygl5_adjacent"]["memory_after_save_identical"]


def test_native_ncc_save_always_commits_to_nvm():
    cases = load()["cases"]
    for name in ("ncc_reldn4a_edit", "ncc_reldn4a_no_edit", "ncc_reldn4a_same_value"):
        assert phase(cases[name]["native"], "save")[-1] == ("direct", "E3810004"), name
    assert phase(cases["ncc_reldn4a_edit"]["cmqttd"], "save")[-2:] == [
        ("direct", "1B010001"), ("direct", "E3810004")]
    for name in ("ncc_reldn4a_no_edit", "ncc_reldn4a_same_value"):
        assert not capture.mutations([capture._parse(row) for row in cases[name]["cmqttd"]["requests"]["save"]])


def test_native_behaviour_behind_deliberate_cmqttd_contracts():
    cases = load()["cases"]
    for name, case in cases.items():
        native, cmqttd = case["native"], case["cmqttd"]
        # Native LOAD is lazy and SAVE re-identifies nothing.
        assert native["requests"]["load"] == [], name
        assert not any(cal.startswith("21") for _, cal in phase(native, "save")), name
        assert phase(cmqttd, "load")[:2] == [("direct", "2101"), ("direct", "2102")], name
        assert phase(cmqttd, "save")[:2] == [("direct", "2101"), ("direct", "2102")], name
    key4 = cases["direct_key4_array"]
    assert ("direct", "1A0D0C") in phase(key4["native"], "get_before")
    assert ("direct", "1A0D04") in phase(key4["cmqttd"], "load")
    giu = cases["giu_pc_gim_array"]
    assert phase(giu["native"], "get_before")[0] == ("oem", "A3FC0300")
    assert phase(giu["native"], "get_before")[-1] == ("oem", "A3FC0301")
    assert not any(cal.startswith("A3FC") for _, cal in phase(giu["cmqttd"], "load"))
    dali = cases["dali_pc_dal2b"]
    assert dali["native"]["save_timing"]["max_gap_before_save_request_s"] >= 0.9
    assert dali["cmqttd"]["save_timing"]["max_gap_before_save_request_s"] >= 0.9


def test_goc2_acknowledgement_names_the_low_address_byte():
    document = load()
    assert document["fixture"]["goc2_store_ack"] == "32<low address byte><tag>"
    assert document["differences"]["goc2_ack_parameter"]["decision"] == "fixed"
    probe = document["goc2_parameter_ff_ack_probe"]
    assert probe["get_status"] == 408 and "Address set failed" in probe["get_reply"][-1]
    assert probe["save_requests"][-3:] == ["d:A6FF0001020501"] * 3
    goc2 = document["cases"]["goc2_dimar12_word"]
    assert phase(goc2["native"], "save") == phase(goc2["cmqttd"], "save")[4:5] == [
        ("direct", "A6FF0001020501")]


def test_difference_catalogue_is_reviewed():
    document = load()
    assert document["differences"] == capture.DIFFERENCES
    assert {row["decision"] for row in capture.DIFFERENCES.values()} <= {"fixed", "deliberate", "observation"}
    for row in capture.DIFFERENCES.values():
        assert set(row["methods"]) <= NATIVE_METHODS


def _comparable(record):
    return ({name: capture.collapse([capture._parse(row) for row in rows])
             for name, rows in record["requests"].items()},
            capture._memory(record))


def _native_invariants(record):
    """Timing-independent native facts: SAVE mutations, reads and memory.

    Native C-Gate occasionally delays or retransmits a synthetic-unit request,
    which can move a read into a later phase; which requests occur, the SAVE
    mutation order and the resulting memory do not change.
    """
    rows = [capture._parse(row) for rows in record["requests"].values() for row in rows]
    return {"save_mutations": capture.mutations([capture._parse(row) for row in record["requests"]["save"]]),
            "reads": sorted(set(capture.reads(rows))),
            "memory": capture._memory(record)}


@pytest.mark.skipif(not NATIVE, reason="owned native C-Gate is not configured")
def test_owned_native_recapture_matches_committed_transcript():
    committed = load()["cases"]
    native, oracle = capture.capture_native(os.environ["CBUS_LOCAL_CGATE_VENDOR"],
                                            os.environ["CBUS_CGATE_JAVA"], list(capture.CASES))
    assert oracle["cleanup_complete"] == ["True"]
    for name, record in native.items():
        assert all(command["status"] < 400 for command in record["commands"]), name
        assert _native_invariants(record) == _native_invariants(committed[name]["native"]), name


@pytest.mark.skipif(not NATIVE or not SPECS, reason="owned native catalogue and decoded unit specifications are not configured")
@pytest.mark.skipif(not CMQTTD.is_file() or not os.access(CMQTTD, os.X_OK), reason="cmqttd binary is not built")
def test_cmqttd_replay_matches_committed_transcript():
    committed = load()["cases"]
    replay = capture.capture_cmqttd(CMQTTD, SPECS, os.environ["CBUS_LOCAL_CGATE_VENDOR"], list(capture.CASES))
    for name, record in replay.items():
        assert record["requests"] == committed[name]["cmqttd"]["requests"], name
        assert _comparable(record)[1] == _comparable(committed[name]["cmqttd"])[1], name
