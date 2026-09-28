"""Pin the owned original C-Gate KEYGL5 legacy migration observation."""
from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "research/fixtures/project-legacy-transform-units-native-receipt.json"
RECEIPT_SHA256 = "430150d6b49ea07481f3555ad386a8777b67e8f84396c807ffee0f77f709fe3e"
SOURCE_FILES = {
    "native_test_sha256": "tests/test_project_legacy_transform_units_native.py",
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


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_keygl5_legacy_migration_receipt_is_source_bound() -> None:
    assert digest(RECEIPT) == RECEIPT_SHA256
    receipt = json.loads(RECEIPT.read_bytes())
    assert receipt["format"] == "cbus-project-legacy-transform-units-native-v1"
    assert receipt["physical_networks_opened"] is False
    assert all(receipt["service"].values())
    assert receipt["sources"]["transform_sha256"] == STYLESHEET_HASHES
    for field, path in SOURCE_FILES.items():
        assert receipt["sources"][field] == digest(ROOT / path)
    assert [(case["case"], case["source_db_version"], case["removed_pp"])
            for case in receipt["cases"]] == [
                ("UGEN", "2.1", []), ("UGEN2", "2", []),
                ("UREM", "2.1", ["Remote3Identity"]),
                ("UFEATURE", "2", ["FeatureSet"]),
            ]
    for case in receipt["cases"]:
        assert case["source_sha256"] == case["backup_sha256"]
        assert case["native_bytes_equal_portable"] is True
        assert (case["load_before"], case["transform"], case["load_after"],
                case["readback"]) == (408, 200, 200, 344)
