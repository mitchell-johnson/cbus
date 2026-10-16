"""Custom micro-functions, power-up broadcast and Neo indicator editors."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cbus_toolkit.extended_macros import ExtendedKeys, LAYOUTS, PROFILES
from cbus_toolkit.input_power_up import (COUPLER_LAYOUTS, BROADCAST_LAYOUTS, CouplerPowerUp, KeyPowerUpBroadcast,
                                         power_up_editor)
from cbus_toolkit.macros import ClassicKeys, MacroError, STAGES, _READ_FIELDS
from cbus_toolkit.neo_indicators import (FAMILIES, NeoIndicatorOptions, NeoIndicatorStyles, OPTION_LAYOUTS,
                                         STYLE_LAYOUTS, brightness_to_percent, percent_to_brightness)
from cbus_toolkit.pp_editor import PPApplyError, PPEditError, parse_values
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec, UnitSpecStore
import test_macros as classic_tests


DEFAULTS = {"GroupAssertOnPowerup": "0", "BistableSwitchBlock": "0",
            "BlockAllocation": "1 2 4 8 16 32 64 128", "GAVBroadcastFlag": "255",
            "IndicatorBrightness": "255", "GroupAddress": "255 " * 8 + "255", "IndicatorPressedLevel": "15",
            "TimerDuration": "15", "EnableNightlight": "0", "DisableTimerFlash": "0",
            "IDBacklightIllumination": "0", "FirstKeyThrowAway": "0", "EnableNightlightOnPCx": "0",
            "EnableNightlightOnPA6": "0", "IndicatorFunction": "2 2 2 2 2 2 2 2", "PrimaryColour": "1 1 1 1 1 1 1 1"}


def fixture(filename, unit_type, layouts):
    parameters = {}
    for name, (kind, address, count, bits, offset, skip) in layouts.items():
        fields = {"Name": name, "Type": kind, "Address": str(address), "ArraySize": str(count), "BitSize": str(bits),
                  "BitAddress": str(offset), "ArraySkip": str(skip), "DefaultValue": DEFAULTS[name]}
        parameters[name] = ParameterSpec(name, kind, "fixture.xml", fields)
    return UnitSpec(filename, {"Type": unit_type}, ("fixture.xml",), parameters)


class PowerUpTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture("BCN4B.xml", "BCN4B", COUPLER_LAYOUTS)
        self.editor = CouplerPowerUp(self.spec)

    def test_only_bistable_key_blocks_can_broadcast_and_whole_byte_is_rebuilt(self):
        current = dict(self.spec.defaults(), BistableSwitchBlock="5", BlockAllocation="3 2 12 8 16 32 64 128",
                       GroupAssertOnPowerup="0x88")
        # Keys 1 and 3 are bistable; they reference blocks 1, 2, 3 and 4.
        self.assertEqual(self.editor.bistable_blocks(self.editor.snapshot(current)), {1, 2, 3, 4})
        plan = self.editor.plan(current, enable=[1, 3])
        self.assertEqual(plan.changes["GroupAssertOnPowerup"], (0b1101,))
        self.assertEqual(plan.as_dict()["cleared_non_bistable"], [8])
        with self.assertRaisesRegex(PPEditError, "not used by a bistable key"):
            self.editor.plan(current, enable=[5])
        # Key 5 exists in the array but not on a four-input coupler.
        with self.assertRaisesRegex(PPEditError, "not used by a bistable key"):
            self.editor.plan(dict(current, BistableSwitchBlock="16"), enable=[5])
        self.assertEqual(self.editor.plan(current, disable=[4]).changes["GroupAssertOnPowerup"], (0,))
        for options in ({"enable": [0]}, {"enable": [9]}, {"enable": [1], "disable": [1]}, {"enable": "1"}):
            with self.subTest(options=options), self.assertRaises(PPEditError):
                self.editor.plan(current, **options)

    def test_apply_verifies_type_schema_staleness_and_rolls_back(self):
        session = classic_tests.Session(self.spec)
        session.set("BistableSwitchBlock", "1")
        session.calls.clear()
        plan = self.editor.plan(session.values(), enable=[1])
        self.assertTrue(self.editor.apply(session, plan)["verified"])
        self.assertEqual(session.calls, [("GroupAssertOnPowerup", "1")])
        with self.assertRaisesRegex(PPEditError, "changed since"):
            self.editor.apply(session, plan)
        other = classic_tests.Session(fixture("BCN2B.xml", "BCN2B", COUPLER_LAYOUTS))
        with self.assertRaisesRegex(PPEditError, "differs"):
            self.editor.apply(other, plan)
        session = classic_tests.Session(self.spec)
        session.set("BistableSwitchBlock", "1")
        session.failure = "GroupAssertOnPowerup"
        with self.assertRaises(PPApplyError) as caught:
            self.editor.apply(session, self.editor.plan(session.values(), enable=[1]))
        self.assertEqual(caught.exception.rollback_errors, ())
        self.assertEqual(session.values()["GroupAssertOnPowerup"], "0")

    def test_key_broadcast_flag_and_refusals(self):
        spec = fixture("KEYBC4.xml", "KEYBC4", BROADCAST_LAYOUTS)
        editor = KeyPowerUpBroadcast(spec)
        self.assertEqual(editor.plan(spec.defaults(), broadcast=True).changes["GAVBroadcastFlag"], (0,))
        self.assertEqual(editor.plan({"GAVBroadcastFlag": "0"}, broadcast=False).changes["GAVBroadcastFlag"], (255,))
        with self.assertRaises(PPEditError):
            editor.plan(spec.defaults(), broadcast=1)
        self.assertIsInstance(power_up_editor(spec), KeyPowerUpBroadcast)
        for filename, unit_type in (("KEY4.xml", "KEY4"), ("IOPE2R2.xml", "IOPE2R2"), ("KEYM4.xml", "KEYM4")):
            with self.subTest(unit_type=unit_type), self.assertRaises(PPEditError):
                power_up_editor(fixture(filename, unit_type, BROADCAST_LAYOUTS))


class NeoIndicatorTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture("KEYM4.xml", "KEYM4", OPTION_LAYOUTS)
        self.options = NeoIndicatorOptions(self.spec)

    def test_brightness_percent_conversion_matches_toolkit_integer_maths(self):
        table = {0: 4, 1: 5, 2: 6, 3: 7, 4: 10, 50: 127, 99: 252, 100: 255}
        for percent, value in table.items():
            self.assertEqual(percent_to_brightness(percent), value)
        self.assertTrue(all(4 <= percent_to_brightness(p) <= 255 for p in range(101)))
        self.assertEqual(brightness_to_percent(127), 50)
        self.assertIsNone(brightness_to_percent(8))

    def test_brightness_sources_and_group(self):
        current = self.spec.defaults()
        self.assertEqual(self.options.plan(current, brightness="fixed", brightness_percent=50).changes,
                         {"IndicatorBrightness": (127,)})
        plan = self.options.plan(current, brightness="group", brightness_group=12)
        self.assertEqual(plan.changes["IndicatorBrightness"], (0,))
        self.assertEqual(plan.changes["GroupAddress"], (255,) * 8 + (12,))
        self.assertEqual(plan.as_dict()["brightness"], {"source": "group", "percent": None, "group": 12})
        self.assertEqual(self.options.plan(current, brightness="first_block").changes["IndicatorBrightness"], (1,))
        for options in ({"brightness": "fixed"}, {"brightness": "fixed", "brightness_percent": 101},
                        {"brightness": "group"}, {"brightness": "group", "brightness_group": 256},
                        {"brightness_percent": 5}, {"brightness": "first_block", "brightness_group": 1},
                        {"brightness": "other"}):
            with self.subTest(options=options), self.assertRaises(PPEditError):
                self.options.plan(current, **options)

    def test_key_press_nightlight_dependencies_and_family_bit(self):
        current = self.spec.defaults()
        plan = self.options.plan(current, key_press_level=9, key_press_seconds=4, nightlight=True,
                                 ignore_first_key_press=True, timer_flash=False, id_backlight=True)
        self.assertEqual(plan.changes, {"IndicatorPressedLevel": (9,), "TimerDuration": (4,),
                                        "EnableNightlightOnPA6": (1,), "FirstKeyThrowAway": (1,),
                                        "DisableTimerFlash": (1,), "IDBacklightIllumination": (1,)})
        off = self.options.plan(dict(current, EnableNightlightOnPCx="1", EnableNightlight="1"), nightlight=False)
        self.assertEqual(off.changes, {"EnableNightlight": (0,), "EnableNightlightOnPCx": (0,)})
        with self.assertRaisesRegex(PPEditError, "key-press brightening"):
            self.options.plan(current, key_press_seconds=0, nightlight=True)
        with self.assertRaisesRegex(PPEditError, "nightlight enabled"):
            self.options.plan(current, ignore_first_key_press=True)
        with self.assertRaisesRegex(PPEditError, "key_press_level"):
            self.options.plan(current, key_press_seconds=3)
        with self.assertRaisesRegex(PPEditError, "duration"):
            self.options.plan(dict(current, TimerDuration="0"), key_press_level=3)
        # Disabling brightening keeps the stored level, as the wizard does.
        self.assertEqual(self.options.plan(current, key_press_seconds=0).changes, {"TimerDuration": (0,)})
        saturn = NeoIndicatorOptions(fixture("KEYB4.xml", "KEYB4", OPTION_LAYOUTS))
        self.assertEqual(saturn.plan(current, nightlight=True).changes, {"EnableNightlightOnPCx": (1,)})

    def test_styles_colours_and_family_eligibility(self):
        spec = fixture("KEYM4.xml", "KEYM4", STYLE_LAYOUTS)
        styles = NeoIndicatorStyles(spec)
        plan = styles.plan(spec.defaults(), colour="blue", style="status_dual")
        self.assertEqual(plan.changes, {"PrimaryColour": (0,) * 8, "IndicatorFunction": (3,) * 8})
        self.assertEqual(plan.as_dict()["off_colour"], "orange")
        self.assertEqual(styles.plan(spec.defaults(), colour="orange").changes, {})
        with self.assertRaises(PPEditError):
            styles.plan(spec.defaults(), colour="red")
        self.assertTrue(NeoIndicatorStyles(fixture("KEYV2.xml", "KEYV2", STYLE_LAYOUTS)).plan(
            spec.defaults(), colour="blue").as_dict()["avanti_colour_note"])
        for filename, unit_type in (("KEYA3.xml", "KEYA3"), ("KEYC4.xml", "KEYC4")):
            with self.subTest(unit_type=unit_type), self.assertRaisesRegex(PPEditError, "excludes"):
                NeoIndicatorStyles(fixture(filename, unit_type, STYLE_LAYOUTS))
        with self.assertRaisesRegex(PPEditError, "excludes classic"):
            NeoIndicatorOptions(fixture("KEYC4.xml", "KEYC4", OPTION_LAYOUTS))
        NeoIndicatorOptions(fixture("KEYA3.xml", "KEYA3", OPTION_LAYOUTS))
        self.assertEqual(set(FAMILIES), {profile[0] for profile in PROFILES.values()})

    def test_bit_values_accept_native_boolean_text(self):
        self.assertEqual(parse_values("true false 0x1 $0F 7"), (1, 0, 1, 15, 7))
        with self.assertRaises(PPEditError):
            parse_values("maybe")


def run_cli(test, *args, status=0, prefix=()):
    # Keep the selected source or installed-wheel environment. Forcing src/
    # here would silently bypass the fresh-wheel gate in CLI subprocesses.
    env = dict(os.environ)
    process = subprocess.run([sys.executable, "-m", "cbus_toolkit", *map(str, prefix), *map(str, args)],
                             text=True, capture_output=True, env=env)
    test.assertEqual(process.returncode, status, process.stderr + process.stdout)
    return json.loads(process.stdout if process.stdout else process.stderr)


class OfflineCliTests(unittest.TestCase):
    def test_micro_function_domain_listing(self):
        listing = run_cli(self, "keys", "micro-functions")
        self.assertEqual(listing["stages"], list(STAGES))
        self.assertEqual([item["code"] for item in listing["micro_functions"]],
                         [0, 1, 2, 4, 5, 6, 12, 9, 10, 11, 3, 13, 15, 14, 7, 8])

    @unittest.skipUnless(os.environ.get("CBUS_UNITSPEC_DIR"), "Set CBUS_UNITSPEC_DIR for vendor schemas")
    def test_offline_plans_for_every_new_editor(self):
        directory = os.environ["CBUS_UNITSPEC_DIR"]
        with tempfile.TemporaryDirectory() as folder:
            def snapshot(spec, **overrides):
                values = run_cli(self, "unit-schema", "--spec-dir", directory, "defaults", spec)
                values.update(overrides)
                path = Path(folder) / (spec + ".json")
                path.write_text(json.dumps(values))
                return path
            keys = ("keys", "--spec-dir", directory)
            plan = run_cli(self, *keys, "custom-plan", "KEY4.xml", snapshot("KEY4.xml"), "--key", 2, "--jp", "on", "--lr", 15)
            self.assertEqual(plan["preset"]["codes"]["JPCommand"], 13)
            self.assertFalse(plan["saved"])
            plan = run_cli(self, *keys, "neo-custom-plan", "KEYM4.xml", snapshot("KEYM4.xml"), "--key", 4, "--sr", "0x3")
            self.assertEqual(plan["changes"]["SRCommand"][3], 3)
            self.assertIn("Toolkit offers", run_cli(self, *keys, "custom-plan", "KEY4.xml", snapshot("KEY4.xml"),
                                                    "--key", 1, "--jp", 16, status=1)["error"])
            plan = run_cli(self, *keys, "power-up-plan", "BCN4B.xml",
                           snapshot("BCN4B.xml", BistableSwitchBlock="2"), "--enable-block", 2)
            self.assertEqual(plan["changes"]["GroupAssertOnPowerup"], [2])
            plan = run_cli(self, *keys, "power-up-plan", "KEYBC4.xml", snapshot("KEYBC4.xml"), "--broadcast")
            self.assertEqual(plan["changes"]["GAVBroadcastFlag"], [0])
            plan = run_cli(self, *keys, "neo-indicator-plan", "KEYM4.xml", snapshot("KEYM4.xml"),
                           "--brightness", "fixed", "--brightness-percent", 50, "--no-timer-flash")
            self.assertEqual(plan["changes"], {"IndicatorBrightness": [127], "DisableTimerFlash": [1]})
            plan = run_cli(self, *keys, "neo-style-plan", "KEYB4.xml", snapshot("KEYB4.xml"), "--colour", "blue",
                           "--style", "always_on")
            self.assertEqual(plan["changes"]["IndicatorFunction"], [1] * 8)
            run_cli(self, *keys, "neo-style-plan", "KEYA3.xml", snapshot("KEYA3.xml"), "--colour", "blue", status=1)


def raw_byte(session, address):
    return int(session.get_raw_data(address, 1).lines[-1].split("RawData=", 1)[1], 16)


@unittest.skipUnless(classic_tests.NATIVE, classic_tests.NATIVE_REASON)
class NativeInputOptionTests(unittest.TestCase):
    """Native PP acceptance on closed database units; no physical input."""

    def setUp(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        self.store = UnitSpecStore(os.environ["CBUS_UNITSPEC_DIR"])
        self.CGateClient, self.NativeDatabase, self.Programmer = CGateClient, NativeDatabase, Programmer

    def create(self, client, network, address, unit_type, filename, family=None, firmware=None, catalog=None):
        if family is not None:
            firmware, catalog = classic_tests.family_catalog(family, filename)
        self.NativeDatabase(client).create_unit(network, address, unit_type + "_" + str(address), unit_type,
                                                firmware, catalog_number=catalog)
        return f"{network}/p/{address}"

    def reload(self, client, project, network, finals):
        client.command("PROJECT SAVE " + project)
        client.command("PROJECT CLOSE " + project)
        client.command("PROJECT LOAD " + project)
        client.command("PROJECT USE " + project)
        for path, expected in finals.items():
            with self.subTest(reload=path), self.Programmer(client).load(network, "/db" + path) as session:
                self.assertEqual(session.values(), expected)

    def test_custom_micro_functions_on_classic_and_neo_types(self):
        cases = (("KEY4.xml", "KEY4", "classic", 0x32), ("KEYAUX4.xml", "KEYAUX4", "classic", 0x32),
                 ("KEYM4.xml", "KEYM4", "neo", 0x68), ("KEYB6.xml", "KEYB6", "neo", 0x68),
                 ("KEYDV2.xml", "KEYDV2", "neo", 0x68), ("KEYE.xml", "KEYE1", "neo", 0x68))
        finals = {}
        with classic_tests.native_endpoint() as (host, port), self.CGateClient(host, port, timeout=30) as client, \
                classic_tests.closed_network_project(client, "CM") as project:
            network = f"//{project}/254"
            for index, (filename, unit_type, family, base) in enumerate(cases):
                spec = self.store.load(filename)
                keys = ClassicKeys(spec) if family == "classic" else ExtendedKeys(spec)
                workflow = _READ_FIELDS if family == "classic" else LAYOUTS
                if unit_type == "KEY4":
                    path = self.create(client, network, 60 + index, unit_type, filename, firmware="1.2.67", catalog="5034N")
                else:
                    path = self.create(client, network, 60 + index, unit_type, filename, family=family)
                key = keys.key_count
                with self.Programmer(client).load(network, "/db" + path) as session:
                    session.reset_defaults()
                    baseline = session.values()
                    # Every stage accepts every code 0..15: rotate through them.
                    for code in range(16):
                        stages = {stage: (code + offset * 4) % 16 for offset, stage in enumerate(STAGES)}
                        with self.subTest(unit_type=unit_type, code=code):
                            result = keys.configure_micro_functions(session, key=key, stages=stages)
                            self.assertTrue(result["verified"])
                            actual = session.values()
                            self.assertEqual({name: int(actual[name].split()[key - 1], 0) for name in STAGES}, stages)
                            raw = session.get_raw_data(base + 2 * (key - 1), 2).lines[-1].split("RawData=", 1)[1]
                            codes = [stages[name] for name in STAGES]
                            self.assertEqual(raw, bytes((codes[0] << 4 | codes[1], codes[2] << 4 | codes[3])).hex())
                            self.assertEqual(classic_tests.unrelated(actual, workflow),
                                             classic_tests.unrelated(baseline, workflow))
                    # A single-stage edit keeps the other three stages.
                    before = session.values()
                    keys.configure_micro_functions(session, key=1, stages={"lr": "off"})
                    after = session.values()
                    for name in ("JPCommand", "SRCommand", "LPCommand"):
                        self.assertEqual(after[name], before[name])
                    self.assertEqual(int(after["LRCommand"].split()[0], 0), 15)
                    with self.assertRaises(MacroError):
                        keys.plan_micro_functions(session.values(), key=key + 1, stages={"jp": 1})
                    if family == "neo":
                        selectors = ["0"] * 8
                        selectors[0] = "1"
                        session.set("SceneKeySelector", " ".join(selectors))
                        frozen = session.values()
                        with self.assertRaisesRegex(MacroError, "scene keys"):
                            keys.configure_micro_functions(session, key=1, stages={"jp": 1})
                        self.assertEqual(session.values(), frozen)
                        session.set("SceneKeySelector", "0 0 0 0 0 0 0 0")
                    finals[path] = session.values()
                    session.save_to_source()
            self.reload(client, project, network, finals)

    def test_power_up_broadcast_on_couplers_and_broadcast_flag_units(self):
        finals = {}
        with classic_tests.native_endpoint() as (host, port), self.CGateClient(host, port, timeout=30) as client, \
                classic_tests.closed_network_project(client, "PU") as project:
            network = f"//{project}/254"
            for index, (unit_type, firmware, catalog) in enumerate((("BCN2B", "2.2.00", "5102BCLEDL"),
                                                                    ("BCN4B", "2.2.00", "5104BCL"),
                                                                    ("KEYV1SP", "2.0.00", "BCL-V-01"))):
                editor = CouplerPowerUp(self.store.load(unit_type + ".xml"))
                path = self.create(client, network, 80 + index, unit_type, unit_type + ".xml",
                                   firmware=firmware, catalog=catalog)
                with self.Programmer(client).load(network, "/db" + path) as session:
                    session.reset_defaults()
                    # Key 1 bistable on blocks 1 and 3; a stale bit on block 8.
                    session.set("BlockAllocation", "5 2 4 8 16 32 64 128")
                    session.set("BistableSwitchBlock", "1")
                    session.set("GroupAssertOnPowerup", "128")
                    baseline = session.values()
                    with self.assertRaisesRegex(PPEditError, "bistable"):
                        editor.configure(session, enable=[2])
                    self.assertEqual(session.values(), baseline)
                    result = editor.configure(session, enable=[1, 3])
                    self.assertTrue(result["verified"])
                    self.assertEqual(result["cleared_non_bistable"], [8])
                    self.assertEqual(raw_byte(session, 0x1D), 0b101)
                    self.assertEqual(classic_tests.unrelated(session.values(), COUPLER_LAYOUTS),
                                     classic_tests.unrelated(baseline, COUPLER_LAYOUTS))
                    editor.configure(session, disable=[3])
                    self.assertEqual(raw_byte(session, 0x1D), 1)
                    finals[path] = session.values()
                    session.save_to_source()
            for index, unit_type in enumerate(("KEYBC2", "KEYBC4", "DINAUX4")):
                editor = KeyPowerUpBroadcast(self.store.load(unit_type + ".xml"))
                path = self.create(client, network, 90 + index, unit_type, unit_type + ".xml", family="classic")
                with self.Programmer(client).load(network, "/db" + path) as session:
                    session.reset_defaults()
                    baseline = session.values()
                    editor.configure(session, broadcast=True)
                    self.assertEqual(raw_byte(session, 0x6F), 0)
                    self.assertEqual(classic_tests.unrelated(session.values(), BROADCAST_LAYOUTS),
                                     classic_tests.unrelated(baseline, BROADCAST_LAYOUTS))
                    finals[path] = session.values()
                    session.save_to_source()
            key4 = self.store.load("KEY4.xml")
            with self.assertRaises(PPEditError):
                power_up_editor(key4)
            self.reload(client, project, network, finals)

    def test_cli_dry_run_then_persist_each_editor(self):
        with classic_tests.native_endpoint() as (host, port), self.CGateClient(host, port, timeout=30) as client, \
                classic_tests.closed_network_project(client, "KC") as project:
            network = f"//{project}/254"
            paths = {"KEY4": self.create(client, network, 120, "KEY4", "KEY4.xml", firmware="1.2.67", catalog="5034N"),
                     "BCN4B": self.create(client, network, 121, "BCN4B", "BCN4B.xml", firmware="2.2.00", catalog="5104BCL"),
                     "KEYM4": self.create(client, network, 122, "KEYM4", "KEYM4.xml", family="neo")}
            cgate = ("cgate", "--host", host, "--port", port)
            spec_dir = ("--spec-dir", os.environ["CBUS_UNITSPEC_DIR"])
            def unit(unit_type):
                return ("unit", "--lock-address", network, "--source", "/db" + paths[unit_type])
            run_cli(self, *unit("BCN4B"), "set", "BistableSwitchBlock", "1", prefix=cgate)
            cases = (("KEY4", ("key-micro-functions", *spec_dir, "--spec", "KEY4.xml", "--key", 3, "--jp", "on", "--lp", 7),
                      lambda values: int(values["LPCommand"].split()[2], 0) == 7),
                     ("KEYM4", ("neo-key-micro-functions", *spec_dir, "--spec", "KEYM4.xml", "--key", 2, "--sr", "store1"),
                      lambda values: int(values["SRCommand"].split()[1], 0) == 1),
                     ("BCN4B", ("power-up", *spec_dir, "--spec", "BCN4B.xml", "--enable-block", 1),
                      lambda values: int(values["GroupAssertOnPowerup"], 0) == 1),
                     ("KEYM4", ("neo-indicators", *spec_dir, "--spec", "KEYM4.xml", "--brightness", "first_block",
                                "--id-backlight"),
                      lambda values: int(values["IndicatorBrightness"], 0) == 1),
                     ("KEYM4", ("neo-indicator-styles", *spec_dir, "--spec", "KEYM4.xml", "--colour", "blue"),
                      lambda values: values["PrimaryColour"].split() == ["0x0"] * 8 or
                      [int(v, 0) for v in values["PrimaryColour"].split()] == [0] * 8))
            for unit_type, action, check in cases:
                with self.subTest(action=action[0]):
                    original = run_cli(self, *unit(unit_type), "show", prefix=cgate)
                    preview = run_cli(self, *unit(unit_type), "--dry-run", *action, prefix=cgate)
                    self.assertTrue(preview["verified"])
                    self.assertFalse(preview["saved"])
                    self.assertEqual(run_cli(self, *unit(unit_type), "show", prefix=cgate), original)
                    applied = run_cli(self, *unit(unit_type), *action, prefix=cgate)
                    self.assertTrue(applied["saved"])
                    values = run_cli(self, *unit(unit_type), "show", prefix=cgate)
                    self.assertEqual(values, applied["parameters"])
                    self.assertTrue(check(values))

    def test_neo_indicator_options_and_styles_by_family(self):
        cases = ("KEYM4.xml", "KEYDV2.xml", "KEYB4.xml", "KEYH2.xml", "KEYV2.xml", "KEYA3.xml")
        finals = {}
        with classic_tests.native_endpoint() as (host, port), self.CGateClient(host, port, timeout=30) as client, \
                classic_tests.closed_network_project(client, "NI") as project:
            network = f"//{project}/254"
            for index, filename in enumerate(cases):
                spec = self.store.load(filename)
                unit_type = PROFILES[filename][0]
                options = NeoIndicatorOptions(spec)
                path = self.create(client, network, 100 + index, unit_type, filename, family="neo")
                with self.Programmer(client).load(network, "/db" + path) as session:
                    session.reset_defaults()
                    baseline = session.values()
                    options.configure(session, brightness="fixed", brightness_percent=3)
                    self.assertEqual(raw_byte(session, 0x32), 7)
                    options.configure(session, brightness="group", brightness_group=42)
                    self.assertEqual(raw_byte(session, 0x32), 0)
                    self.assertEqual(raw_byte(session, 0x58), 42)
                    options.configure(session, brightness="first_block")
                    self.assertEqual(raw_byte(session, 0x32), 1)
                    result = options.configure(session, key_press_level=9, key_press_seconds=4, nightlight=True,
                                               ignore_first_key_press=True, timer_flash=False, id_backlight=True)
                    self.assertTrue(result["verified"])
                    bit = 6 if FAMILIES[unit_type] == "standard" else 5
                    self.assertEqual(raw_byte(session, 0x33), 0x94)
                    self.assertEqual(raw_byte(session, 0x34) & 0x7B, 1 << bit | 1 << 4 | 1 << 3 | 1 << 1)
                    before = session.values()
                    with self.assertRaisesRegex(PPEditError, "key-press brightening"):
                        options.configure(session, key_press_seconds=0)
                    self.assertEqual(session.values(), before)
                    options.configure(session, key_press_seconds=0, nightlight=False, ignore_first_key_press=False)
                    self.assertEqual(raw_byte(session, 0x33), 0x90)
                    if FAMILIES[unit_type] in ("standard", "saturn"):
                        styles = NeoIndicatorStyles(spec)
                        styles.configure(session, colour="blue", style="status_dual")
                        for entry in range(8):
                            self.assertEqual(raw_byte(session, 0x60 + entry) & 0x38, 0x30)
                        styles.configure(session, colour="orange", style="always_off")
                        for entry in range(8):
                            self.assertEqual(raw_byte(session, 0x60 + entry) & 0x38, 0x08)
                    else:
                        with self.assertRaises(PPEditError):
                            NeoIndicatorStyles(spec)
                    workflow = {**OPTION_LAYOUTS, **STYLE_LAYOUTS}
                    self.assertEqual(classic_tests.unrelated(session.values(), workflow),
                                     classic_tests.unrelated(baseline, workflow))
                    finals[path] = session.values()
                    session.save_to_source()
            with self.assertRaises(PPEditError):
                NeoIndicatorOptions(self.store.load("KEYC4.xml"))
            self.reload(client, project, network, finals)


if __name__ == "__main__":
    unittest.main()
