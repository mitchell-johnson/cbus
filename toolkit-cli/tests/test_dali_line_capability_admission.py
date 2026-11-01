"""Server-advertised DALI line leaf ownership, consumed fail-closed by the CLI.

cmqttd advertises `writable_line_fields` inside the
`dali_session_extended_proxy` capability document: the identity and byte
ownership of every line leaf it admits as a native-serialization-owned edit.
The committed wire vector
``rust/testdata/vectors/dali_proxy_line_capability.json`` pins the exact rows.
This module verifies, at the pure unit layer:

* the CLI's evidence-bound line admission table (the executed original line
  vector receipt projection in ``dali_extended_proxy.LINE_FIELDS``) equals the
  committed advertisement row-for-row, so the server advertisement and the
  retained evidence are the same set;
* ``_preflight`` consumes a present advertisement as an additional fail-closed
  cross-check — an edit needs both the advertisement's leaf identity and byte
  ownership, and the retained evidence; neither alone suffices — while a
  missing advertisement keeps the pre-unbind table-only behaviour and the CLI
  refuses anything unevidenced or natively excluded regardless of what is
  advertised.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from cbus_toolkit.dali_commissioning import (
    DaliCommissioning, DaliCommissioningError, deployment_edit_dispositions,
)
from cbus_toolkit import dali_extended_proxy

from test_dali_commissioning import LINE_PREFIX, TARGET, ScriptedService, line_proxy

ROOT = Path(__file__).resolve().parents[2]
VECTOR = json.loads((ROOT / "rust/testdata/vectors/dali_proxy_line_capability.json").read_text())

EDIT_SUFFIX = "line/1/sceneTriggerMap/16/actionSelector"
EDIT = {"path": dali_extended_proxy.PREFIX + EDIT_SUFFIX, "value": {"0": 11, "15": 22}}
EDIT_ADDRESSES = list(dali_extended_proxy.LINE_FIELDS[EDIT_SUFFIX]["addresses"])


def vector_rows():
    assert VECTOR["format"] == "cbus-dali-proxy-line-capability-wire-v1"
    return VECTOR["writable_line_fields"]


def proxy_contract(rows=None, **override):
    contract = {
        "families": [], "native_reserved_bits": True, "excluded_bytes": True,
        "writable_global_fields": [], "line_families": 15, "whole_recalled_families": True,
    }
    if rows is not None:
        contract["writable_line_fields"] = rows
    contract.update(override)
    return contract


class AdvertisedLineLeafAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service = ScriptedService()
        self.workflow = DaliCommissioning(self.service)

    def deploy(self, edits, name="attempt.json"):
        self.service.model_transform = (
            lambda model: model["cdg"].update({"extParams": {"proxy": line_proxy()}}))
        return self.workflow.deploy(TARGET, edits, extract_type="EXT_ONLY",
                                    deploy_type="EXT_ONLY", journal=Path(self.directory.name) / name)

    def test_cli_evidence_table_equals_the_committed_wire_vector(self):
        rows = vector_rows()
        self.assertEqual(len(rows), 2832)
        advertised = {row["path"]: row["addresses"] for row in rows}
        self.assertEqual(len(advertised), 2832)
        table = {dali_extended_proxy.PREFIX + suffix: list(spec["addresses"])
                 for suffix, spec in dali_extended_proxy.LINE_FIELDS.items()}
        self.assertEqual(len(table), 2832)
        self.assertEqual(
            advertised, table, "server advertisement diverges from the CLI's evidence-bound table")
        self.assertEqual([row["path"] for row in rows], list(table), "row order")
        refused = ("statusCorrectionMask", "statusCorrectionInterval",
                   "lampRunningTime", "oidToShortAddress")
        for row in rows:
            self.assertFalse(any(f"/{family}/" in row["path"] for family in refused), row["path"])
            self.assertRegex(row["path"], r"^/cdg/extParams/proxy/line/[01]/")
            for address in row["addresses"]:
                self.assertTrue(type(address) is int and 0 <= address < 11376, row["path"])

    def test_full_committed_advertisement_admits_an_evidenced_leaf(self):
        self.service.caps["dali_session_extended_proxy"] = proxy_contract(rows=vector_rows())
        result = self.deploy([deepcopy(EDIT)])
        self.assertTrue(result["complete"])
        self.assertEqual(result["edit_dispositions"][0]["kind"], "proxy")
        self.assertTrue(any(" DEPLOY " in command for command in self.service.commands))

    def test_per_leaf_advertisement_admits_its_own_leaf(self):
        row = {"path": EDIT["path"], "addresses": EDIT_ADDRESSES}
        self.service.caps["dali_session_extended_proxy"] = proxy_contract(rows=[row])
        result = self.deploy([deepcopy(EDIT)])
        self.assertTrue(result["complete"])

    def test_unadvertised_but_evidenced_leaf_is_refused_before_commands(self):
        self.service.caps["dali_session_extended_proxy"] = proxy_contract(rows=[])
        with self.assertRaisesRegex(
                DaliCommissioningError,
                "DALI server line leaf ownership does not match this reviewed CLI plan"):
            self.deploy([deepcopy(EDIT)])
        self.assertEqual(self.service.commands, ["CMQTT CAPABILITIES"])

    def test_advertised_leaf_ownership_mismatch_is_refused(self):
        self.service.caps["dali_session_extended_proxy"] = proxy_contract(
            rows=[{"path": EDIT["path"], "addresses": EDIT_ADDRESSES[::-1]}])
        with self.assertRaisesRegex(DaliCommissioningError, "line leaf ownership"):
            self.deploy([deepcopy(EDIT)], name="reversed.json")
        twin = [{"path": EDIT["path"], "addresses": EDIT_ADDRESSES} for _ in range(2)]
        self.service.caps["dali_session_extended_proxy"].update(proxy_contract(rows=twin))
        self.service.commands.clear()
        with self.assertRaisesRegex(DaliCommissioningError, "line leaf ownership"):
            self.deploy([deepcopy(EDIT)], name="duplicated.json")

    def test_advertisement_cannot_open_unevidenced_or_refused_leaves(self):
        self.service.caps["dali_session_extended_proxy"] = proxy_contract(rows=vector_rows())
        cases = [
            ("statically excluded mask",
             {"path": LINE_PREFIX + "0/statusCorrectionMask/members", "value": [1]},
             "statically excluded"),
            ("statically excluded interval",
             {"path": LINE_PREFIX + "1/statusCorrectionInterval/interval", "value": 8},
             "statically excluded"),
            ("overwritten forward map",
             {"path": LINE_PREFIX + "0/oidToShortAddress/map", "value": [0] * 64},
             "never the effective writer"),
            ("lamp running time",
             {"path": LINE_PREFIX + "0/lampRunningTime/3/time", "value": 0},
             "not admitted"),
            ("unknown line field",
             {"path": LINE_PREFIX + "0/objectProperties/0/unknownField", "value": 1},
             "not an evidenced native writable leaf"),
            ("whole line object",
             {"path": LINE_PREFIX + "1/virtualGroups/5", "value": {"members": [2]}},
             "not an evidenced native writable leaf"),
            ("uncovered sub-leaf",
             {"path": LINE_PREFIX + "0/remoteOnMask/members/0", "value": 1},
             "not an evidenced native writable leaf"),
            ("computed read-only map",
             {"path": LINE_PREFIX + "0/utilitySaToOidMap/map", "value": {}},
             "computed read-only"),
        ]
        for reason, edit, pattern in cases:
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(ValueError, pattern):
                    self.deploy([edit])
        # The CLI table refuses all of these before any connection, so the
        # advertised per-leaf schema cannot open or even reach them.
        self.assertEqual(self.service.commands, [])
        for reason, edit, pattern in cases:
            with self.subTest(reason=reason + " (preconnect)"):
                with self.assertRaisesRegex(ValueError, pattern):
                    deployment_edit_dispositions([edit], "B", None, dry_run=True)

    def test_missing_advertisement_keeps_the_table_only_behaviour(self):
        self.service.caps["dali_session_extended_proxy"] = proxy_contract()
        result = self.deploy([deepcopy(EDIT)])
        self.assertTrue(result["complete"])
        self.assertTrue(
            all(row["server_leaf_schema_advertised"] is False for row in result["edit_dispositions"]))

    def test_malformed_top_level_advertisement_keeps_the_table_only_behaviour(self):
        for index, broken in enumerate(({"writable_line_fields": {"path": EDIT["path"]}},
                                        {"writable_line_fields": "no"})):
            with self.subTest(broken=broken):
                self.service.caps["dali_session_extended_proxy"] = proxy_contract(**broken)
                self.service.commands.clear()
                result = self.deploy([deepcopy(EDIT)], name=f"table-only-{index}.json")
                self.assertTrue(result["complete"])
                self.assertEqual(self.service.commands[0], "CMQTT CAPABILITIES")

    def test_leaf_without_a_malformed_well_formed_row_is_not_advertised(self):
        broken = [{"path": EDIT["path"]}, {"addresses": [1]},
                  {"path": EDIT["path"], "addresses": [None, "x"]}]
        self.service.caps["dali_session_extended_proxy"] = proxy_contract(rows=broken)
        with self.assertRaisesRegex(DaliCommissioningError, "line leaf ownership"):
            self.deploy([deepcopy(EDIT)], name="malformed-rows.json")

    def test_advertised_rows_never_relax_the_family_count_contract(self):
        self.service.caps["dali_session_extended_proxy"] = proxy_contract(rows=vector_rows(),
                                                                         line_families=14)
        with self.assertRaisesRegex(DaliCommissioningError, "line serializer is unavailable"):
            self.deploy([deepcopy(EDIT)], name="old-count.json")
        self.service.caps["dali_session_extended_proxy"].update(
            proxy_contract(rows=vector_rows(), whole_recalled_families=False))
        self.service.commands.clear()
        with self.assertRaisesRegex(DaliCommissioningError, "line serializer is unavailable"):
            self.deploy([deepcopy(EDIT)], name="partial-recall.json")
        self.service.caps["dali_session_extended_proxy"].update(
            proxy_contract(rows=vector_rows(), line_families=15, whole_recalled_families=True))
        result = self.deploy([deepcopy(EDIT)], name="accepted.json")
        self.assertTrue(result["complete"])


if __name__ == "__main__":
    unittest.main()
