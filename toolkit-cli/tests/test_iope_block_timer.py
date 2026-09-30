"""IOPE Environment timer source vectors, guards and preservation."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import unittest

from cbus_toolkit.iope_block_timer import (
    EXPIRY, FORMAT, LAYOUTS, WRITABLE, IopeBlockTimer, plan_from_dict)
from cbus_toolkit.iope_environment import CACHE_FORMAT
from cbus_toolkit.iope_settings import PROFILES
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.pp_editor import PPApplyError, PPEditError
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from test_macros import Session

CACHE = {"format": CACHE_FORMAT, "source": "synthetic existing same-network groups",
         "applications": [{"address": 56, "groups": list(range(10, 30))}]}
DEFAULTS = {
    "Application": [56, 57], "InputGroupAddress": list(range(10, 18)),
    "CorridorMasterGroup": [255], "FirstJoinPrimaryApplication": [255],
    "SecondJoinPrimaryApplication": [255], "FirstJoinEnableControlApplication": [255],
    "SecondJoinEnableControlApplication": [255], "CorridorGroupBlock": [2],
    "FirstCorridorOfficeGroupBlock": [3], "SecondCorridorOfficeGroupBlock": [4],
    "FirstCorridorLinkEnable": [1], "TimerExpiryCommand": [0x40] * 8,
    "TimerHighByte": [0] * 8, "TimerLowByte": [60] * 8,
}


def fixture(unit_type="IOPE2R2"):
    parameters = {}
    for name, (kind, address, size, bits, bit, skip) in LAYOUTS.items():
        fields = {"Name": name, "Type": kind, "Address": str(address), "ArraySize": str(size),
                  "BitAddress": str(bit), "ArraySkip": str(skip),
                  "DefaultValue": " ".join(map(str, DEFAULTS.get(name, [0] * size)))}
        if kind == "int":
            fields.update(BitSize=str(bits), MinValue="0", MaxValue=str((1 << bits) - 1))
        parameters[name] = ParameterSpec(name, kind, "synthetic.xml", fields)
    # Sentinels are outside this editor's ownership, including old hidden-effect targets.
    for name, address, value in (("Pot1TimerExpiryCommand", 0x34, 0xF0),
                                 ("Pot2TimerExpiryCommand", 0x35, 0xE1),
                                 ("Memory1", 0x10, 27), ("Unrelated", 0x70, 71)):
        parameters[name] = ParameterSpec(name, "int", "synthetic.xml",
                                        {"Name": name, "Type": "int", "Address": str(address),
                                         "DefaultValue": str(value)})
    return UnitSpec(unit_type + ".xml", {"Type": unit_type}, ("synthetic.xml",), parameters)


def session(unit_type="IOPE2R2", firmware="1.2.00"):
    result = Session(fixture(unit_type))
    result.firmware = firmware
    result.catalog_number = PROFILES[unit_type].catalog_number
    return result


class BlockTimerTest(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.editor = IopeBlockTimer(self.spec)
        self.current = self.spec.defaults()
        self.identity = ("IOPE2R2", "1.2.00", "5752PP/2R")

    def plan(self, **options):
        return self.editor.plan(self.current, identity=self.identity, group_cache=CACHE, **options)

    def test_original_full_byte_command_vectors_all_profiles(self):
        vectors = {"idle": 0x00, "toggle": 0x4F, "on": 0x47, "off": 0x40}
        self.assertEqual(dict(EXPIRY), vectors)
        for unit_type in PROFILES:
            editor = IopeBlockTimer(fixture(unit_type))
            for retained in vectors.values():
                for name, code in vectors.items():
                    with self.subTest(unit_type=unit_type, retained=retained, selected=name):
                        current = fixture(unit_type).defaults()
                        current["TimerExpiryCommand"] = [0xA5, 0xB6, 0x40, retained, 0xC7, 0xD8, 0xE9, 0xFA]
                        plan = editor.plan(current, identity=(unit_type, "1.2.00", None),
                                           block=4, seconds=0x1234, expiry=name, group_cache=CACHE)
                        final = {**plan.expected, **plan.changes}
                        self.assertEqual(final["TimerExpiryCommand"],
                                         (0xA5, 0xB6, 0x40, code, 0xC7, 0xD8, 0xE9, 0xFA))
                        self.assertEqual(final["TimerHighByte"][3], 0x12)
                        self.assertEqual(final["TimerLowByte"][3], 0x34)
                        before = editor.codec.encode_many(plan.expected).apply(
                            MemoryImage.from_bytes(bytes([0xA5]) * 256))
                        after = editor.codec.encode_many(plan.changes).apply(before)
                        self.assertEqual(after.byte(0x39), code)
                        self.assertEqual((after.byte(0x43), after.byte(0x4B)), (0x12, 0x34))
                        for address in range(256):
                            if address not in (0x39, 0x43, 0x4B):
                                self.assertEqual(after.byte(address), before.byte(address))
                        self.assertLessEqual(set(plan.changes), WRITABLE)
                        self.assertFalse(plan.details["input_source_bound"])
                        self.assertEqual(plan.details["timer_variant"], 1)

    def test_office_and_corridor_duration_boundaries(self):
        for seconds in (0, 1, 59, 60, 255, 256, 65535):
            with self.subTest(role="office", seconds=seconds):
                final = self.plan(block=4, seconds=seconds)
                merged = {**final.expected, **final.changes}
                self.assertEqual(merged["TimerHighByte"][3] * 256 + merged["TimerLowByte"][3], seconds)
                self.assertEqual(final.details["minimum_seconds"], 0)
        for seconds in (60, 255, 256, 65535):
            with self.subTest(role="corridor", seconds=seconds):
                self.assertEqual(self.plan(block=3, seconds=seconds).details["minimum_seconds"], 60)
        for seconds in (0, 1, 59):
            with self.subTest(seconds=seconds), self.assertRaisesRegex(PPEditError, "at least 60"):
                self.plan(block=3, seconds=seconds)
        self.current["TimerLowByte"] = [60, 60, 59, 60, 60, 60, 60, 60]
        with self.assertRaisesRegex(PPEditError, "initial control normalization"):
            self.plan(block=3, seconds=60, expiry="off")
        self.plan(block=4, seconds=0)

    def test_role_enable_and_stable_environment_guards(self):
        self.assertEqual(self.plan(block=3).details["environment_role"], "corridor")
        self.assertEqual(self.plan(block=4).details["environment_role"], "first-office")
        with self.assertRaisesRegex(PPEditError, "enabled Environment timer role"):
            self.plan(block=5, expiry="on")
        self.current["SecondCorridorLinkEnable"] = "1"
        self.assertEqual(self.plan(block=5, expiry="on").details["environment_role"], "second-office")
        self.current["FirstCorridorLinkEnable"] = "0"
        with self.assertRaisesRegex(PPEditError, "initialization would change"):
            self.plan(block=3, expiry="on")
        self.current["SecondCorridorLinkEnable"] = "0"
        with self.assertRaisesRegex(PPEditError, "controls are disabled"):
            self.plan(block=4, expiry="on")
        self.current["FirstCorridorLinkEnable"] = "1"
        self.current["FirstCorridorOfficeGroupBlock"] = "2"
        with self.assertRaisesRegex(PPEditError, "initialization would change"):
            self.plan(block=4, expiry="on")

    def test_missing_group_and_metadata_never_infer_objects(self):
        for cache in (None, {}, {**CACHE, "applications": []},
                      {**CACHE, "applications": [{"address": 56, "groups": [10]}]}):
            with self.subTest(cache=cache), self.assertRaises(PPEditError):
                self.editor.plan(self.current, identity=self.identity, block=4, expiry="off", group_cache=cache)
        self.current["InputGroupAddress"] = [10, 11, 12, 255, 14, 15, 16, 17]
        with self.assertRaisesRegex(PPEditError, "existing assigned group"):
            self.plan(block=4, expiry="off")

    def test_every_unsupported_retained_byte_refused_even_when_replacing(self):
        for retained in set(range(256)) - {0x00, 0x4F, 0x47, 0x40}:
            self.current["TimerExpiryCommand"] = [0x40, 0x40, 0x40, retained, 0x40, 0x40, 0x40, 0x40]
            with self.subTest(retained=retained), self.assertRaisesRegex(PPEditError, "Retained expiry"):
                self.plan(block=4, seconds=120, expiry="off")

    def test_options_exact_types_and_no_raw_expiry_admission(self):
        for options in ({"block": None}, {"block": True}, {"block": 0}, {"block": 9},
                        {"block": 4, "seconds": True}, {"block": 4, "seconds": -1},
                        {"block": 4, "seconds": 65536}, {"block": 4, "seconds": 1.0},
                        {"block": 4, "expiry": 0x40}, {"block": 4, "expiry": "ramp_off"},
                        {"block": 4, "expiry": "OFF"}, {"block": 4, "expiry": []}):
            pp = session()
            with self.subTest(options=options), self.assertRaises(PPEditError):
                self.editor.configure(pp, group_cache=CACHE, **options)
            self.assertEqual(pp.calls, [])

    def test_exact_profile_and_schema_admission(self):
        for unit_type in PROFILES:
            for firmware in ("1.0.00", "1.1.00", "1.2.00", "1.2.99"):
                pp = session(unit_type, firmware)
                IopeBlockTimer(pp.spec).configure(pp, block=4, expiry="on", group_cache=CACHE)
        for firmware in ("0.9.99", "1.3.00", None):
            pp = session(firmware=firmware)
            with self.assertRaises(PPEditError):
                self.editor.configure(pp, block=4, expiry="on", group_cache=CACHE)
            self.assertEqual(pp.calls, [])
        for identity in (None, self.identity[:2], ("IOPE1R1", "1.2.00", None),
                         ("IOPE2R2", "1.2.00", "wrong")):
            with self.assertRaises(PPEditError):
                self.editor.plan(self.current, identity=identity, block=4, group_cache=CACHE)
        with self.assertRaises(PPEditError):
            IopeBlockTimer(self.spec, "IOPE1R1")
        old = self.spec.parameters["TimerExpiryCommand"]
        bad = replace(old, fields={**old.fields, "BitSize": "4"})
        with self.assertRaisesRegex(PPEditError, "Unsupported parameter layout"):
            IopeBlockTimer(replace(self.spec, parameters={**self.spec.parameters, old.name: bad}))

    def test_apply_roundtrip_stale_preservation_and_partial_write_rollback(self):
        pp = session()
        before = pp.values()
        plan = self.editor.plan(before, identity=self.identity, block=4,
                                seconds=65535, expiry="on", group_cache=CACHE)
        result = self.editor.apply(pp, plan_from_dict(json.loads(json.dumps(plan.as_dict()))))
        self.assertTrue(result["verified"])
        self.assertFalse(result["saved"])
        for key, value in before.items():
            if key not in WRITABLE:
                self.assertEqual(pp.values()[key], value)
        with self.assertRaisesRegex(PPEditError, "changed since"):
            self.editor.apply(pp, plan)
        pp = session()
        pp.current["CorridorGroupBlock"] = "1"
        with self.assertRaisesRegex(PPEditError, "changed since"):
            self.editor.apply(pp, plan)
        self.assertEqual(pp.calls, [])
        for failure in ("TimerExpiryCommand", "TimerHighByte", "TimerLowByte"):
            pp = session()
            pp.failure = failure
            with self.subTest(failure=failure), self.assertRaises(PPApplyError):
                self.editor.apply(pp, plan)
            self.assertEqual(pp.values(), before)

    def test_saved_plan_cannot_forge_dependency_writes_or_claims(self):
        original = self.plan(block=4, seconds=65535, expiry="on").as_dict()
        edits = ({"changes": {"InputGroupAddress": [11] * 8}}, {"firmware": "1.1.00"},
                 {"catalog_number": "wrong"}, {"timer_variant": 2}, {"input_source_bound": True},
                 {"environment_role": "corridor"}, {"minimum_seconds": 60}, {"device_verified": True},
                 {"options": {"block": 4}}, {"options": {**original["options"], "raw": 71}},
                 {"spec_filename": "IOPE1R1.xml"}, {"extra": True}, {"saved": True})
        for edit in edits:
            pp = session()
            with self.subTest(edit=edit), self.assertRaises(PPEditError):
                self.editor.apply(pp, plan_from_dict({**deepcopy(original), **edit}))
            self.assertEqual(pp.calls, [])
        for field in ("expected", "changes"):
            document = deepcopy(original)
            document[field]["TimerExpiryCommand"] = [True] * 8
            with self.assertRaises(PPEditError):
                plan_from_dict(document)

    def test_show_preserves_unknown_commands_and_does_not_claim_eligibility(self):
        self.current["TimerExpiryCommand"] = [0xF0] * 8
        view = self.editor.show(self.current)
        self.assertIsNone(view["blocks"][3]["expiry"])
        self.assertEqual(view["blocks"][3]["expiry_code"], 0xF0)
        self.assertFalse(view["group_objects_resolved"])

    def test_source_receipt_names_boundaries(self):
        receipt = json.loads((Path(__file__).resolve().parents[1] /
                              "research/fixtures/iope-block-timer-source-review.json").read_text())
        self.assertEqual(receipt["format"], "cbus-iope-block-timer-source-review-v1")
        self.assertFalse(receipt["original_execution"])
        self.assertEqual(receipt["writable_parameters"], sorted(WRITABLE))
        self.assertEqual(receipt["expiry_commands"], {"idle": 0, "toggle": 79, "on": 71, "off": 64})
        self.assertIn("0x11ab7f8", {method["start"] for method in receipt["methods"]})
        self.assertEqual(FORMAT, "cbus-iope-block-timer-plan-v1")


@unittest.skipUnless(os.environ.get("CBUS_TOOLKIT_EXE") and os.environ.get("CBUS_UNITSPEC_DIR"),
                     "Set original Toolkit EXE and decoded UnitSpecs for static source checks")
class BlockTimerOriginalSourceTest(unittest.TestCase):
    def test_original_hashes_methods_resources_and_layouts(self):
        import pefile
        from cbus_toolkit.unitspec import UnitSpecStore
        receipt = json.loads((Path(__file__).resolve().parents[1] /
                              "research/fixtures/iope-block-timer-source-review.json").read_text())
        executable = Path(os.environ["CBUS_TOOLKIT_EXE"])
        data, mapping = executable.read_bytes(), executable.with_suffix(".map").read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), receipt["toolkit_exe_sha256"])
        self.assertEqual(hashlib.sha256(mapping).hexdigest(), receipt["toolkit_map_sha256"])
        image = pefile.PE(data=data)
        base = image.OPTIONAL_HEADER.ImageBase
        segments = {i: base + next(s.VirtualAddress for s in image.sections if s.Name.startswith(name))
                    for i, name in ((1, b".text"), (2, b".itext"))}
        symbols, addresses = {}, set()
        for line in mapping.decode("ascii").splitlines():
            match = re.match(r"^\s+000([12]):([0-9A-Fa-f]{8})\s+(\S+)\s*$", line)
            if match:
                address = segments[int(match[1])] + int(match[2], 16)
                symbols.setdefault(match[3], set()).add(address)
                addresses.add(address)
        starts = sorted(addresses)
        for method in receipt["methods"]:
            start, end = int(method["start"], 16), int(method["end"], 16)
            self.assertIn(start, symbols[method["name"]])
            self.assertEqual(starts[starts.index(start) + 1], end)
            self.assertEqual(hashlib.sha256(image.get_data(start - base, end - start)).hexdigest(),
                             method["sha256"])
        resources = {}
        for kind in image.DIRECTORY_ENTRY_RESOURCE.entries:
            if not hasattr(kind, "directory"):
                continue
            for named in kind.directory.entries:
                if named.name:
                    for locale in named.directory.entries:
                        blob = locale.data.struct
                        resources.setdefault(str(named.name), set()).add(
                            hashlib.sha256(image.get_data(blob.OffsetToData, blob.Size)).hexdigest())
        for name, digest in receipt["form_resource_sha256"].items():
            self.assertEqual(resources.get(name), {digest})
        directory = Path(os.environ["CBUS_UNITSPEC_DIR"])
        for name, digest in receipt["unitspec_sha256"].items():
            self.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(), digest)
        store = UnitSpecStore(directory)
        for unit_type in PROFILES:
            IopeBlockTimer(store.load(unit_type + ".xml"))


if __name__ == "__main__":
    unittest.main()
