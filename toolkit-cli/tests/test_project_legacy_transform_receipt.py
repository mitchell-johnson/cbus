"""Guard the source and outcome boundary of the owned legacy transform capture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


from project_legacy_transform_receipt_source import (CLI_SHA256, historical_cli,
                                                     assert_current_project_carry_forward)


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "research/fixtures/project-legacy-transform-native-receipt.json"
RECEIPT_SHA256 = "8b9bed9a578c946e4a31f700446371e562d9d29312a35a4dedce13b78362d1c0"
SOURCES = {
    "portable_module_sha256": "src/cbus_toolkit/project_legacy_transform.py",
    "cli_module_sha256": "src/cbus_toolkit/project_legacy_transform_cli.py",
    "native_module_sha256": "src/cbus_toolkit/native.py",
    "portable_test_sha256": "tests/test_project_legacy_transform.py",
    "test_sha256": "tests/test_project_legacy_transform_native.py",
    "owned_service_harness_sha256": "research/local_cgate.py",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_native_legacy_transform_receipt_is_source_bound() -> None:
    assert digest(RECEIPT) == RECEIPT_SHA256
    receipt = json.loads(RECEIPT.read_bytes())
    assert receipt["format"] == "cbus-project-legacy-transform-native-v1"
    assert receipt["physical_networks_opened"] is False
    assert receipt["service"]["listener_ownership_verified"] is True
    assert receipt["service"]["cleanup_complete"] is True
    assert receipt["sources"]["cli_dispatch_sha256"] == CLI_SHA256
    historical_cli()
    assert_current_project_carry_forward()
    for field, path in SOURCES.items():
        assert receipt["sources"][field] == digest(ROOT / path)
    assert receipt["preview"]["backup_absent_before_test"] is True
    assert receipt["preview"]["creates_backup_without_changing_xml"] is True
    cases = receipt["cases"]
    assert [case["name"] for case in cases] == ["RPMAL", "FRENC", "FRDTD", "FRXML11"]
    for case in cases:
        assert case["backup_absent_before_load"] is True
        assert case["backup_absent_after_rejected_load"] is True
        assert case["backup_sha256"] == case["source_sha256"]
        assert case["load_before"].startswith("408 ")
        assert case["transform_response"] == "200 OK."
        assert case["load_after"] == "200 OK."
        assert case["readback_code"] == 344
        assert case["readback_db_version"] == "2.3"
        assert case["readback_project_address"] == case["name"]
    assert cases[0]["backup_created_by"] == "--test"
    assert all(case["backup_created_by"] == "transform" for case in cases[1:])


def test_project_source_carry_forward_detects_argument_and_forwarding_changes() -> None:
    from project_legacy_transform_receipt_source import project_source_contract

    source = historical_cli()
    expected = project_source_contract(source)
    for old, changed in ((b'"--xslt-file"', b'"--different-xslt-file"'),
                         (b'xslt_file=getattr(args, "xslt_file", None)',
                          b'xslt_file=getattr(args, "wrong_field", None)'),
                         (b'project_legacy_transform_run(args)',
                          b'project_legacy_transform_run(None)')):
        assert source.count(old) == 1
        assert project_source_contract(source.replace(old, changed)) != expected
