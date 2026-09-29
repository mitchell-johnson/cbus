"""Opt-in CONVERTUNIT pair acceptance against owned native C-Gate and Rust servers.

Every admitted source/target pair is converted in catalogue and move form and
compared with the independent ``conversion_mapping`` model. The private
mapping table, unit specifications and catalogue are supplied explicitly; the
tests skip without them and never contact a network or physical unit.
"""
import json
import os
from pathlib import Path
import unittest

from research.convertunit_pairs import Inputs, owned_backend, run


ROOT = Path(__file__).resolve().parents[1]
SPECS = os.environ.get("CBUS_UNITSPEC_DIR")
VENDOR = os.environ.get("CBUS_LOCAL_CGATE_VENDOR")
RECEIPT = ROOT / "research/fixtures/convertunit-pairs-native-receipt.json"
# Known Rust residuals, by case: NCC targets declare a device-memory UnitType
# parameter that the shared Rust field map cannot hold beside the database
# identity, C-Bus 3 DIN output channels are not regenerated, and PP LOAD does
# not refuse stored values native C-Gate cannot parse.
NCC_TARGETS = {"DIMDD4", "DIMDD8", "RELDN4A", "RELDN8A", "RELDN16A"}


def private_inputs():
    if not (SPECS and VENDOR):
        return None
    specs, catalog = Path(SPECS), Path(VENDOR) / "unitspec/cbusunits.xml"
    if not (specs / "ConvertUnitMappingTable.xml").is_file() or not catalog.is_file():
        return None
    return specs, catalog


@unittest.skipUnless(os.environ.get("CBUS_CGATE_JAVA") and private_inputs(),
                     "set CBUS_CGATE_JAVA, CBUS_LOCAL_CGATE_VENDOR and CBUS_UNITSPEC_DIR for native conversion pairs")
class NativeConversionPairTests(unittest.TestCase):
    def test_every_admitted_pair_matches_the_independent_model(self):
        specs, catalog = private_inputs()
        inputs = Inputs(specs, catalog, specs / "ConvertUnitMappingTable.xml")
        with owned_backend("native", spec_dir=specs, catalog_path=catalog, table_path=None,
                           vendor=VENDOR, java=os.environ["CBUS_CGATE_JAVA"]) as (client, backend):
            receipt = run(client, inputs)
        failures = [row["id"] for row in [*receipt["cases"], *receipt["negative_cases"], *receipt["boundary_cases"]]
                    if not row["passed"]]
        self.assertEqual(failures, [])
        self.assertTrue(all(row["source_stored_as_rendered"] and row["pp_matches"] for row in receipt["cases"]))
        committed = json.loads(RECEIPT.read_text())
        # The committed evidence is bound to these exact private inputs.
        self.assertEqual({key: receipt["inputs"][key] for key in receipt["inputs"]},
                         {key: committed["inputs"][key] for key in receipt["inputs"]})
        self.assertEqual(backend["cgate_jar_sha256"], committed["backend"]["cgate_jar_sha256"])


def rust_binary(name, variable):
    candidate = Path(os.environ.get(variable) or ROOT.parent / "rust/target/debug" / name)
    return candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None


class RustConversionPairTests(unittest.TestCase):
    def check_backend(self, backend, binary):
        if not (binary and private_inputs()):
            self.skipTest(f"{backend} binary or private conversion inputs are unavailable")
        specs, catalog = private_inputs()
        inputs = Inputs(specs, catalog, specs / "ConvertUnitMappingTable.xml")
        with owned_backend(backend, spec_dir=specs, catalog_path=catalog, table_path=None,
                           binary=binary) as (client, _):
            receipt = run(client, inputs)
        self.assertTrue(all(row["passed"] for row in [*receipt["negative_cases"], *receipt["boundary_cases"]]))
        for row in receipt["cases"]:
            with self.subTest(case=row["id"]):
                self.assertEqual(row["convert"]["final"], "200 OK.")
                self.assertTrue(row["reload_matches"])
                self.assertIs(row.get("source_removed", True), True)
                ncc = row["target_type"] in NCC_TARGETS
                self.assertEqual(row["pp_mismatches"], ["UnitType"] if ncc else [])
                self.assertEqual(row["identity_mismatches"], ["OutputChannels"] if ncc else [])
                unparseable = row["readback"].get("predicted_unparseable")
                self.assertEqual(row["readback"]["mismatches"], ["<unexpected-load>"] if unparseable else [])

    def test_cgate_mock_pairs(self):
        self.check_backend("cgate-mock", rust_binary("cgate-mock", "CBUS_CGATE_MOCK_BIN"))

    def test_cmqttd_pairs(self):
        self.check_backend("cmqttd", rust_binary("cmqttd", "CBUS_CMQTTD_BIN"))


if __name__ == "__main__":
    unittest.main()
