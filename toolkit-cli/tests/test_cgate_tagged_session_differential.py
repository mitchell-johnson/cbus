"""Strict tagged-wire differential and retained receipt integrity checks."""
from __future__ import annotations

from copy import deepcopy
import io
import json
from pathlib import Path

import pytest

from research import cgate_tagged_session_differential as differential


FIXTURES = Path(__file__).resolve().parents[1] / "research/fixtures"


def raw_cases():
    """Build role-consistent raw wire from the pinned normalized oracle."""
    native = differential.validate_native()
    replacements = {
        "<session:a>": "cmd3", "<session:b>": "cmd5",
        "<port:a>": "40123", "<port:b>": "40124",
        "<timestamp:console>": "20260928-120000",
        "<timestamp:a>": "20260928-120001",
        "<timestamp:b>": "20260928-120002",
    }
    cases = deepcopy(native["cases"])
    for case in cases:
        case["response_lines"] = [
            _replace(line, replacements) for line in case["response_lines"]
        ]
    return cases


def _replace(value, replacements):
    for token, raw in replacements.items():
        value = value.replace(token, raw)
    return value


def test_all_eleven_cases_preserve_full_numeric_tagged_wire():
    actual = raw_cases()
    expected = [case["response_lines"] for case in differential.validate_native()["cases"]]
    assert differential.normalize_wire(actual, {"a": 40123, "b": 40124}) == expected
    assert len(expected) == 11
    assert expected[2][0].startswith("[502] 300-sessionID=cmd1 origin=internal")
    assert expected[7] == [
        "[505] 408 Operation failed: tag name has already been set\r\n"
    ]


@pytest.mark.parametrize(
    ("case_index", "line_index", "old", "new", "error"),
    [
        (2, 0, "[502] ", "[999] ", "numeric prefix"),
        (2, 1, "[502] ", "", "numeric prefix"),
        (2, 2, "\r\n", "\n", "numeric prefix or CRLF"),
        (2, 0, "tag=Console", "tag=Other", "Console row"),
        (2, 0, "300-", "300 ", "continuation or terminal"),
        (2, 1, "40123", "40125", "owned peer port"),
        (5, 1, "20260928-120001", "20260928-120010", "timestamp changed"),
        (10, 0, "cmd5", "cmd3", "queried identity"),
        (7, 0, "408", "200", None),
    ],
)
def test_wire_mutations_are_rejected_or_compare_red(case_index, line_index, old, new, error):
    cases = raw_cases()
    line = cases[case_index]["response_lines"][line_index]
    assert old in line
    cases[case_index]["response_lines"][line_index] = line.replace(old, new)
    if error is None:
        normalized = differential.normalize_wire(cases, {"a": 40123, "b": 40124})
        assert normalized[case_index] != differential.validate_native()["cases"][case_index]["response_lines"]
    else:
        with pytest.raises(ValueError, match=error):
            differential.normalize_wire(cases, {"a": 40123, "b": 40124})


def test_extra_or_missing_console_row_is_rejected():
    cases = raw_cases()
    cases[2]["response_lines"].pop(0)
    with pytest.raises(ValueError, match="Console row"):
        differential.normalize_wire(cases, {"a": 40123, "b": 40124})


def test_live_reader_rejects_wrong_tag_or_lf_before_any_receipt_credit():
    with pytest.raises(ValueError, match="numeric tag"):
        differential.read_response(io.BytesIO(b"[999] 300 sessionID=cmd3\r\n"), "501")
    with pytest.raises(ValueError, match="CRLF"):
        differential.read_response(io.BytesIO(b"[501] 300 sessionID=cmd3\n"), "501")


def test_native_fixture_byte_change_fails_closed(tmp_path, monkeypatch):
    altered = tmp_path / "native.json"
    altered.write_bytes(differential.NATIVE.read_bytes() + b"\n")
    monkeypatch.setattr(differential, "NATIVE", altered)
    with pytest.raises(ValueError, match="capture hash changed"):
        differential.validate_native()


@pytest.mark.parametrize("product", ["cgate-mock", "cmqttd"])
def test_committed_receipt_binds_full_wire_oracle_and_current_source(product):
    path = FIXTURES / f"cgate-tagged-session-differential-{product}.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    differential.validate_passed_receipt(receipt)
    assert receipt["product"] == product
    assert (receipt["executed"], receipt["passed"], receipt["failed"], receipt["skipped"]) == (11, 11, 0, 0)
    assert receipt["cases"][2]["rust_normalized"][0].startswith(
        "[502] 300-sessionID=cmd1 origin=internal"
    )


def test_receipt_rejects_raw_tag_tamper_and_stale_transitive_rust_source(monkeypatch):
    path = FIXTURES / "cgate-tagged-session-differential-cmqttd.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    changed_wire = deepcopy(receipt)
    changed_wire["cases"][2]["rust_wire_reply"][0] = (
        changed_wire["cases"][2]["rust_wire_reply"][0].replace("[502]", "[999]")
    )
    with pytest.raises(ValueError, match="raw wire changed"):
        differential.validate_passed_receipt(changed_wire)
    source = differential.ROOT / "rust/cbus-mqtt/src/lib.rs"
    assert source.relative_to(differential.ROOT).as_posix() in receipt["source_fingerprint"]
    original_digest = differential.digest
    monkeypatch.setattr(
        differential, "digest", lambda path: "0" * 64 if path == source else original_digest(path)
    )
    with pytest.raises(ValueError, match="fingerprint is stale"):
        differential.validate_passed_receipt(receipt)
