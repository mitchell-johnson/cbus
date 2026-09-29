"""Pin original build-2001 earlier-version conversion and rejection evidence."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "research/fixtures/project-legacy-transform-versions-native-receipt.json"
RECEIPT_SHA256 = "8b6c6cbdbd1cf6269407ccf6e5e08b7d6118eff1bc257d761627526317bfa718"
SOURCE_FILES = {
    "native_test_sha256": "tests/test_project_legacy_transform_versions_native.py",
    "portable_module_sha256": "src/cbus_toolkit/project_legacy_transform.py",
    "native_module_sha256": "src/cbus_toolkit/native.py",
    "cli_dispatch_sha256": "src/cbus_toolkit/cli.py",
    "portable_test_sha256": "tests/test_project_legacy_transform.py",
    "owned_service_harness_sha256": "research/local_cgate.py",
}
STYLESHEET_HASHES = {
    "v2tov21.xslt": "8346eab4259b957d53fc2b5c14ee1e058196124eabe4a7e3fb45b145f74735a8",
    "v21tov22.xslt": "e2090621171b5febf4903eaa964dd7a855b3d3cea827678da3758376dceab875",
    "v22tov23.xslt": "5674534824826a2db5e3b762c207ce0e566298e54703f628d16f9b3d2d47dab2",
    "projectversions.xml": "f9b2e0a83753321e311dee1ac7e1817b28dd984a792a2fd2923efa1cac85aaf8",
}


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_earlier_versions_receipt_is_source_bound() -> None:
    assert digest(RECEIPT) == RECEIPT_SHA256
    receipt = json.loads(RECEIPT.read_bytes())
    assert receipt["format"] == "cbus-project-legacy-transform-versions-native-v1"
    assert receipt["physical_networks_opened"] is False
    assert receipt["service"]["listener_ownership_verified"] is True
    assert receipt["service"]["cleanup_complete"] is True
    assert receipt["sources"]["transform_sha256"] == STYLESHEET_HASHES
    for field, path in SOURCE_FILES.items():
        assert receipt["sources"][field] == digest(ROOT / path)
    cases = receipt["cases"]
    assert len(cases) == 8
    assert {case["source_version"] for case in cases} == {"1", "2", "2.1", "2.4"}
    accepted = [case for case in cases if case["source_version"] in ("2", "2.1")]
    rejected = [case for case in cases if case["source_version"] in ("1", "2.4")]
    assert len(accepted) == 6 and len(rejected) == 2
    for case in accepted:
        assert case["source_sha256"] == case["backup_sha256"]
        assert case["load_before"].startswith("408 ")
        assert case["transform"] == "200 OK."
        assert case["load_after"] == "200 OK."
        assert case["readback_db_version"] == "2.3"
        assert case["readback_project_address"] == case["name"]
        assert case["preview"][-1] == "200 OK."
    for case in rejected:
        assert case["source_sha256"] == case["backup_sha256"]
        assert case["source_unchanged"] is True
        assert case["preview"][-1] == case["transform"]
        assert case["transform"].endswith("No suitable transforms")
    custom = receipt["custom_stylesheet_output"]
    assert custom["preview_source_unchanged"] is True
    assert custom["preview_output_unchanged"] is True
    assert custom["source_backup_created"] is False
    assert custom["source_unchanged_after_transform"] is True
    assert custom["load_after"] == "200 OK."
    assert custom["readback_db_version"] == "2.3"
    assert custom["readback_project_address"] == "VOUT"
    assert custom["in_place"]["backup_sha256"] == custom["source_sha256"]
    assert custom["in_place"]["output_sha256"] == custom["output_sha256"]
    assert custom["in_place"]["readback_db_version"] == "2.3"
    assert custom["in_place"]["readback_project_address"] == "VINLINE"
