"""The scoped native differential is strict about source and wire framing."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import re

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "research/cgate_session_differential.py"
spec = importlib.util.spec_from_file_location("cgate_session_differential", SCRIPT)
differential = importlib.util.module_from_spec(spec)
spec.loader.exec_module(differential)


def test_native_capture_canonicalizes_only_three_internal_console_rows():
    native = differential.validate_native()
    canonical, excluded = differential.canonicalize(native["cases"][:9], native=True)
    assert len(canonical) == 9
    assert len(excluded) == 3
    assert canonical[2] == [
        "300-sessionID=<a> origin=/127.0.0.1:<port-a> from=<time-a>",
        "300 sessionID=<b> origin=/127.0.0.1:<port-b> from=<time-b>",
    ]
    assert canonical[5] == ["408 Operation failed: tag name has already been set"]


def test_unexpected_internal_row_is_not_filtered():
    cases = deepcopy(differential.validate_native()["cases"][:9])
    cases[2]["reply"][0] = cases[2]["reply"][0].replace("tag=Console", "tag=Other")
    with pytest.raises(ValueError, match="unexpected external row"):
        differential.canonicalize(cases, native=True)


def test_client_tag_echo_must_match_exactly():
    stream = io.BytesIO(b"[wrong] 300 sessionID=cmd3\n")
    with pytest.raises(ValueError, match="did not echo client-assigned tag"):
        differential.read_reply(stream, "requested")


def test_stale_native_capture_fails_before_probe(tmp_path, monkeypatch):
    altered = tmp_path / "native.json"
    altered.write_bytes(differential.NATIVE.read_bytes() + b"\n")
    monkeypatch.setattr(differential, "NATIVE", altered)
    with pytest.raises(ValueError, match="native capture hash changed"):
        differential.validate_native()


def test_passed_receipt_rejects_missing_or_stale_source_binding():
    receipt_path = SCRIPT.parent / "fixtures/cgate-session-differential-fixed.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    differential.validate_passed_receipt(receipt)
    stale = deepcopy(receipt)
    stale["source_fingerprint"]["rust/cbus-cgate/src/main.rs"] = "0" * 64
    with pytest.raises(ValueError, match="source fingerprint is stale"):
        differential.validate_passed_receipt(stale)
    partial = deepcopy(receipt)
    partial["skipped"] = 1
    with pytest.raises(ValueError, match="did not pass all nine"):
        differential.validate_passed_receipt(partial)


def test_cmqttd_receipt_is_separate_and_fully_executed():
    receipt_path = SCRIPT.parent / "fixtures/cgate-session-differential-cmqttd.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["product"] == "cmqttd"
    assert re.fullmatch(r"[0-9a-f]{64}", receipt["rust_artifact"]["sha256"])
    differential.validate_passed_receipt(receipt)


def test_broken_tagged_reply_is_a_red_executed_case_not_a_blocked_skip(tmp_path, monkeypatch):
    binary = tmp_path / "mock"
    binary.write_bytes(b"binary")
    binary.chmod(0o755)

    def broken_probe(_binary):
        raise differential.ProbeBehaviorError([], "session-query-a", ValueError("wrong tag"))

    monkeypatch.setattr(differential, "probe", broken_probe)
    receipt, code = differential.run(binary, "current-build")
    assert code == 1
    assert (receipt["result"], receipt["executed"], receipt["failed"], receipt["skipped"]) == (
        "failed", 1, 1, 8
    )


def test_pre_fix_receipt_is_red_without_skipped_cases():
    receipt_path = SCRIPT.parent / "fixtures/cgate-session-differential-pre-fix.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["rust_artifact"]["sha256"] == (
        "1dbc9c1c041da90993e407c68131c49748dd3435cacd8b6d9dcecfe78c1fb242"
    )
    assert (receipt["result"], receipt["executed"], receipt["passed"],
            receipt["failed"], receipt["skipped"]) == ("failed", 9, 0, 9, 0)
    with pytest.raises(ValueError, match="lacks exact current Rust artifact hash"):
        differential.validate_passed_receipt(receipt)
