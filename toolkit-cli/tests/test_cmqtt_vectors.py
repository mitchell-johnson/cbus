"""P1 JSON compatibility vectors for the observed dynamic-label cache.

Each row of rust/testdata/vectors/observed_dynamic_labels.jsonl pins the
existing decode_observed_labels contract (provenance, bounds,
partial/corrupt, language/variant/app-group identity) without inventing a
physical cache inventory query. Uses only the committed vector file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cbus_toolkit.cmqtt import decode_observed_labels

VECTORS = Path(__file__).resolve().parents[2] / "rust" / "testdata" / "vectors" / "observed_dynamic_labels.jsonl"


def load_vectors():
    text = VECTORS.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    assert rows, "vector file must not be empty"
    return rows


# Mirrors the Rust vector test roster: deletion/rename fails loudly on the
# missing/unexpected ID, while ADDING a row only extends this roster (both
# sides) without touching the floor logic.
EXPECTED_IDS = (
    "odl-0001-valid-standard-text",
    "odl-0002-valid-unicode-segmented",
    "odl-0003-valid-built-in-icon",
    "odl-0004-valid-dynamic-icon-8x7",
    "odl-0005-valid-language-selection",
    "odl-0006-incomplete-unicode-first-fragment",
    "odl-0007-unmatched-fragment-error",
    "odl-0008-invalid-utf8-error",
    "odl-0009-invalid-icon-dimensions-error",
    "odl-0010-complete-true-rejected",
    "odl-0011-device-readback-true-rejected",
    "odl-0012-wrong-format-rejected",
    "odl-0013-wrong-source-rejected",
    "odl-0014-capacity-exceeded-rejected",
    "odl-0015-bad-sequence-rejected",
    "odl-0016-mixed-app-interleaved-standard",
)


def test_vector_file_pins_observed_cache_contract():
    rows = load_vectors()
    # Floor, not an exact count: additive compatibility cases must not break
    # the contract pin. Per-row shape/expect pins below carry the weight.
    assert len(rows) >= len(EXPECTED_IDS), (
        f"expected at least {len(EXPECTED_IDS)} compatibility cases, got {len(rows)}"
    )
    seen_ids: set[str] = set()
    for item in rows:
        assert isinstance(item.get("id"), str) and item["id"]
        assert item["id"] not in seen_ids, f"duplicate vector id {item['id']}"
        seen_ids.add(item["id"])
        assert isinstance(item.get("document"), dict)
        assert ("expect" in item) ^ ("expect_error" in item), item["id"]
    assert seen_ids == set(EXPECTED_IDS), (
        "vector id roster changed: add the new id (both sides) or restore "
        f"the deleted/renamed row; missing={set(EXPECTED_IDS) - seen_ids}, "
        f"unexpected={seen_ids - set(EXPECTED_IDS)}"
    )


def test_vectors_match_decode_observed_labels():
    for item in load_vectors():
        doc = item["document"]
        if "expect_error" in item:
            with pytest.raises(ValueError, match=item["expect_error"]):
                decode_observed_labels(doc)
            continue
        expect = item["expect"]
        result = decode_observed_labels(doc)
        assert result["complete"] is False, item["id"]
        assert result["device_readback"] is False, item["id"]
        assert result["format"] == "cbus-observed-dynamic-label-cache-v1", item["id"]
        assert result["observation_count"] == len(doc["observations"]), item["id"]
        assert result["reset_on_reconnect"] == (doc.get("reset_on_reconnect") is True), item["id"]
        assert len(result["entries"]) == expect["entries"], item["id"]
        assert result["incomplete_transactions"] == expect.get("incomplete_transactions", 0), item["id"]
        assert len(result["errors"]) == expect.get("errors", 0), item["id"]
        if "kinds" in expect:
            assert sorted(e["kind"] for e in result["entries"]) == sorted(expect["kinds"]), item["id"]
        if "texts" in expect:
            got = sorted(
                (e["text"] for e in result["entries"] if "text" in e),
                key=lambda v: (v is None, "" if v is None else v),
            )
            want = sorted(
                expect["texts"],
                key=lambda v: (v is None, "" if v is None else v),
            )
            assert got == want, item["id"]
        if "error_substrings" in expect:
            for needle in expect["error_substrings"]:
                assert any(needle in e["error"] for e in result["errors"]), (item["id"], needle)
        if "language_selections" in expect:
            assert len(result["language_selections"]) == expect["language_selections"], item["id"]
        if "entry" in expect:
            assert len(result["entries"]) == 1, item["id"]
            for key, value in expect["entry"].items():
                assert result["entries"][0][key] == value, (item["id"], key)
        if "language" in expect:
            assert len(result["language_selections"]) == 1, item["id"]
            for key, value in expect["language"].items():
                assert result["language_selections"][0][key] == value, (item["id"], key)
