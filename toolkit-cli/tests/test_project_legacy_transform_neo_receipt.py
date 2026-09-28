"""Pin the owned original C-Gate Neo legacy migration observation."""
from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "research/fixtures/project-legacy-transform-neo-native-receipt.json"
RECEIPT_SHA256 = "9e2f92f86a3a6ff2e87a2d91da776332ed5e23de6da6d03e30868044b276f67d"
SOURCE_FILES = {
    "native_test_sha256": "tests/test_project_legacy_transform_neo_native.py",
    "portable_module_sha256": "src/cbus_toolkit/project_legacy_transform.py",
    "portable_test_sha256": "tests/test_project_legacy_transform.py",
    "owned_service_harness_sha256": "research/local_cgate.py",
}
STYLESHEET_HASHES = {
    "v2tov21.xslt": "8346eab4259b957d53fc2b5c14ee1e058196124eabe4a7e3fb45b145f74735a8",
    "v21tov22.xslt": "e2090621171b5febf4903eaa964dd7a855b3d3cea827678da3758376dceab875",
    "v22tov23.xslt": "5674534824826a2db5e3b762c207ce0e566298e54703f628d16f9b3d2d47dab2",
    "projectversions.xml": "f9b2e0a83753321e311dee1ac7e1817b28dd984a792a2fd2923efa1cac85aaf8",
}
CASES = ("B2A21", "B2N21", "B2A2", "B2N2", "B4A21", "B4N21", "B4A2", "B4N2")
CONDITIONAL = {"KeyDisableGroupInvert", "CorridorLinkEnable",
               "NightlightColour", "DisableIRNEC"}


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_neo_legacy_migration_receipt_is_source_bound() -> None:
    assert digest(RECEIPT) == RECEIPT_SHA256
    receipt = json.loads(RECEIPT.read_bytes())
    assert receipt["format"] == "cbus-project-legacy-transform-neo-native-v1"
    assert receipt["physical_networks_opened"] is False
    assert all(receipt["service"].values())
    assert receipt["sources"]["transform_sha256"] == STYLESHEET_HASHES
    for field, path in SOURCE_FILES.items():
        assert receipt["sources"][field] == digest(ROOT / path)
    assert tuple(case["case"] for case in receipt["cases"]) == CASES
    for case in receipt["cases"]:
        removed = set(case["removed_pp"])
        assert case["unit_type"] in ("KEYB2", "KEYB4")
        assert case["source_db_version"] in ("2", "2.1")
        assert case["source_sha256"] == case["backup_sha256"]
        assert case["native_bytes_equal_portable"] is True
        assert (case["load_before"], case["transform"], case["load_after"],
                case["readback"]) == (408, 200, 200, 344)
        assert "Remote3Identity" in removed
        assert ("FeatureSet" in removed) == (case["source_db_version"] == "2")
        assert (CONDITIONAL <= removed) == (not case["application_present"])
        assert case["readback_pp_count"] == case["source_pp_count"] - len(case["removed_pp"])
