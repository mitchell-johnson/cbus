"""Pin the owned original C-Gate observation for Unit-conditioned templates."""
from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "research/fixtures/project-legacy-transform-templates-native-receipt.json"
RECEIPT_SHA256 = "9c54dec8159343972020f0b17b5cb59838195e44393fc5bb4b06ca684cfe0f15"
CENSUS = ROOT / "research/fixtures/project-legacy-transform-template-census.json"
SOURCE_FILES = {
    "census_sha256": "research/fixtures/project-legacy-transform-template-census.json",
    "native_test_sha256": "tests/test_project_legacy_transform_templates_native.py",
    "portable_module_sha256": "src/cbus_toolkit/project_legacy_transform.py",
    "portable_test_sha256": "tests/test_project_legacy_transform_templates.py",
    "owned_service_harness_sha256": "research/local_cgate.py",
}
CASES = ("FW21", "FW2", "FW22", "DLT21", "DLT2", "NEO21", "NS2", "NS21", "WL21", "WL2", "EXP2")
# Templates whose effect depends on Unit type, firmware, namespace or a PP
# expansion/rename; each must have at least one native byte-equal case here.
NATIVE_BRANCH_CLASSES = {"conditional-parameter-removal", "parameter-addition",
                         "namespace-parameter-addition", "firmware-rename",
                         "parameter-expansion", "parameter-rename"}


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_template_migration_receipt_is_source_bound() -> None:
    assert digest(RECEIPT) == RECEIPT_SHA256
    receipt = json.loads(RECEIPT.read_bytes())
    assert receipt["format"] == "cbus-project-legacy-transform-templates-native-v1"
    assert receipt["physical_networks_opened"] is False
    assert all(receipt["service"].values())
    for field, path in SOURCE_FILES.items():
        assert receipt["sources"][field] == digest(ROOT / path)
    census = json.loads(CENSUS.read_bytes())
    assert {name: value for name, value in census["sources"].items()} == receipt["sources"]["transform_sha256"]
    assert tuple(case["case"] for case in receipt["cases"]) == CASES
    exercised = set()
    for case in receipt["cases"]:
        assert case["source_sha256"] == case["backup_sha256"]
        assert case["native_bytes_equal_portable"] is True
        assert case["readback_units_equal_portable"] is True
        assert (case["load_before"], case["transform"], case["load_after"],
                case["readback"]) == (408, 200, 200, 344)
        assert case["firmware_changes"] == (0 if case["source_db_version"] == "2.2" else 7)
        exercised.update(case["templates"])
    branch_ids = {row["id"] for row in census["templates"]
                  if row["classification"] in NATIVE_BRANCH_CLASSES}
    assert branch_ids == exercised
    assert all(row["portable_coverage"] for row in census["templates"])
