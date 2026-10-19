"""Consume the associated numeric Level object-XML matrix (#73).

The matrix is an owned-model contract inferred from retained imported
original shapes. These checks pin its internal consistency and bind every
cited original case to its committed fixture bytes; they do not establish
renamed-associated, bare-selector or hardware acceptance.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VECTOR = ROOT / "rust/testdata/vectors/cgate_associated_numeric_level_object_matrix.jsonl"
FIXTURES = ROOT / "rust/testdata/fixtures"
OWNERS = {"plain-group": ("Group", 1, 7), "completed-group": ("Group", 1, 8),
          "plain-netvar": ("NetVar", 4, 7), "completed-netvar": ("NetVar", 4, 8)}
FORMS = {"qualified-numeric", "qualified-lexical", "bare-numeric"}


def rows():
    return [json.loads(line) for line in VECTOR.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_matrix_covers_each_owner_and_selector_form_once():
    matrix = rows()
    assert len(matrix) == 12
    for row in matrix:
        assert row["format"] == "cbus-associated-numeric-level-object-xml-v1"
        assert row["issue"] == 73 and row["observed_only"] is True
        assert row["owner"] in OWNERS and row["form"] in FORMS
        assert row["parent_kind"] == OWNERS[row["owner"]][0]
    pairs = [(row["owner"], row["form"]) for row in matrix]
    assert len(set(pairs)) == 12
    # (request, owner) pairs keep plain and completed owners distinct.
    requests = [(row["request"], row["owner"]) for row in matrix]
    assert len(set(requests)) == 12
    assert len({row["request"] for row in matrix}) == 12


def test_selector_spellings_match_owner_coordinates():
    for row in rows():
        _, group, level = OWNERS[row["owner"]]
        expected = {
            "qualified-numeric": f"DBGETXML //ASSOC/11/56/{group}/{level}",
            "qualified-lexical": f"DBGETXML //ASSOC/Renamed/56/{group}/{level}",
            "bare-numeric": f"DBGETXML 11/56/{group}/{level}",
        }[row["form"]]
        assert row["request"] == expected


def test_outcomes_split_by_parent_kind_and_bare_stays_refused():
    for row in rows():
        if row["form"] == "bare-numeric":
            # The bare selector contract remains blocked on #72.
            assert (row["status"], row["wire_status"], row["final"]) == (404, 404, "404 Project not selected")
            assert row["body"] is None
        elif row["form"] == "qualified-lexical" or row["parent_kind"] == "Group":
            assert (row["status"], row["wire_status"], row["body"]) == (200, 344, "<Level")
            assert row["final"] is None and row["same_as"] == "DBGETXML !<Level-OID>"
        else:
            assert (row["status"], row["wire_status"], row["body"]) == (500, 500, None)
            assert row["final"] == "500 Internal error."


def test_cited_original_cases_match_committed_fixture_bytes():
    cited = {}
    for row in rows():
        if row["form"] != "qualified-numeric":
            assert "native_cases" not in row
            continue
        assert "not natively measured" in row["evidence"]
        for fixture, tag in row["native_cases"]:
            cited.setdefault((fixture, tag), set()).add(row["parent_kind"])
    assert len(cited) == 14
    by_kind = {"Group": 0, "NetVar": 0}
    for (fixture, tag), kinds in cited.items():
        assert len(kinds) == 1
        kind, = kinds
        capture = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
        case, = [case for case in capture["cases"] if case["tag"] == tag]
        parts = case["command"].split()[1].removeprefix("//").split("/")
        assert case["command"].startswith("DBGETXML //") and len(parts) == 5
        assert all(part.isdigit() and str(int(part)) == part for part in parts[1:])
        lines = case["response_lines"]
        if kind == "Group":
            assert lines[-1] == f"[{tag}] 344 End XML snippet\r\n"
            assert any(line.startswith(f"[{tag}] 347-<Level ") for line in lines)
        else:
            assert lines == [f"[{tag}] 500 Internal error.\r\n"]
        by_kind[kind] += 1
    assert by_kind == {"Group": 10, "NetVar": 4}
