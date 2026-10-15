"""Issue #131/#73/#74: numeric Level vector contracts stay pinned.

Validates the checked-in JSONL wire vectors without a backend: ordinary
typed SAFE ownership (#131), associated qualified/bare Level XML after rename
(#73) and canonical numeric COPY plus plain LOAD preservation (#74).
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ORDINARY = ROOT / "rust/testdata/vectors/cgate_ordinary_numeric_level_value.jsonl"
LEVEL_MATRIX = ROOT / "rust/testdata/vectors/cgate_associated_numeric_level_matrix.jsonl"
OBJECT_MATRIX = ROOT / "rust/testdata/vectors/cgate_associated_numeric_level_object_matrix.jsonl"
COPY = ROOT / "rust/testdata/vectors/cgate_associated_numeric_copy.jsonl"


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_ordinary_numeric_level_value_vector_pins_typed_owner():
    rows = _rows(ORDINARY)
    assert len(rows) == 13
    assert all(row["format"] == "cbus-ordinary-numeric-level-value-v1" for row in rows)
    assert all(row["issue"] == 131 for row in rows)
    by_request = {row["request"]: row for row in rows}
    assert by_request["DBSETSAFE //T131/254/80/8/4/Value 99"]["status"] == 200
    assert by_request["DBSETSAFE //T131/254/80/8/4/Value oops"]["status"] == 400
    assert by_request["DBSET //T131/254/80/8/4/Value oops"]["status"] == 408
    assert by_request["DBSETSAFE //T131/254/80/8/9/Value 99"]["status"] == 401
    assert "no addressed owner" in by_request["DBSETSAFE //T131/254/80/8/9/Value 99"]["body"]
    assert by_request["DBSETSAFE //OTHER/254/80/8/4/Value 99"]["status"] == 401
    assert "project not selected" in by_request["DBSETSAFE //OTHER/254/80/8/4/Value 99"]["body"]
    assert by_request["DBSETSAFE //T131/254/81/8/4/Value 99"]["status"] == 200


def test_associated_level_matrix_pins_qualified_bare_contract():
    rows = _rows(LEVEL_MATRIX)
    assert len(rows) == 8
    qualified = [row for row in rows if row["form"] == "qualified"]
    bare = [row for row in rows if row["form"] == "bare"]
    assert len(qualified) == 4 and len(bare) == 4
    assert all(row["status"] == 404 and row["wire"] == 404 for row in bare)
    group = [row for row in qualified if "group" in row["owner"]]
    netvar = [row for row in qualified if "netvar" in row["owner"]]
    assert all(row["status"] == 200 and row["wire"] == 344 for row in group)
    assert all(row["status"] == 500 and row["wire"] == 500 for row in netvar)


def test_associated_object_matrix_pins_rename_controls():
    rows = _rows(OBJECT_MATRIX)
    assert len(rows) == 12
    assert all(row["format"] == "cbus-associated-numeric-level-object-matrix-v1" for row in rows)
    lexical = [row for row in rows if row["form"] == "qualified-lexical"]
    assert len(lexical) == 4
    assert all(row["status"] == 200 and row["wire"] == 344 for row in lexical)
    assert {(row["request"], row["owner"]) for row in lexical} == {
        ("DBGETXML //ASSOC/Renamed/56/1", "plain-group"),
        ("DBGETXML //ASSOC/Renamed/56/1", "completed-group"),
        ("DBGETXML //ASSOC/Renamed/56/4", "plain-netvar"),
        ("DBGETXML //ASSOC/Renamed/56/4", "completed-netvar"),
    }


def test_associated_numeric_copy_pins_canonical_destinations():
    rows = _rows(COPY)
    assert len(rows) == 8
    assert all(row["format"] == "cbus-associated-numeric-copy-v1" for row in rows)
    assert all(row["issue"] == 74 for row in rows)
    by_request = {row["request"]: row for row in rows}
    assert by_request["DBCOPYSAFE !<source-Level-OID> //LAB/11/56/1 12 NumericCopy"]["status"] == 301
    assert by_request["DBCOPY !<source-Level-OID> //LAB/11/56/1"]["status"] == 301
    assert by_request["DBCOPYSAFE //LAB/Renamed/56/1/9 //LAB/11/56/1 13 NumericLexicalCopy"]["status"] == 301
    assert by_request["DBCOPYSAFE !<source-Level-OID> //LAB/11/56/9 15 Ghost"]["status"] == 401
    assert by_request["DBCOPYSAFE !<raw-Level-OID> //LAB/11/56/1 16 RawCopy"]["status"] == 408
