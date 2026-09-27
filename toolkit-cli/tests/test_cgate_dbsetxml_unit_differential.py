"""Source-bound exact-wire receipts for the scoped original Unit XML mapper."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from research.cgate_dbsetxml_unit_differential import validate_receipt


ROOT = Path(__file__).resolve().parents[2]
RECEIPTS = ROOT / "toolkit-cli/research/fixtures"


@pytest.mark.parametrize("product", ("mock", "cmqttd"))
def test_committed_original_vs_rust_mapper_receipt(product):
    receipt = json.loads(
        (RECEIPTS / f"cgate-dbsetxml-unit-differential-{product}.json").read_text()
    )
    validate_receipt(receipt)
    assert len(receipt["cases"]) == 12
    assert len(receipt["combined_network_checks"]) == 2
    assert receipt["combined_network_passed"] == 2
    assert receipt["wire_equal"] == 5  # five 301 rows; XML envelope differs
    assert all(not case["unsolicited_events"] for case in receipt["cases"])
    assert all(not case["unsolicited_events"] for case in receipt["combined_network_checks"])


def test_mapper_receipt_rejects_mutated_original_and_rust_wire():
    receipt = json.loads(
        (RECEIPTS / "cgate-dbsetxml-unit-differential-mock.json").read_text()
    )
    changed = copy.deepcopy(receipt)
    changed["cases"][2]["original_wire"][0] = "[810] 200 OK\r\n"
    with pytest.raises(ValueError, match="original wire changed"):
        validate_receipt(changed)
    changed = copy.deepcopy(receipt)
    changed["cases"][1]["rust_wire"][0] = changed["cases"][1]["rust_wire"][0].replace(
        "<Unit>", "<Unit altered=\"1\">"
    )
    with pytest.raises(ValueError, match="XML reply changed"):
        validate_receipt(changed)
    changed = copy.deepcopy(receipt)
    changed["cases"][0]["mapped_request"] = changed["cases"][0]["mapped_request"].replace(
        "127.0.0.1:1", "127.0.0.1:2"
    )
    with pytest.raises(ValueError, match="OID substitution changed"):
        validate_receipt(changed)
    changed = copy.deepcopy(receipt)
    changed["combined_network_checks"][0]["rust_wire"][0] = (
        changed["combined_network_checks"][0]["rust_wire"][0].replace(
            "<Application>", "<Application changed=\"1\">"
        )
    )
    with pytest.raises(ValueError, match="combined Network mapper changed"):
        validate_receipt(changed)
