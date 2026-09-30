"""IOPE occupancy-controller settings: offline rules, CLI and owned native C-Gate acceptance."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from cbus_toolkit.iope_settings import (
    BLOCKS, FORMAT, LAYOUTS, PROFILES, IopeSettings, plan_from_dict, profile_refusal, timer_seconds)
from cbus_toolkit.pp_editor import PPApplyError, PPEditError
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore
from test_macros import NATIVE, NATIVE_REASON, Session, closed_network_project, native_endpoint

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "research/fixtures/iope-settings-native-acceptance.json"
REVIEW = ROOT / "research/fixtures/iope-settings-source-review.json"
FIRMWARE = "1.2.00"

# Synthetic defaults: bistable auxiliary 1 on block 1 with a group, block 2
# grouped but only on a momentary auxiliary, block 3 ungrouped.
DEFAULTS = {"Memory1": [128], "Memory2": [153], "Memory3": [191], "Memory4": [230], "LongPressTime": [25],
            "RampRateA": [1], "RampRateB": [2], "RampRateC": [3], "RampRateS": [1], "ClockGenEnable": [1],
            "Sensor1EnableGroupInEnableControlApp": [1], "Sensor2EnableGroupInEnableControlApp": [1],
            "BistableAuxiliary1": [1], "TimerHighByte": [1] * 8, "TimerLowByte": [44] * 8,
            "InputGroupAddress": [10, 11] + [255] * 6, "OutputGroupAddress": [20, 21, 22, 23],
            "Sensor1EnableGroup": [255], "Sensor2EnableGroup": [255], "StatusReportInterval": [3],
            "GroupAssertOnPowerup": [0b110], "Auxiliary1BlockAllocation": [1, 0, 1, 0, 0, 0, 0, 0],
            "Auxiliary2BlockAllocation": [0, 1, 0, 0, 0, 0, 0, 0]}


def fixture(unit_type):
    parameters = {}
    for name, (kind, address, size, bits, bit, skip) in LAYOUTS.items():
        fields = {"Name": name, "Type": kind, "Address": str(address), "ArraySize": str(size),
                  "BitAddress": str(bit), "ArraySkip": str(skip),
                  "DefaultValue": " ".join(map(str, DEFAULTS.get(name, [0] * size)))}
        if kind == "int":
            fields.update(BitSize=str(bits), MinValue="0", MaxValue=str((1 << bits) - 1))
        parameters[name] = ParameterSpec(name, kind, "literal-iope-fixture.xml", fields)
    for name, address in (("UnitAddress", 0x20), ("AreaGroupAddress", 0x68)):
        parameters[name] = ParameterSpec(name, "int", "literal-iope-fixture.xml", {
            "Name": name, "Type": "int", "Address": str(address), "DefaultValue": "255"})
    return UnitSpec(unit_type + ".xml", {"Type": unit_type}, ("literal-iope-fixture.xml",), parameters)


def session(unit_type="IOPE2C4"):
    result = Session(fixture(unit_type))
    result.unit_type, result.firmware, result.catalog_number = unit_type, FIRMWARE, PROFILES[unit_type].catalog_number
    return result


def values(unit_type="IOPE2C4", **overrides):
    result = {name: " ".join(map(str, DEFAULTS.get(name, [0] * layout[2]))) for name, layout in LAYOUTS.items()}
    result.update({k: " ".join(map(str, v)) for k, v in overrides.items()})
    return result


class IopeRulesTest(unittest.TestCase):
    def editor(self, unit_type="IOPE2C4"):
        return IopeSettings(fixture(unit_type))

    def test_profiles_firmware_and_spec_gates(self):
        self.assertEqual({t: (p.sensors, p.auxiliaries, p.outputs, p.relays) for t, p in PROFILES.items()},
                         {"IOPE1R1": (1, 1, 1, 1), "IOPE2R2": (2, 2, 2, 2), "IOPE2C4": (2, 2, 4, 2)})
        self.assertIsNone(profile_refusal("IOPE2R2", "1.0.00"))
        self.assertIsNone(profile_refusal("IOPE1R1", "1.2.99"))
        for unit_type, firmware in (("IOPE2R2", "1.3.00"), ("IOPE2R2", "0.9.99"), ("SENPILL", "1.2.00")):
            self.assertIsNotNone(profile_refusal(unit_type, firmware))
        with self.assertRaisesRegex(PPEditError, "Use IOPE1R1.xml"):
            IopeSettings(fixture("IOPE2R2"), "IOPE1R1")
        with self.assertRaisesRegex(PPEditError, "Only IOPE"):
            IopeSettings(fixture("IOPE2R2"), "RELDN4")

    def test_global_tab_domains(self):
        editor = self.editor()
        plan = editor.plan(values(), long_press=63, ramp_rates={"global1": 0, "scene": "1020 secs"},
                           status_report=255, debounce=6, recall_percents={1: 50}, recall_levels={4: 7},
                           clock_gen=False, burden=True)
        self.assertEqual(dict(plan.changes), {
            "LongPressTime": (63,), "RampRateA": (0,), "RampRateS": (15,), "StatusReportInterval": (255,),
            "SensorOccupancyDebounce": (6,), "Memory1": (127,), "Memory4": (7,), "ClockGenEnable": (0,),
            "Burden": (1,)})
        for options, message in (({"long_press": 5}, "6..63"), ({"status_report": 2}, "3..255"),
                                 ({"debounce": 7}, "0..6"), ({"ramp_rates": {"global4": 1}}, "global1"),
                                 ({"recall_percents": {1: 101}}, "0..100"),
                                 ({"recall_percents": {1: 1}, "recall_levels": {1: 1}}, "either"),
                                 ({"recall_levels": {5: 1}}, "Global")):
            with self.subTest(options=options), self.assertRaisesRegex(PPEditError, message):
                editor.plan(values(), **options)

    def test_sensor_enable_and_state_recovery_transforms(self):
        editor = self.editor()
        plan = editor.plan(values(), sensors={1: {"disabled_when": "on", "enable_group": 200,
                                                  "enable_application": "primary", "state_recovery": "restore"},
                                              2: {"state_recovery": "enabled", "enable_group": None}})
        self.assertEqual(dict(plan.changes), {
            "Sensor1Enabled": (1,), "Sensor1EnableGroup": (200,), "Sensor1EnableGroupInEnableControlApp": (0,),
            "Sensor1EnableStateStoreEnabled": (1,), "Sensor2EnabledStartup": (1,)})
        both = values(Sensor1EnableStateStoreEnabled=[1], Sensor1EnabledStartup=[1])
        view = editor.show(both)["sensors"][0]
        self.assertEqual((view["state_recovery"], view["toolkit_save_rewrites_state_bits"]), ("restore", True))
        plan = editor.plan(both, sensors={1: {"state_recovery": "disabled"}})
        self.assertEqual(dict(plan.changes), {"Sensor1EnableStateStoreEnabled": (0,), "Sensor1EnabledStartup": (0,)})
        with self.assertRaisesRegex(PPEditError, "Sensor must be 1..1"):
            self.editor("IOPE1R1").plan(values("IOPE1R1"), sensors={2: {"disabled_when": "off"}})
        with self.assertRaisesRegex(PPEditError, "0..254"):
            editor.plan(values(), sensors={1: {"enable_group": 255}})

    def test_power_up_broadcast_eligibility_and_save_clearing(self):
        editor = self.editor()
        self.assertEqual(editor.broadcast_eligible(editor.snapshot(values())), {1})
        view = editor.show(values())["power_up_broadcast"]
        self.assertEqual(view, {"blocks": [2, 3], "eligible_blocks": [1], "toolkit_save_clears": [2, 3]})
        plan = editor.plan(values(), enable_broadcast=[1])
        self.assertEqual(plan.changes["GroupAssertOnPowerup"], (1,))
        self.assertIn("GroupAssertOnPowerup:cleared-ineligible", plan.details["derived"])
        for block in (2, 3):
            with self.subTest(block=block), self.assertRaisesRegex(PPEditError, "no group or no bistable"):
                editor.plan(values(), enable_broadcast=[block])
        # Auxiliary 2 is only counted where the unit has it.
        mom = values(BistableAuxiliary1=[0], BistableAuxiliary2=[1])
        self.assertEqual(editor.broadcast_eligible(editor.snapshot(mom)), {2})
        one = self.editor("IOPE1R1")
        self.assertEqual(one.broadcast_eligible(one.snapshot(values("IOPE1R1", BistableAuxiliary1=[0],
                                                                     BistableAuxiliary2=[1]))), set())
        with self.assertRaisesRegex(PPEditError, "both"):
            editor.plan(values(), enable_broadcast=[1], disable_broadcast=[1])

    def test_output_recovery_and_level_store_rule(self):
        editor = self.editor()
        plan = editor.plan(values(), outputs={4: {"level_store": False, "recovery_percent": 30}})
        self.assertEqual(plan.changes["LightLevelOutput"][3], 76)
        plan = editor.plan(values(), outputs={1: {"level_store": True}})
        self.assertEqual((plan.changes["LevelStoreEnable"][0], plan.changes["LightLevelOutput"][0]), (1, 255))
        stored = values(LevelStoreEnable=[1, 0, 0, 0])
        with self.assertRaisesRegex(PPEditError, "255"):
            editor.plan(stored, outputs={1: {"recovery_level": 3}})
        with self.assertRaisesRegex(PPEditError, "shared"):
            editor.plan(values(OutputGroupAddress=[20, 20, 22, 23]), outputs={1: {"recovery_level": 3}})
        with self.assertRaisesRegex(PPEditError, "Output channel must be 1..2"):
            self.editor("IOPE2R2").plan(values("IOPE2R2"), outputs={3: {"recovery_level": 1}})
        self.assertEqual([row["relay"] for row in editor.show(values())["outputs"]], [True, True, False, False])

    def test_block_timers(self):
        self.assertEqual(timer_seconds("18:12:15"), 65535)
        self.assertEqual(timer_seconds(0), 0)
        for bad in (65536, -1, "18:12:16", "1:60:00", True):
            with self.subTest(bad=bad), self.assertRaises(PPEditError):
                timer_seconds(bad)
        plan = self.editor().plan(values(), block_timers={1: 0, BLOCKS: "0:05:01"})
        self.assertEqual((plan.changes["TimerHighByte"][0], plan.changes["TimerLowByte"][0]), (0, 0))
        self.assertEqual((plan.changes["TimerHighByte"][7], plan.changes["TimerLowByte"][7]), (1, 45))
        self.assertEqual(self.editor().show(values())["block_timers"][0]["seconds"], 300)

    def test_apply_readback_stale_rollback_and_plan_document(self):
        editor, pp = self.editor(), session()
        pp.set("UnitAddress", "12")
        plan = editor.plan(pp.values(), identity=("IOPE2C4", FIRMWARE, None), long_press=40)
        document = json.loads(json.dumps(plan.as_dict()))
        self.assertEqual((document["format"], document["saved"]), (FORMAT, False))
        result = editor.apply(pp, plan_from_dict(document))
        self.assertTrue(result["verified"])
        self.assertEqual(pp.values()["UnitAddress"], "12")
        with self.assertRaisesRegex(PPEditError, "changed since"):
            editor.apply(pp, plan_from_dict(document))
        pp.firmware = "1.3.00"
        with self.assertRaisesRegex(PPEditError, "not an admitted"):
            editor.configure(pp, long_press=41)
        pp.firmware = FIRMWARE

        class Failing(Session):
            def set(self, name, value):
                if name == "Memory2":
                    raise RuntimeError("uncertain reply")
                super().set(name, value)
        failing = Failing(fixture("IOPE2C4"))
        failing.unit_type, failing.firmware = "IOPE2C4", FIRMWARE
        before = failing.values()
        with self.assertRaises(PPApplyError):
            editor.configure(failing, recall_levels={1: 1, 2: 2})
        self.assertEqual(failing.values(), before)
        with self.assertRaisesRegex(PPEditError, "Expected a"):
            plan_from_dict({"format": "other"})


def write_spec(folder, unit_type):
    spec = fixture(unit_type)
    root = ET.Element("UnitSpecification")
    ET.SubElement(root, "Type").text = unit_type
    parameters = ET.SubElement(root, "Parameters")
    for parameter in spec.parameters.values():
        node = ET.SubElement(parameters, "Param")
        for key, value in parameter.fields.items():
            ET.SubElement(node, key).text = value
    ET.ElementTree(root).write(Path(folder) / spec.filename, encoding="utf-8", xml_declaration=True)


def cli(test, *args, status=0):
    result = subprocess.run([sys.executable, "-m", "cbus_toolkit", *map(str, args)],
                            capture_output=True, text=True, timeout=90)
    test.assertEqual(result.returncode, status, result.stdout + result.stderr)
    return json.loads(result.stdout or result.stderr)


class IopeCliTest(unittest.TestCase):
    def test_offline_show_plan_and_refusals(self):
        with tempfile.TemporaryDirectory() as folder:
            write_spec(folder, "IOPE2C4")
            snapshot = Path(folder) / "iope.json"
            snapshot.write_text(json.dumps({"format": "cbus-cli-parameters-v1", "unit_type": "IOPE2C4",
                                            "firmware": FIRMWARE, "catalog_number": "5752PP/2R/2D",
                                            "parameters": values()}))
            base = ("iope-settings", "--spec-dir", folder)
            self.assertEqual(cli(self, *base, "show", snapshot)["unit_type"], "IOPE2C4")
            plan = cli(self, *base, "plan", snapshot, "--long-press", "40", "--ramp-rate", "scene=8 secs",
                       "--sensor", "2", "--state-recovery", "restore", "--enable-group", "none",
                       "--output", "3", "--recovery-percent", "100", "--block-timer", "2=1:00:00",
                       "--enable-broadcast-block", "1", "--recall-percent", "2=0")
            self.assertEqual(plan["firmware"], FIRMWARE)
            self.assertEqual(plan["changes"]["RampRateS"], [2])
            self.assertEqual(plan["changes"]["TimerHighByte"][1], 3600 >> 8)
            self.assertEqual(plan["changes"]["LightLevelOutput"][2], 255)
            self.assertEqual(plan["changes"]["Memory2"], [0])
            for args, message in ((("--state-recovery", "restore"), "--sensor"),
                                  (("--sensor", "3", "--disabled-when", "on"), "Sensor must"),
                                  (("--enable-broadcast-block", "2"), "bistable")):
                with self.subTest(args=args):
                    self.assertIn(message, cli(self, *base, "plan", snapshot, *args, status=1)["error"])
            bare = Path(folder) / "bare.json"
            bare.write_text(json.dumps(values()))
            self.assertIn("--unit-type", cli(self, *base, "show", bare, status=1)["error"])
            newer = Path(folder) / "newer.json"
            newer.write_text(snapshot.read_text().replace(FIRMWARE, "1.3.00"))
            self.assertIn("1.0.00..1.2.99", cli(self, *base, "show", newer, status=1)["error"])


# (unit type, catalogue number) created in the owned native database.
NATIVE_TYPES = tuple((t, p.catalog_number) for t, p in PROFILES.items())


def raw_byte(pp, address):
    return int(pp.get_raw_data(address, 1).lines[-1].split("RawData=", 1)[1], 16)


@unittest.skipUnless(NATIVE, NATIVE_REASON)
class IopeNativeTest(unittest.TestCase):
    """Owned C-Gate PP sessions on closed database units; no physical controller."""

    def check(self, pp, editor, case, report, label, expect=(), **options):
        before = pp.values()
        result = editor.configure(pp, **options)
        self.assertTrue(result["verified"])
        after = pp.values()
        unrelated = sorted(n for n in before if n not in LAYOUTS)
        self.assertEqual({n: after[n] for n in unrelated}, {n: before[n] for n in unrelated})
        for name in LAYOUTS:
            if name not in result["changes"]:
                self.assertEqual(after[name], before[name], (label, name))
        for address, mask, value in expect:
            self.assertEqual(raw_byte(pp, address) & mask, value, (label, hex(address)))
            case["raw_byte_assertions"] += 1
        case["positive"].append(label)
        case["unrelated_parameters_preserved"] = len(unrelated)
        report["edits"] += 1

    def refuse(self, pp, editor, case, label, pattern, **options):
        before = pp.values()
        with self.assertRaisesRegex(PPEditError, pattern):
            editor.configure(pp, **options)
        self.assertEqual(pp.values(), before)
        case["invalid"].append(label)

    def exercise(self, client, network, address, unit_type, catalog, report):
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        profile = PROFILES[unit_type]
        editor = IopeSettings(self.store.load(unit_type + ".xml"))
        NativeDatabase(client).create_unit(network, address, "Iope" + str(address), unit_type, FIRMWARE,
                                           catalog_number=catalog)
        path = f"/db{network}/p/{address}"
        case = {"unit_type": unit_type, "catalog_number": catalog, "firmware": FIRMWARE, "positive": [],
                "boundary": [], "invalid": [], "raw_byte_assertions": 0}
        n = profile.sensors
        with Programmer(client).load(network, path) as pp:
            self.assertEqual((pp.unit_type, pp.firmware), (unit_type, FIRMWARE))
            # Neighbour bits share bytes 0x30, 0x3E, 0x6C and 0x6E.
            pp.set("Sensor1EnableMultipleSensorHeads", "1")
            pp.set("EEPROMLevelStore", "1")
            pp.set("SecondCorridorLinkEnable", "1")
            pp.set("LogicLevelStoreEnable", "1 0 1 0")
            pp.set("InputGroupAddress", "30 31 255 255 255 255 255 255")
            pp.set("Auxiliary1BlockAllocation", "1 0 0 0 0 0 0 0")
            baseline = pp.values()
            self.check(pp, editor, case, report, "global", long_press=63, ramp_rates={"global1": 0, "global2": 15,
                       "global3": 7, "scene": 1}, status_report=255, debounce=6,
                       recall_percents={1: 100, 2: 0}, recall_levels={3: 1, 4: 254}, clock_gen=False, burden=True,
                       expect=((0x31, 0x3F, 63), (0x32, 0xFF, 0x70), (0x33, 0xFF, 0x1F), (0x6A, 0xFF, 255),
                               (0x6C, 0x70, 0x60), (0x10, 0xFF, 255), (0x11, 0xFF, 0), (0x12, 0xFF, 1),
                               (0x13, 0xFF, 254), (0x3E, 0x43, 0x42)))
            self.check(pp, editor, case, report, "global-minimum", long_press=6, status_report=3, debounce=0,
                       expect=((0x31, 0x3F, 6), (0x6A, 0xFF, 3), (0x6C, 0x70, 0)))
            case["boundary"] += ["long-press-6-63", "status-report-3-255", "debounce-0-6", "recall-0-255"]
            self.check(pp, editor, case, report, "sensor-enable", sensors={n: {
                "disabled_when": "on", "enable_group": 254, "enable_application": "primary",
                "state_recovery": "restore"}},
                expect=((0x3E, 1 << (1 + n), 1 << (1 + n)), (0x60 + n, 0xFF, 254), (0x30, 1 << (5 + n), 0),
                        (0x3E, 1 << (3 + n), 1 << (3 + n)), (0x1C, 1 << (n - 1), 0), (0x30, 0x10, 0x10)))
            self.check(pp, editor, case, report, "sensor-state-enabled", sensors={n: {
                "state_recovery": "enabled", "enable_group": None, "enable_application": "enable-control",
                "disabled_when": "off"}},
                expect=((0x3E, 1 << (3 + n), 0), (0x1C, 1 << (n - 1), 1 << (n - 1)), (0x60 + n, 0xFF, 255),
                        (0x30, 1 << (5 + n), 1 << (5 + n)), (0x3E, 1 << (1 + n), 0)))
            self.refuse(pp, editor, case, "sensor-high", "Sensor must", sensors={n + 1: {"disabled_when": "on"}})
            self.refuse(pp, editor, case, "enable-group-255", "0..254", sensors={1: {"enable_group": 255}})
            # Power-up broadcast: block 1 grouped + aux1 bistable; block 2 grouped, not bistable.
            self.refuse(pp, editor, case, "broadcast-momentary", "bistable", enable_broadcast=[1])
            pp.set("BistableAuxiliary1", "1")
            self.check(pp, editor, case, report, "broadcast", enable_broadcast=[1], expect=((0x1D, 0xFF, 1),))
            self.refuse(pp, editor, case, "broadcast-ungrouped-or-momentary", "bistable", enable_broadcast=[2])
            self.check(pp, editor, case, report, "broadcast-off", disable_broadcast=[1], expect=((0x1D, 0xFF, 0),))
            last = profile.outputs
            self.check(pp, editor, case, report, "output-recovery", outputs={last: {
                "level_store": False, "recovery_percent": 50}},
                expect=((0x6E, 1 << (last - 1), 0), (0x08 + last - 1, 0xFF, 127), (0x6E, 0x50, 0x50)))
            self.check(pp, editor, case, report, "output-level-store-255", outputs={1: {"level_store": True}},
                       expect=((0x6E, 1, 1), (0x08, 0xFF, 255)))
            self.refuse(pp, editor, case, "output-level-with-store", "255", outputs={1: {"recovery_level": 3}})
            self.refuse(pp, editor, case, "output-high", "Output channel", outputs={last + 1: {"recovery_level": 1}})
            self.check(pp, editor, case, report, "block-timers", block_timers={1: 0, 8: "18:12:15"},
                       expect=((0x40, 0xFF, 0), (0x48, 0xFF, 0), (0x47, 0xFF, 255), (0x4F, 0xFF, 255)))
            case["boundary"].append("timer-0-65535")
            self.refuse(pp, editor, case, "timer-overflow", "65535", block_timers={1: 65536})
            self.refuse(pp, editor, case, "long-press-5", "6..63", long_press=5)
            after = pp.values()
            for name in ("Sensor1EnableMultipleSensorHeads", "EEPROMLevelStore", "SecondCorridorLinkEnable",
                         "LogicLevelStoreEnable"):
                self.assertEqual(after[name], baseline[name])
            expected = editor.snapshot(after)
            pp.save_to_source()
        client.command("PROJECT SAVE " + network.split("/")[2])
        with Programmer(client).load(network, path) as pp:
            self.assertEqual(editor.snapshot(pp.values()), expected)
            self.assertEqual(pp.values(), after)
        case["save_reload_passed"] = True
        report["types"].append(case)
        report["raw_byte_assertions"] += case["raw_byte_assertions"]

    def refuse_type(self, client, network, address, report):
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        # Native C-Gate has no IOPE spec beyond the catalogued revisions, so the
        # refusal is an admitted-firmware unit loaded against another schema.
        NativeDatabase(client).create_unit(network, address, "Iope" + str(address), "IOPE2R2", "1.0.00",
                                           catalog_number="5752PP/2R")
        editor = IopeSettings(self.store.load("IOPE2C4.xml"))
        with Programmer(client).load(network, f"/db{network}/p/{address}") as pp:
            before = pp.values()
            with self.assertRaisesRegex(PPEditError, "differs"):
                editor.configure(pp, long_press=10)
            self.assertEqual(pp.values(), before)
        report["refused"].append({"unit_type": "IOPE2R2", "firmware": "1.0.00", "schema": "IOPE2C4.xml",
                                  "values_unchanged": True})

    def test_admitted_types_raw_bytes_preservation_save_reload_and_refusals(self):
        from cbus_toolkit.cgate import CGateClient
        self.store = UnitSpecStore(os.environ["CBUS_UNITSPEC_DIR"])
        report = {"format": "cbus-iope-settings-acceptance-v1", "backend": os.environ.get(
            "CBUS_NATIVE_SERVICE_BACKEND", "host"), "scope": (
            "Toolkit source-grounded IOPE Global, sensor enable, power failure and block timer settings "
            "through native PP and a closed database; no physical controller"),
            "types": [], "refused": [], "edits": 0, "raw_byte_assertions": 0, "passed": False,
            "physical_hardware_verified": False}
        with native_endpoint() as (host, port), CGateClient(host, port, timeout=30) as client, \
                closed_network_project(client, "IO") as project:
            network = f"//{project}/254"
            for index, (unit_type, catalog) in enumerate(NATIVE_TYPES):
                with self.subTest(unit_type=unit_type):
                    self.exercise(client, network, 30 + index, unit_type, catalog, report)
            self.refuse_type(client, network, 40, report)
            self.run_cli(host, port, project, network)
            report["cli_passed"] = True
        report["passed"] = len(report["types"]) == len(NATIVE_TYPES) and len(report["refused"]) == 1
        self.assertTrue(report["passed"])
        if os.environ.get("CBUS_IOPE_REPORT"):
            Path(os.environ["CBUS_IOPE_REPORT"]).write_text(json.dumps(report, indent=2) + "\n")

    def run_cli(self, host, port, project, network):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        with CGateClient(host, port, timeout=30) as client:
            client.command("PROJECT USE " + project)
            NativeDatabase(client).create_unit(network, 50, "IopeCli", "IOPE2C4", FIRMWARE,
                                               catalog_number="5752PP/2R/2D")
            client.command("PROJECT SAVE " + project)
        prefix = ("cgate", "--host", host, "--port", port, "--timeout", "20", "unit", "--lock-address", network,
                  "--source", "/db" + network + "/p/50")
        options = ("--long-press", "30", "--sensor", "1", "--state-recovery", "restore", "--block-timer", "3=90")
        with tempfile.TemporaryDirectory() as folder:
            exported = Path(folder) / "iope.json"
            original = cli(self, *prefix, "show")
            cli(self, *prefix, "export", exported)
            plan = cli(self, "iope-settings", "plan", exported, *options)
            preview = cli(self, *prefix, "--dry-run", "iope-settings", *options)
            self.assertEqual(plan["changes"], preview["changes"])
            self.assertFalse(preview["saved"])
            self.assertEqual(cli(self, *prefix, "show"), original)
            self.assertEqual(cli(self, *prefix, "iope-settings", "--show")["global"]["long_press"], 25)
            plan_file = Path(folder) / "plan.json"
            plan_file.write_text(json.dumps(plan))
            applied = cli(self, *prefix, "iope-settings", "--plan", plan_file)
            self.assertTrue(applied["saved"])
            self.assertEqual(applied["parameters"]["UnitName"], original["UnitName"])
            self.assertIn("changed since", cli(self, *prefix, "iope-settings", "--plan", plan_file, status=1)["error"])
            self.assertEqual(cli(self, *prefix, "iope-settings", "--show")["block_timers"][2]["seconds"], 90)


class IopeReceiptTest(unittest.TestCase):
    def test_receipts_are_sanitized_and_cover_every_type(self):
        review = json.loads(REVIEW.read_text())
        self.assertEqual(review["binding"]["dialog_factory"], "TUnitDialogFactory.RegisterUnitDialog")
        self.assertEqual(set(review["binding"]["unit_types"]), set(PROFILES))
        self.assertIsNone(review["binding"]["node_manager"])
        for row in review["controls"]:
            self.assertTrue(row["evidence"], row["control"])
        native = json.loads(RECEIPT.read_text())
        self.assertTrue(native["passed"])
        self.assertFalse(native["physical_hardware_verified"])
        self.assertEqual({row["unit_type"] for row in native["types"]}, set(PROFILES))
        text = RECEIPT.read_text() + REVIEW.read_text()
        self.assertNotIn("Clipsal", text)


if __name__ == "__main__":
    unittest.main()
