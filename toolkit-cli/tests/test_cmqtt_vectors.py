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


def test_vector_file_pins_observed_cache_contract():
    rows = load_vectors()
    assert len(rows) >= 10, "expected ~10-15 compatibility cases"
    for item in rows:
        assert isinstance(item.get("id"), str) and item["id"]
        assert isinstance(item.get("document"), dict)
        assert ("expect" in item) ^ ("expect_error" in item), item["id"]


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
        assert len(result["entries"]) == expect["entries"], item["id"]
        assert result["incomplete_transactions"] == expect.get("incomplete_transactions", 0), item["id"]
        assert len(result["errors"]) == expect.get("errors", 0), item["id"]
        if "kinds" in expect:
            assert sorted(e["kind"] for e in result["entries"]) == sorted(expect["kinds"]), item["id"]
        if "texts" in expect:
            got = sorted(e["text"] for e in result["entries"] if "text" in e and e["text"] is not None)
            assert got == sorted(expect["texts"]), item["id"]
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
