"""Independent synthetic IOPE corridor transitions and mutation refusal."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
import re
from pathlib import Path
import unittest

from cbus_toolkit.iope_environment import (
    CACHE_FORMAT, FORMAT, LAYOUTS, PROFILES, WRITABLE, IopeEnvironment, plan_from_dict)
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.pp_editor import PPApplyError, PPEditError
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from test_macros import Session


# Synthetic model, not a site or vendor unit specification.
DEFAULTS = {
    "Application": [56, 57], "InputGroupAddress": list(range(10, 18)),
    "CorridorMasterGroup": [255], "FirstJoinPrimaryApplication": [255],
    "SecondJoinPrimaryApplication": [255], "FirstJoinEnableControlApplication": [255],
    "SecondJoinEnableControlApplication": [255], "CorridorGroupBlock": [0],
    "FirstCorridorOfficeGroupBlock": [1], "SecondCorridorOfficeGroupBlock": [2],
}
CACHE = {"format": CACHE_FORMAT, "source": "synthetic same-network object inventory",
         "applications": [{"address": 56, "groups": list(range(10, 31))},
                          {"address": 57, "groups": list(range(10, 31))},
                          {"address": 203, "groups": list(range(10, 31))}]}


def fixture(unit_type="IOPE2R2"):
    parameters = {}
    for name, (kind, address, size, bits, bit, skip) in LAYOUTS.items():
        fields = {"Name": name, "Type": kind, "Address": str(address), "ArraySize": str(size),
                  "BitAddress": str(bit), "ArraySkip": str(skip),
                  "DefaultValue": " ".join(map(str, DEFAULTS.get(name, [0] * size)))}
        if kind == "int":
            fields.update(BitSize=str(bits), MinValue="0", MaxValue=str((1 << bits) - 1))
        parameters[name] = ParameterSpec(name, kind, "synthetic.xml", fields)
    parameters["Unrelated"] = ParameterSpec("Unrelated", "int", "synthetic.xml", {
        "Name": "Unrelated", "Type": "int", "Address": "112", "DefaultValue": "71"})
    return UnitSpec(unit_type + ".xml", {"Type": unit_type}, ("synthetic.xml",), parameters)


def session(unit_type="IOPE2R2"):
    result = Session(fixture(unit_type))
    result.firmware = "1.2.00"
    result.catalog_number = PROFILES[unit_type].catalog_number
    return result


class EnvironmentTest(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = IopeEnvironment(self.spec)
        self.current = self.spec.defaults()
        self.identity = ("IOPE2R2", "1.2.00", "5752PP/2R")

    def plan(self, **options):
        return self.editor.plan(self.current, identity=self.identity, group_cache=CACHE, **options)

    def active(self):
        self.current.update(FirstCorridorLinkEnable="1", CorridorGroupBlock="2",
                            FirstCorridorOfficeGroupBlock="3", SecondCorridorOfficeGroupBlock="4")

    def test_enable_source_vector_and_shared_byte_preservation(self):
        plan = self.plan(enabled=True)
        self.assertEqual(dict(plan.changes), {
            "CorridorGroupBlock": (2,), "FirstCorridorOfficeGroupBlock": (3,),
            "SecondCorridorOfficeGroupBlock": (4,), "FirstCorridorLinkEnable": (1,)})
        image = self.editor.codec.encode_many(plan.changes).apply(MemoryImage({0x6B: 0x41, 0x6C: 0xE2}))
        self.assertEqual((image.byte(0x6B), image.byte(0x6C)), (0xD3, 0xE4))
        self.assertEqual(len(plan.details["derived"]), 3)
        self.assertFalse(plan.details["whole_dialog_save"])
        self.assertLessEqual(set(plan.changes), WRITABLE)

    def test_role_changes_use_public_one_based_block_numbers(self):
        self.active()
        plan = self.plan(corridor_block=8, first_office_block=7, second_office_enabled=True,
                         second_office_block=6, master_group=20)
        self.assertEqual(dict(plan.changes), {
            "CorridorMasterGroup": (20,), "CorridorGroupBlock": (7,),
            "FirstCorridorOfficeGroupBlock": (6,), "SecondCorridorOfficeGroupBlock": (5,),
            "SecondCorridorLinkEnable": (1,)})
        self.current.update({k: list(v) for k, v in plan.changes.items()})
        disabled = self.plan(enabled=False)
        self.assertEqual(dict(disabled.changes), {
            "FirstCorridorLinkEnable": (0,), "SecondCorridorLinkEnable": (0,)})
        self.assertIn("disabling corridor", disabled.details["derived"][0]["cause"])

    def test_initialization_clears_conflicting_master_and_repairs_roles(self):
        self.current.update(CorridorMasterGroup="10", CorridorGroupBlock="0",
                            FirstCorridorOfficeGroupBlock="0", SecondCorridorOfficeGroupBlock="0",
                            SecondCorridorLinkEnable="1")
        plan = self.plan()
        self.assertEqual(dict(plan.changes), {
            "CorridorMasterGroup": (255,), "FirstCorridorOfficeGroupBlock": (2,),
            "SecondCorridorOfficeGroupBlock": (1,), "SecondCorridorLinkEnable": (0,)})
        # Initial active linking prevents the first-enable relocation.
        self.current.update(FirstCorridorLinkEnable="1", CorridorGroupBlock="0",
                            FirstCorridorOfficeGroupBlock="1", SecondCorridorOfficeGroupBlock="2",
                            CorridorMasterGroup="255", SecondCorridorLinkEnable="0")
        self.assertEqual(dict(self.plan().changes), {})

    def test_selector_exclusions_and_disabled_controls(self):
        for options in ({"master_group": 20}, {"corridor_block": 8}, {"second_office_enabled": True}):
            with self.subTest(options=options), self.assertRaises(PPEditError):
                self.plan(**options)
        self.active()
        for options in ({"corridor_block": 4}, {"first_office_block": 3},
                        {"second_office_enabled": True, "second_office_block": 3},
                        {"second_office_block": 8}, {"master_group": 10}):
            with self.subTest(options=options), self.assertRaises(PPEditError):
                self.plan(**options)
        self.assertEqual(self.plan(master_group=255).changes, {})

    def test_application_identity_distinguishes_equal_addresses(self):
        self.active()
        self.current["SecondApplicationBlocks"] = "1"
        # Input block 1 uses 57/10, so primary 56/10 is a distinct object.
        plan = self.plan(master_group=10)
        self.assertEqual(plan.changes["CorridorMasterGroup"], (10,))
        self.current["FirstJoinPrimaryApplication"] = "20"
        with self.assertRaisesRegex(PPEditError, "join uses"):
            self.plan(master_group=20)
        # Enable-Control join takes priority over the primary join parameter.
        self.current["FirstJoinEnableControlApplication"] = "20"
        self.assertEqual(self.plan(master_group=20).changes["CorridorMasterGroup"], (20,))

    def test_second_enable_clears_master_matching_inactive_second_office(self):
        self.active()
        self.current.update(CorridorMasterGroup="14", SecondCorridorOfficeGroupBlock="4")
        plan = self.plan(second_office_enabled=True)
        self.assertEqual(plan.changes["CorridorMasterGroup"], (255,))
        self.assertEqual(plan.changes["SecondCorridorLinkEnable"], (1,))

    def test_metadata_admission_missing_duplicate_and_positive_evidence(self):
        for cache in (None, {}, {**CACHE, "source": ""},
                      {**CACHE, "applications": [CACHE["applications"][0]] * 2},
                      {**CACHE, "applications": [{"address": 56, "groups": [10, 10]}]},
                      {**CACHE, "applications": [{"address": 56, "groups": []}]}):
            with self.subTest(cache=cache), self.assertRaises(PPEditError):
                self.editor.plan(self.current, identity=self.identity, group_cache=cache, enabled=True)
        with self.assertRaisesRegex(PPEditError, "positive group object"):
            self.plan(enabled=True, master_group=31)
        self.current["Application"] = "202 57"
        with self.assertRaisesRegex(PPEditError, "primary Lighting"):
            self.plan(enabled=True)

    def test_firmware_catalogue_and_schema_refusals(self):
        for unit_type in PROFILES:
            editor = IopeEnvironment(fixture(unit_type))
            for firmware in ("1.0.00", "1.1.00", "1.2.00", "1.2.99"):
                editor.plan(fixture(unit_type).defaults(), identity=(unit_type, firmware, None),
                            group_cache=CACHE, enabled=True)
            for firmware in ("0.9.99", "1.3.00", "9", None):
                with self.subTest(unit_type=unit_type, firmware=firmware), self.assertRaises(PPEditError):
                    editor.plan(fixture(unit_type).defaults(), identity=(unit_type, firmware, None),
                                group_cache=CACHE, enabled=True)
        for identity in (None, self.identity[:2], ("IOPE2R2", "1.2.00", "wrong"),
                         ("IOPE1R1", "1.2.00", None)):
            with self.assertRaises(PPEditError):
                self.editor.plan(self.current, identity=identity, group_cache=CACHE)
        with self.assertRaisesRegex(PPEditError, "Use IOPE1R1.xml"):
            IopeEnvironment(self.spec, "IOPE1R1")
        parameter = self.spec.parameters["CorridorGroupBlock"]
        bad = replace(parameter, fields={**parameter.fields, "BitAddress": "2"})
        with self.assertRaisesRegex(PPEditError, "Unsupported parameter layout"):
            IopeEnvironment(replace(self.spec, parameters={**self.spec.parameters, bad.name: bad}))

    def test_invalid_domains_and_types_fail_before_mutation(self):
        for options in ({"enabled": 1}, {"corridor_block": True}, {"first_office_block": 0},
                        {"second_office_block": 9}, {"master_group": 256}, {"master_group": -1}):
            pp = session()
            with self.subTest(options=options), self.assertRaises(PPEditError):
                self.editor.configure(pp, group_cache=CACHE, **options)
            self.assertEqual(pp.calls, [])

    def test_apply_canonical_roundtrip_stale_and_rollback(self):
        pp = session()
        plan = self.editor.plan(pp.values(), identity=self.identity, group_cache=CACHE, enabled=True)
        document = json.loads(json.dumps(plan.as_dict()))
        result = self.editor.apply(pp, plan_from_dict(document))
        self.assertTrue(result["verified"])
        self.assertFalse(result["saved"])
        self.assertEqual(pp.values()["Unrelated"], "71")
        with self.assertRaisesRegex(PPEditError, "changed since"):
            self.editor.apply(pp, plan_from_dict(document))
        pp = session()
        before = pp.values()
        pp.failure = "CorridorGroupBlock"
        with self.assertRaises(PPApplyError):
            self.editor.apply(pp, plan)
        self.assertEqual(pp.values(), before)

    def test_forged_plan_rejected_before_any_write(self):
        original = self.plan(enabled=True).as_dict()
        edits = ({"changes": {"CorridorMasterGroup": [10]}},
                 {"firmware": "1.1.00"}, {"catalog_number": "wrong"},
                 {"options": {"enabled": True}}, {"device_verified": True},
                 {"spec_filename": "IOPE1R1.xml"}, {"extra_claim": True}, {"saved": True},
                 {"changes": {"FirstCorridorLinkEnable": [True]}})
        for edit in edits:
            pp = session()
            document = {**deepcopy(original), **edit}
            with self.subTest(edit=edit), self.assertRaises(PPEditError):
                self.editor.apply(pp, plan_from_dict(document))
            self.assertEqual(pp.calls, [])
        for kind in (True, 1.0):
            document = deepcopy(original)
            document["expected"]["SecondApplicationBlocks"] = [kind]
            with self.assertRaises(PPEditError):
                plan_from_dict(document)
        document = deepcopy(original)
        del document["saved"]
        with self.assertRaises(PPEditError):
            plan_from_dict(document)

    def test_show_is_raw_and_options_are_defensively_copied(self):
        view = self.editor.show(self.current)
        self.assertFalse(view["group_objects_resolved"])
        self.assertEqual((view["corridor_block"], view["master_group"]), (1, 255))
        cache = deepcopy(CACHE)
        plan = self.editor.plan(self.current, identity=self.identity, group_cache=cache, enabled=True)
        cache["applications"][0]["groups"].clear()
        self.assertEqual(plan.details["options"]["group_cache"]["applications"][0]["groups"],
                         list(range(10, 31)))

    def test_sanitized_source_receipt(self):
        path = Path(__file__).resolve().parents[1] / "research/fixtures/iope-environment-source-review.json"
        receipt = json.loads(path.read_text())
        self.assertEqual(receipt["format"], "cbus-iope-environment-source-review-v1")
        self.assertEqual(receipt["original_execution"], False)
        self.assertEqual(receipt["toolkit_exe_sha256"],
                         "9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab")
        for method in receipt["methods"]:
            self.assertEqual(len(method["sha256"]), 64)
        self.assertIn("0x12dbad8", {method["start"] for method in receipt["methods"]})
        self.assertEqual(receipt["writable_parameters"], sorted(WRITABLE))
        self.assertEqual(FORMAT, "cbus-iope-environment-plan-v1")


@unittest.skipUnless(os.environ.get("CBUS_TOOLKIT_EXE") and os.environ.get("CBUS_UNITSPEC_DIR"),
                     "Set original Toolkit EXE and decoded UnitSpecs for source byte checks")
class EnvironmentOriginalSourceTest(unittest.TestCase):
    def test_exact_source_hashes_named_method_ranges_and_layouts(self):
        import pefile
        from cbus_toolkit.unitspec import UnitSpecStore
        root = Path(__file__).resolve().parents[1]
        receipt = json.loads((root / "research/fixtures/iope-environment-source-review.json").read_text())
        executable = Path(os.environ["CBUS_TOOLKIT_EXE"])
        data = executable.read_bytes()
        mapping = Path(os.environ.get("CBUS_TOOLKIT_MAP", executable.with_suffix(".map"))).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), receipt["toolkit_exe_sha256"])
        self.assertEqual(hashlib.sha256(mapping).hexdigest(), receipt["toolkit_map_sha256"])
        image = pefile.PE(data=data)
        base = image.OPTIONAL_HEADER.ImageBase
        segments = {i: base + next(s.VirtualAddress for s in image.sections if s.Name.startswith(name))
                    for i, name in ((1, b".text"), (2, b".itext"))}
        symbols = {}
        for line in mapping.decode("ascii").splitlines():
            match = re.match(r"^\s+000([12]):([0-9A-Fa-f]{8})\s+(\S+)\s*$", line)
            if match:
                symbols[match[3]] = segments[int(match[1])] + int(match[2], 16)
        starts = sorted(set(symbols.values()))
        for method in receipt["methods"]:
            start, end = int(method["start"], 16), int(method["end"], 16)
            self.assertEqual(symbols[method["name"]], start)
            self.assertEqual(starts[starts.index(start) + 1], end)
            self.assertEqual(hashlib.sha256(image.get_data(start - base, end - start)).hexdigest(),
                             method["sha256"])
        directory = Path(os.environ["CBUS_UNITSPEC_DIR"])
        for name, digest in receipt["unitspec_sha256"].items():
            self.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(), digest)
        store = UnitSpecStore(directory)
        for unit_type in PROFILES:
            IopeEnvironment(store.load(unit_type + ".xml"))


if __name__ == "__main__":
    unittest.main()
