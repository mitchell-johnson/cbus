"""Narrowest offline P5-P6 slices (issues 38-44, 45-49, 103).

Each class pins ONE genuinely-missing pure-offline branch with a synthetic
fixture. No hardware, vendor EXE, C-Gate server, or decoded vendor spec is
required. P5.01 device-dialog control bindings are intentionally NOT covered
here: they need the vendor-EXE digest (see module docstring in
device_dialogs.py and test_device_dialogs.py, 13 tests).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from test_dlt_labels import fixture as dlt_fixture
from test_input_options import fixture as input_fixture
from test_sensors import fixture as sensor_fixture
from test_thermostat_settings import OUTPUTS, _spec, snapshot
from test_wireless_gateway import fixture as wgate_fixture

from cbus_toolkit import thermostat_settings as ts_settings
from cbus_toolkit.conversion import NativeConversions
from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.dlt_labels import DltLabelError, flavour_bits, variant
from cbus_toolkit.input_power_up import COUPLER_LAYOUTS, CouplerPowerUp
from cbus_toolkit.key_options_cli import _controls, _number, _settings, _unique_object, offline
from cbus_toolkit.sensors import Multisensor, SensorError, margin_percent, saved_margin
from cbus_toolkit.thermostat_templates import ThermostatTemplateError
from cbus_toolkit.unitspec import UnitSpecStore
from cbus_toolkit.wireless_gateway import (
    NO_REMOTE,
    WirelessGatewayError,
    parse_assignment,
    serial_from_bytes,
    serial_to_bytes,
)


class KeyOptionsCliOfflineTests(unittest.TestCase):
    """P5.02 (issue 39): the key_options_cli adapter had zero direct tests.

    test_input_options.py (14 tests) covers the underlying editors
    (ClassicKeys/ExtendedKeys/CouplerPowerUp/NeoIndicator*), but nothing
    imported key_options_cli itself. These pins cover its pure-offline
    helpers: base-0 numbers, duplicate JSON keys, control-array shape,
    micro-function digit-vs-name staging, power-up coupler/broadcast
    branches, indicator empty-options refusal, and the micro-function
    domain listing (no spec required).
    """

    def test_number_parses_bases_and_rejects(self):
        self.assertEqual(_number("0x10"), 16)
        self.assertEqual(_number("0o17"), 15)
        self.assertEqual(_number("20"), 20)
        self.assertEqual(_number("0"), 0)
        for bad in ("010", "xyz", "", "0x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                _number(bad)

    def test_unique_object_rejects_duplicate_keys(self):
        self.assertEqual(_unique_object([("a", 1), ("b", 2)]), {"a": 1, "b": 2})
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            json.loads('{"a": 1, "a": 2}', object_pairs_hook=_unique_object)

    def test_controls_requires_json_array(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "controls.json"
            path.write_text("[]", encoding="utf-8")
            self.assertEqual(_controls(path), [])
            path.write_text('[1, 2]', encoding="utf-8")
            self.assertEqual(_controls(path), [1, 2])
            path.write_text('{"a": 1}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON array"):
                _controls(path)
            path.write_text('{"a": 1, "a": 2}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                _controls(path)

    def test_settings_micro_function_digit_vs_name(self):
        args = SimpleNamespace(key_number=2, jp="0x3", sr="off", lp="10", lr=None)
        method, options = _settings("custom-plan", args, object())
        self.assertEqual(method, "micro_functions")
        self.assertEqual(options, {"key": 2, "stages": {"jp": 3, "sr": "off", "lp": 10}})

    def test_settings_power_up_coupler_and_broadcast_branches(self):
        coupler = CouplerPowerUp(input_fixture("BCN4B.xml", "BCN4B", COUPLER_LAYOUTS))
        method, options = _settings(
            "power-up-plan",
            SimpleNamespace(enable_blocks=[1], disable_blocks=[], broadcast=None),
            coupler,
        )
        self.assertEqual((method, options), ("plan", {"enable": [1], "disable": []}))
        with self.assertRaisesRegex(ValueError, "not --broadcast"):
            _settings(
                "power-up-plan",
                SimpleNamespace(enable_blocks=[], disable_blocks=[], broadcast=True),
                coupler,
            )
        method, options = _settings(
            "power-up-plan",
            SimpleNamespace(enable_blocks=[], disable_blocks=[], broadcast=True),
            object(),
        )
        self.assertEqual((method, options), ("plan", {"broadcast": True}))
        for args in (
            SimpleNamespace(enable_blocks=[1], disable_blocks=[], broadcast=None),
            SimpleNamespace(enable_blocks=[], disable_blocks=[], broadcast=None),
        ):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, "--broadcast"):
                _settings("power-up-plan", args, object())

    def test_settings_indicator_requires_one_option(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            _settings(
                "neo-indicator-plan",
                SimpleNamespace(
                    brightness=None,
                    brightness_percent=None,
                    brightness_group=None,
                    key_press_level=None,
                    key_press_seconds=None,
                    nightlight=None,
                    ignore_first_key_press=None,
                    timer_flash=None,
                    id_backlight=None,
                ),
                object(),
            )
        method, options = _settings(
            "neo-indicator-plan",
            SimpleNamespace(
                brightness="fixed",
                brightness_percent=50,
                brightness_group=None,
                key_press_level=None,
                key_press_seconds=None,
                nightlight=None,
                ignore_first_key_press=None,
                timer_flash=None,
                id_backlight=None,
            ),
            object(),
        )
        self.assertEqual(method, "plan")
        self.assertEqual(options, {"brightness": "fixed", "brightness_percent": 50})

    def test_offline_micro_functions_lists_domain(self):
        document, code = offline(SimpleNamespace(action="micro-functions"))
        self.assertEqual(code, 0)
        self.assertEqual(document["stages"], ["JPCommand", "SRCommand", "LPCommand", "LRCommand"])
        self.assertEqual(len(document["micro_functions"]), 16)
        self.assertEqual(document["micro_functions"][0]["code"], 0)


class ConversionNarrowTests(unittest.TestCase):
    """P5.06 (issue 43): catalogue-vs-destination conflict and path normalization.

    test_conversion.py (3 offline + 3 native-skipped) covers CHECK modes,
    rejected conversions, and invalid paths/targets, but never exercises
    _arguments with both a catalogue target and a destination (which must
    fail before any I/O), nor the int() normalization of leading-zero
    octets (//TEST/054/p/020 -> //TEST/54/p/20).
    """

    class RecordingClient:
        def __init__(self):
            self.commands = []

        def command(self, command):
            self.commands.append(command)
            line = "200 yes"
            return CGateResponse((line,), line, 200)

    def test_catalogue_and_destination_conflict_fails_before_io(self):
        client = self.RecordingClient()
        converter = NativeConversions(client)
        with self.assertRaisesRegex(ValueError, "catalogue target or an existing destination"):
            converter._arguments("//TEST/254/p/20", unit_type="DIMDU4", destination="//TEST/254/p/21")
        with self.assertRaisesRegex(ValueError, "catalogue target or an existing destination"):
            converter._arguments(
                "//TEST/254/p/20", catalog_number="L5504D2U", destination="//TEST/254/p/21"
            )
        self.assertEqual(client.commands, [])

    def test_unit_path_normalizes_leading_zeros(self):
        client = self.RecordingClient()
        converter = NativeConversions(client)
        arguments, source, destination, project = converter._arguments(
            "//TEST/054/p/020", unit_type="DIMDU4", catalog_number="L5504D2U"
        )
        self.assertEqual(source, "//TEST/54/p/20")
        self.assertEqual(destination, "//TEST/54/p/20")
        self.assertEqual(project, "TEST")
        self.assertEqual(arguments, "1 //TEST/54/p/20 DIMDU4 L5504D2U")
        self.assertEqual(client.commands, [])


class WirelessGatewayNarrowTests(unittest.TestCase):
    """P5.07 (issue 44): serial-zero roundtrip and tolerant assignment parsing.

    test_wireless_gateway.py (13 tests, incl. 58 native save assertions via
    the retained receipt) covers serial 0x12345678, NO_REMOTE, three parse
    cases and the WTXU map, but never pins serial 0, outer-whitespace /
    case-insensitive parsing, hex groups, or group:none with an explicit
    application.
    """

    def test_serial_zero_roundtrip(self):
        self.assertEqual(serial_to_bytes(0), (0, 0, 0, 0))
        self.assertEqual(serial_from_bytes((0, 0, 0, 0)), 0)
        self.assertEqual(serial_from_bytes(serial_to_bytes(1)), 1)
        self.assertEqual(serial_to_bytes(NO_REMOTE - 1), (0xFE, 0xFF, 0xFF, 0xFF))

    def test_parse_assignment_tolerant_case_whitespace_hex_and_none(self):
        self.assertEqual(
            parse_assignment("  GROUP:0x10:SECONDARY  "),
            {"function": "group", "group": 16, "application": "secondary"},
        )
        self.assertEqual(
            parse_assignment("Group:10"),
            {"function": "group", "group": 10, "application": "primary"},
        )
        self.assertEqual(
            parse_assignment("group:none:secondary"),
            {"function": "group", "group": None, "application": "secondary"},
        )
        self.assertEqual(
            parse_assignment("SCENE-SET:1"), {"function": "scene-set", "scene": 1}
        )
        for bad in ("group:1:2:3", "scene-set:0x1"):
            with self.subTest(bad=bad), self.assertRaises(WirelessGatewayError):
                parse_assignment(bad)

    def test_wgate_fixture_loads_admitted_layout(self):
        from cbus_toolkit.wireless_gateway import WirelessGatewayEditor

        editor = WirelessGatewayEditor(wgate_fixture())
        self.assertEqual(editor.spec.filename, "WGATE5X_2.xml")


class SensorsNarrowTests(unittest.TestCase):
    """P5.04 (issue 41): potentiometer-override boolean guard symmetry.

    test_sensors.py (23 tests) pins allow_shared_block=1 as non-boolean but
    never exercises disable_potentiometer_override with a non-boolean, even
    though plan() validates both together. It also never pins the
    target-zero margin guard directly (margin_percent(0, m) == 0 without
    division). Fixture is the shared synthetic SENPILL layout.
    """

    def setUp(self):
        self.spec = sensor_fixture()
        self.sensor = Multisensor(self.spec)

    def test_both_boolean_guards_reject_non_boolean(self):
        for options in ({"allow_shared_block": 1}, {"allow_shared_block": "yes"}):
            with self.subTest(options=options), self.assertRaisesRegex(SensorError, "boolean"):
                self.sensor.plan(self.spec.defaults(), key=1, event="day", block=1, group=1, **options)
        for options in ({"disable_potentiometer_override": 1}, {"disable_potentiometer_override": "yes"}):
            with self.subTest(options=options), self.assertRaisesRegex(SensorError, "boolean"):
                self.sensor.plan(
                    self.spec.defaults(),
                    key=1,
                    event="day",
                    block=1,
                    group=1,
                    **options,
                )

    def test_margin_target_zero_guard(self):
        self.assertEqual(margin_percent(0, 0), 0)
        self.assertEqual(margin_percent(0, 5), 0)
        self.assertEqual(margin_percent(0, 255), 0)
        self.assertEqual(saved_margin(0, 100), 0)


class ThermostatNarrowTests(unittest.TestCase):
    """P5.05 (issue 42): mapping and preference type guards.

    test_thermostat_settings.py (15 tests) plus dialog-rules (9) cover zones,
    plants, remotes, AFTERLOAD flags and ('C', '', True, 1) preferences, but
    never pins plan_settings with a non-Mapping edits value nor a bytes
    temperature preference. Fixture mirrors the shared synthetic spec.
    """

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        names = set(snapshot())
        (root / "THERMOSTATA.xml").write_text(_spec("THERMOSTATA", names - {"TimerEnable"}))
        (root / "THERMOSTATB.xml").write_text(
            _spec(
                "THERMOSTATB",
                names - set(ts_settings.admitted("programmable"))
                | set(ts_settings.admitted("basic"))
                | {n + "Output" for n in OUTPUTS},
            )
        )
        self.store = UnitSpecStore(root)

    def test_edits_must_be_a_mapping(self):
        for edits in (["PlantCycleTime"], "PlantCycleTime", [("PlantCycleTime", 1)], None):
            with self.subTest(edits=edits), self.assertRaisesRegex(
                ThermostatTemplateError, "mapping"
            ):
                ts_settings.plan_settings(self.store, "PC_TSA", snapshot(), edits)

    def test_bytes_preference_rejected_like_other_non_strings(self):
        with self.assertRaisesRegex(ThermostatTemplateError, "preference"):
            ts_settings.plan_settings(
                self.store, "PC_TSA", snapshot(), {"PlantCycleTime": 0},
                temperature_preference=b"celsius",
            )


class DltNarrowTests(unittest.TestCase):
    """P6 (issues 45-49, 103): LoadLabelFlavours clamps out-of-range raw bits.

    test_dlt_labels.py (15 tests) pins variant() for 0/1 LSB/MSB and
    flavour_bits() refusals (0, 5, -1, True, 2.0, '2'), but never pins the
    min(LSB, 1)/min(MSB, 1) clamp for corrupted raw values > 1. The
    Toolkit view must still report 1..4. Fixture is the shared classic-DLT
    synthetic spec.
    """

    def test_variant_clamps_raw_bits_above_one(self):
        self.assertEqual(variant(5, 7), 4)
        self.assertEqual(variant(2, 0), 2)
        self.assertEqual(variant(0, 9), 3)
        self.assertEqual(variant(3, 4), 4)
        for lsb in (0, 1, 2, 255):
            for msb in (0, 1, 2, 255):
                with self.subTest(lsb=lsb, msb=msb):
                    self.assertIn(variant(lsb, msb), (1, 2, 3, 4))

    def test_flavour_roundtrip_still_holds(self):
        editor_fixture = dlt_fixture()
        self.assertIn("LabelFlavourLSB", editor_fixture.parameters)
        for value in (1, 2, 3, 4):
            self.assertEqual(variant(*flavour_bits(value)), value)


class P5P6Round2NarrowTests(unittest.TestCase):
    """Round 2 (issues 38-44, 45-49, 103): next narrowest pure-offline slices.

    Each method pins ONE genuinely-missing branch with zero prior refs
    (verified via grep -rn across tests/ before writing):
    - conversion.align guards (conversion.py:84-91): grep -rn "\\.align("
      tests/*.py -> 0 hits. Same-address, non-bool dry_run and
      backup-same-project all fail before any C-Gate I/O.
    - key_options_cli offline_options + _settings neo-style terminal
      (key_options_cli.py:79-98,159): grep -rn "offline_options"
      tests/*.py -> 0 hits; grep -rn "neo-style" tests/test_p5p6* -> 0
      hits (only indirect subprocess coverage via test_input_options.py).
    - dlt_controls control_snapshot missing FLAG + plan_controls non-dict
      variants (dlt_controls.py:80-98): grep -rn "control_snapshot"
      tests/*.py -> 0 hits; grep -rn "Variants must be" tests/*.py -> 0
      hits (test_dlt_controls.py covers block non-bool but never a
      non-dict variants value).
    No hardware, vendor EXE, C-Gate server, or decoded vendor spec needed.
    """

    def test_conversion_align_guards_fail_before_io(self):
        from cbus_toolkit.conversion import NativeConversions

        class RecordingClient:
            def __init__(self):
                self.commands = []

            def command(self, command):
                self.commands.append(command)
                line = "200 yes"
                return CGateResponse((line,), line, 200)

        client = RecordingClient()
        converter = NativeConversions(client)
        with self.assertRaisesRegex(ValueError, "must differ"):
            converter.align("//TEST/254/p/20", "//TEST/254/p/20", None, None)
        with self.assertRaisesRegex(ValueError, "must differ"):
            converter.align("//TEST/254/p/20", "//test/254/p/20", None, None)
        for dry_run in ("yes", 1, None):
            with self.subTest(dry_run=dry_run), self.assertRaisesRegex(ValueError, "boolean"):
                converter.align("//TEST/254/p/20", "//TEST/254/p/21", None, None, dry_run=dry_run)
        for backup in ("TEST", "test"):
            with self.subTest(backup=backup), self.assertRaisesRegex(ValueError, "must differ"):
                converter.align(
                    "//TEST/254/p/20", "//TEST/254/p/21", None, None, backup_project=backup
                )
        self.assertEqual(client.commands, [])

    def test_key_options_offline_registers_and_neo_style_terminal(self):
        import argparse

        from cbus_toolkit import key_options_cli as key_cli

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="action")
        key_cli.offline_options(sub)
        self.assertEqual(set(sub.choices), set(key_cli.OFFLINE_ACTIONS))
        method, options = key_cli._settings(
            "neo-style-plan", SimpleNamespace(colour="blue", style="always_on"), object()
        )
        self.assertEqual((method, options), ("plan", {"colour": "blue", "style": "always_on"}))
        method, options = key_cli._settings(
            "neo-style-plan", SimpleNamespace(colour="red", style=None), object()
        )
        self.assertEqual((method, options), ("plan", {"colour": "red", "style": None}))

    def test_dlt_controls_snapshot_and_variants_guards(self):
        from cbus_toolkit.dlt_controls import ClassicDltControls
        from cbus_toolkit.dlt_labels import DltLabelError as ControlLabelError
        from test_dlt_labels import session as dlt_session

        editor = ClassicDltControls(dlt_fixture(), "KEYBL5")
        live = dlt_session()
        values = live.values()
        missing = dict(values)
        del missing["EnableDynamicLabels"]
        with self.assertRaisesRegex(ControlLabelError, "Missing current DLT label parameter"):
            editor.control_snapshot(missing)
        for variants in ([(1, 4)], "1=4", [(1, 4, 5)]):
            with self.subTest(variants=variants), self.assertRaisesRegex(
                ControlLabelError, "slot=variant mapping"
            ):
                editor.plan_controls(values, block_dynamic_updates=True, variants=variants)
        plan = editor.plan_controls(values, block_dynamic_updates=False)
        self.assertEqual(dict(plan.changes), {})


class P5P6Round3NarrowTests(unittest.TestCase):
    """Round 3 (P5 leftovers): four highest-value pure-offline pins.

    Each method pins a branch with zero prior test refs (verified via
    grep -rn across tests/ before writing):
    - conversion._unit_path non-string/out-of-range (conversion.py:22-29):
      grep -rn "_unit_path(" tests/*.py -> only leading-zero normalization
      in test_p5p6_narrow_slices.py; no non-string, >255, or malformed
      case. Fails before any C-Gate I/O.
    - wireless_gateway NO_REMOTE/secondary/empty/unbound
      (wireless_gateway.py:112-138): serial_to_bytes(NO_REMOTE),
      decode_slot(1, 1, *) secondary scene, scene_count all-0xFF == 0,
      and WirelessGatewayPlan.from_dict with firmware None. Only
      serial_from_bytes((255,)*4), decode_slot(1, 0, *)/(0, 1, *),
      mixed scene_count, and bound from_dict are pinned elsewhere.
    - dlt_display._snapshot missing-param (dlt_display.py:58-67):
      test_dlt_display.py pins invalid values but never a missing key.
    - sensors.verify_native_schema happy + declaration refusal
      (sensors.py:129-137): zero refs; fake Session.info('*') keeps it
      pure-offline (synthetic SENPILL layout, no C-Gate/vendor EXE).
    Leftovers NOT pinned here: sensors.py message-specific plan guards
    (already message-covered in test_sensors.py invalid-input cases),
    thermostat_settings _quoted_group_tag double-space (already pinned in
    test_thermostat_output_add_native.py:85-98) and admitted() invalid
    family (trivial KeyError, lower value than the four above).
    """

    def test_conversion_unit_path_rejects_non_string_and_out_of_range(self):
        from cbus_toolkit.conversion import _unit_path

        for bad in (123, None, True, b"//TEST/254/p/20", 12.5):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                ValueError, "fully qualified"
            ):
                _unit_path(bad)
        for bad in (
            "//TEST/256/p/20",
            "//TEST/254/p/256",
            "//TEST/254/p/",
            "not-a-path",
            "//TOOLONGNAME/254/p/20",
            "//TEST/254/x/20",
        ):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                ValueError, r"form //PROJECT"
            ):
                _unit_path(bad)

    def test_wireless_gateway_no_remote_secondary_empty_and_unbound(self):
        import json

        from cbus_toolkit.wireless_gateway import (
            WirelessGatewayEditor,
            WirelessGatewayPlan,
            decode_slot,
            scene_count,
            serial_from_bytes,
            serial_to_bytes,
        )
        from test_wireless_gateway import remote_switch

        self.assertEqual(serial_to_bytes(NO_REMOTE), (0xFF, 0xFF, 0xFF, 0xFF))
        self.assertEqual(serial_from_bytes((0xFF, 0xFF, 0xFF, 0xFF)), NO_REMOTE)
        row = decode_slot(1, 1, 0x21)
        self.assertEqual(row["function"], "scene-set")
        self.assertEqual(row["scene"], 3)
        self.assertEqual(row["raw"], {"mask": 1, "secondary": 1, "value": 0x21})
        self.assertEqual(decode_slot(1, 1, 0x26)["function"], "scene-toggle")
        self.assertEqual(scene_count((0xFF,) * 8), 0)
        editor = WirelessGatewayEditor(wgate_fixture())
        plan = editor.plan(remote_switch().values(), mode="network-gateway")
        self.assertIsNone(plan.identity)
        document = json.loads(json.dumps(plan.as_dict()))
        self.assertIsNone(document.get("firmware"))
        restored = WirelessGatewayPlan.from_dict(document)
        self.assertIsNone(restored.identity)
        self.assertEqual(restored, plan)

    def test_dlt_display_snapshot_requires_every_field(self):
        from cbus_toolkit.dlt_display import FIELDS, _snapshot
        from cbus_toolkit.dlt_labels import DltLabelError
        from test_dlt_display import fixture as display_fixture

        values = display_fixture().defaults()
        self.assertEqual(set(_snapshot(values)), set(FIELDS))
        missing = dict(values)
        del missing["HideClock"]
        with self.assertRaisesRegex(DltLabelError, "Missing current classic DLT display"):
            _snapshot(missing)
        with self.assertRaisesRegex(DltLabelError, "Missing current classic DLT display"):
            _snapshot({})

    def test_sensors_verify_native_schema_accepts_fixture_and_refuses_declarations(self):
        from test_macros import Session

        from cbus_toolkit.sensors import LAYOUTS, _BITS, SensorError, verify_native_schema

        spec = sensor_fixture()
        live = Session(spec)
        self.assertIsNone(verify_native_schema(live, spec, LAYOUTS, _BITS))

        class DoctypeReply:
            lines = ("347-<!DOCTYPE Parameters>",)

        class DoctypeSession:
            def info(self, _name):
                return DoctypeReply()

        with self.assertRaisesRegex(SensorError, "Unsupported native schema"):
            verify_native_schema(DoctypeSession(), spec, LAYOUTS, _BITS)

        class BrokenReply:
            lines = ("347-<Parameters><Param>",)

        class BrokenSession:
            def info(self, _name):
                return BrokenReply()

        with self.assertRaisesRegex(SensorError, "Invalid native parameter schema"):
            verify_native_schema(BrokenSession(), spec, LAYOUTS, _BITS)


class P5P6Round4P5NarrowTests(unittest.TestCase):
    """Round 4 P5 leftovers: message-specific guards with zero prior message pins.

    Each method pins branches with zero prior message-regex refs (verified via
    grep -rn across tests/ before writing):
    - sensors.plan early + key/block guards (sensors.py:223-254): grep -rn
      "Supply both|Event must be|Unsupported timer expiry|Expiry selection|
      require a key/event|Virtual key|Specify block|Block must" tests/*.py
      -> 0 hits. test_sensors.py:153-159 covers the same variants with a
      generic ValueError only; SensorsNarrowTests pins only the "boolean"
      substring and test_sensors.py pins "shared"/"multiple-block"/"Join"/
      "broadcasting"/"maintenance"/"Lighting" substrings elsewhere.
    - thermostat_settings.admitted invalid family
      (thermostat_settings.py:56-57): grep -rn "admitted(" tests/*.py ->
      only valid "programmable"/"basic" uses; no KeyError pin.
    - wireless_gateway WirelessGatewayPlan.from_dict remaining bad shapes
      (wireless_gateway.py:209-221): test_wireless_gateway.py:241-243 pins
      only format-mismatch, unit_type-mismatch and expected-AttributeError;
      non-dict, missing-key, changes-bad-shape, value-TypeError and
      firmware-profile branches are unpinned.
    No hardware, vendor EXE, C-Gate server, or decoded vendor spec needed.
    """

    def test_sensors_early_and_key_block_guards_pin_messages(self):
        spec = sensor_fixture()
        sensor = Multisensor(spec)
        defaults = spec.defaults()
        with self.assertRaisesRegex(SensorError, "Supply both key and event"):
            sensor.plan(defaults, key=1)
        with self.assertRaisesRegex(SensorError, "Supply both key and event"):
            sensor.plan(defaults, event="day")
        with self.assertRaisesRegex(SensorError, "Event must be day"):
            sensor.plan(defaults, key=3, event="motion")
        with self.assertRaisesRegex(SensorError, "Unsupported timer expiry"):
            sensor.plan(defaults, expiry="bogus")
        with self.assertRaisesRegex(SensorError, "Expiry selection requires"):
            sensor.plan(defaults, expiry="ramp_off")
        with self.assertRaisesRegex(SensorError, "require a key/event"):
            sensor.plan(defaults, group=4)
        for key in (True, 9, 0):
            with self.subTest(key=key), self.assertRaisesRegex(
                SensorError, "Virtual key must be"
            ):
                sensor.plan(defaults, key=key, event="day")
        with self.assertRaisesRegex(SensorError, "Block must be"):
            sensor.plan(defaults, key=3, event="day", block=9, group=1)
        current = dict(defaults)
        current["BlockAllocation"] = "0 2 4 8 16 32 64 128"
        with self.assertRaisesRegex(SensorError, "Specify block 1..8"):
            sensor.plan(current, key=1, event="day", group=1)

    def test_thermostat_admitted_invalid_family_raises_keyerror(self):
        for bad in ("bogus", "", "PROGRAMMABLE", None):
            with self.subTest(family=bad), self.assertRaises(KeyError):
                ts_settings.admitted(bad)
        self.assertIn("SendInterval", ts_settings.admitted("programmable"))
        self.assertIn("TimerEnable", ts_settings.admitted("basic"))

    def test_wireless_gateway_from_dict_remaining_bad_shapes(self):
        from cbus_toolkit.wireless_gateway import PLAN_FORMAT, UNIT_TYPE, WirelessGatewayPlan

        for bad in (None, [], "x", {}):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                WirelessGatewayError, "Expected a"
            ):
                WirelessGatewayPlan.from_dict(bad)
        base = {"format": PLAN_FORMAT, "unit_type": UNIT_TYPE, "expected": {}, "changes": {}}
        for bad in (
            {k: v for k, v in base.items() if k != "expected"},
            {k: v for k, v in base.items() if k != "changes"},
            {**base, "changes": 1},
            {**base, "expected": {"A": 1}},
            {**base, "expected": {"A": None}},
        ):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                WirelessGatewayError, "Plan requires expected"
            ):
                WirelessGatewayPlan.from_dict(bad)
        for firmware in ("bogus", "2.2.89", "2.5.00"):
            with self.subTest(firmware=firmware), self.assertRaisesRegex(
                WirelessGatewayError, "admitted"
            ):
                WirelessGatewayPlan.from_dict({**base, "firmware": firmware})


class P5P6Round4NarrowTests(unittest.TestCase):
    """Round 4 (P6 issues 45-49, 103): two genuinely-missing pure-offline slices.

    Each method pins a branch with zero prior test refs (verified via
    grep -rn across tests/ before writing):
    - dlt_indicators._snapshot missing-param (dlt_indicators.py:45-54):
      grep -rn "Missing current classic DLT indicator" tests/*.py -> 0
      hits. test_dlt_indicators.py always plans from full fixture
      defaults and never drops a key. Mirrors the round-3
      dlt_display._snapshot pin.
    - dlt_broadcast._request defers ICON/DYNAMIC/FONT prerequisites when no
      command can be built (dlt_broadcast.py:97-106):
      grep -rn "already_broadcast.*ICON" tests/*.py -> 0 hits and grep -rn
      "ICON.*already_broadcast" tests/*.py -> 0 hits.
      test_dlt_broadcast.py pins invalid ICON IDs ('01', '65536') and a
      missing DYNAMIC bitmap as refusals, and already_broadcast True only
      with valid TEXT, but never the already-broadcast bypass for invalid
      image IDs or a missing bitmap.
    No hardware, vendor EXE, C-Gate server, or decoded vendor spec needed.
    """

    def test_dlt_indicators_snapshot_requires_every_field(self):
        from cbus_toolkit.dlt_indicators import FIELDS as INDICATOR_FIELDS, ClassicDltIndicators
        from cbus_toolkit.dlt_labels import DltLabelError as IndicatorLabelError
        from test_dlt_indicators import fixture as indicator_fixture

        editor = ClassicDltIndicators(indicator_fixture(), "KEYBL5")
        values = indicator_fixture().defaults()
        self.assertEqual(set(editor.snapshot(values)), set(INDICATOR_FIELDS))
        missing = dict(values)
        del missing["TimerDuration"]
        with self.assertRaisesRegex(IndicatorLabelError, "Missing current classic DLT indicator"):
            editor.snapshot(missing)
        with self.assertRaisesRegex(IndicatorLabelError, "Missing current classic DLT indicator"):
            editor.snapshot({})

    def test_dlt_broadcast_defers_image_prerequisites_when_already_broadcast(self):
        from cbus_toolkit.dlt_broadcast import DltBroadcastError, compile_broadcast

        def broadcast_request(**changes):
            request = {
                "format": "cbus-classic-dlt-broadcast-request-v1", "project": "LAB",
                "network": 254, "application": 56, "application_oid": None,
                "group": 20, "level": None, "language": 1, "variant": 1,
                "tag_type": "TEXT", "tag_value": "Kitchen",
                "already_broadcast": False, "bitmap": None,
            }
            request.update(changes)
            return request

        invalid_image_cases = (
            {"tag_type": "ICON", "tag_value": "01"},
            {"tag_type": "ICON", "tag_value": "65536"},
            {"tag_type": "DYNAMIC", "tag_value": "1"},
        )
        for changes in invalid_image_cases:
            with self.subTest(changes=changes), self.assertRaises(DltBroadcastError):
                compile_broadcast(broadcast_request(**changes))
        for changes in invalid_image_cases:
            with self.subTest(changes=changes):
                plan = compile_broadcast(
                    broadcast_request(**changes, already_broadcast=True)
                ).as_dict()
                self.assertEqual(plan["disposition"], "already_broadcast")
                self.assertEqual(plan["commands"], [])
                self.assertEqual(plan["events"], [])
                self.assertTrue(plan["planned_final_cache_marked"])
        # The bypass is narrow: unrelated request validation still applies.
        with self.assertRaises(DltBroadcastError):
            compile_broadcast(broadcast_request(variant=0, already_broadcast=True))


class P5P6Round5NarrowTests(unittest.TestCase):
    """Round 5 (sensor/wireless leftovers): identity shape + boolean/raw-slot pins.

    Each method pins branches with zero prior message-regex refs (verified via
    grep -rn across tests/ before writing):
    - sensors.py:218 + wireless_gateway.py:313 identity tuple-shape guards:
      grep -rn "Identity must be" tests/*.py -> 0 hits (the only hit is an
      unrelated test_edlt.py fail-message; test_sensors.py:166-168 covers the
      same sensor inputs with a generic assertRaises only).
    - sensors.py:222 shared-block/potentiometer full tokens: grep -rn
      "Shared-block" tests/*.py -> 0 hits (SensorsNarrowTests pins only the
      generic "boolean" substring).
    - wireless_gateway.py:221 raw_slot_edits=1 bare TypeError: grep -rn
      "raw_slot_edits" tests/*.py -> only valid shapes ([16], (), (16, 1));
      Round4 P5 from_dict pins cover only expected/changes/firmware shapes,
      never a non-iterable raw_slot_edits which escapes the expected/changes
      try/except as a bare TypeError.
    No hardware, vendor EXE, C-Gate server, or decoded vendor spec needed.
    """

    def test_sensor_wireless_identity_shape_pins_message(self):
        from cbus_toolkit.wireless_gateway import WirelessGatewayEditor
        from test_wireless_gateway import remote_switch

        sensor = Multisensor(sensor_fixture())
        defaults = sensor_fixture().defaults()
        for bad in (("SENPILL", "2.3.00"), ["SENPILL", "2.3.00", "5753PEIRL"], "x"):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                SensorError, r"Identity must be \(unit_type, firmware, catalog_number\)"
            ):
                sensor.plan(defaults, identity=bad)
        editor = WirelessGatewayEditor(wgate_fixture())
        values = remote_switch().values()
        for bad in (("WGATE5F", "2.4.00"), ["WGATE5F", "2.4.00", "5800WCGA"], "x"):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                WirelessGatewayError, r"Identity must be \(unit_type, firmware, catalog_number\)"
            ):
                editor.plan(values, identity=bad)

    def test_sensor_boolean_full_token_and_raw_slot_edits_typeerror(self):
        from cbus_toolkit.wireless_gateway import PLAN_FORMAT, UNIT_TYPE, WirelessGatewayPlan

        sensor = Multisensor(sensor_fixture())
        defaults = sensor_fixture().defaults()
        for options in ({"allow_shared_block": 1}, {"disable_potentiometer_override": 1}):
            with self.subTest(options=options), self.assertRaisesRegex(
                SensorError, "Shared-block and potentiometer options must be boolean"
            ):
                sensor.plan(defaults, key=1, event="day", block=1, group=1, **options)
        base = {"format": PLAN_FORMAT, "unit_type": UNIT_TYPE, "expected": {}, "changes": {}}
        with self.assertRaises(TypeError):
            WirelessGatewayPlan.from_dict({**base, "raw_slot_edits": 1})


class P5P6Round7DltNarrowTests(unittest.TestCase):
    """Round 7 (P6 issues 45-49, 103): two genuinely-missing pure-offline slices.

    Each method pins a branch with zero prior direct test refs (verified via
    grep -rn across tests/ before writing):
    - dlt_cli._slot_variant syntax guard (dlt_cli.py:9-13): grep -rn
      "_slot_variant" tests/*.py -> 0 hits. test_cli_dlt.py exercises
      --variant only via subprocess with well-formed SLOT=VARIANT plus
      semantic refusals (1=5 range, 9=1 slot, duplicate, missing); no test
      ever passes malformed syntax, so the ValueError branch is unpinned.
    - dlt_cli.display_settings yes/no mapping (dlt_cli.py:41-49): grep -rn
      "display_settings(" tests/*.py -> 0 hits (the only "display_settings"
      hit is an unrelated evidence-dict key in test_differential_matrix.py
      without a call paren). test_cli_dlt_display.py exercises the flags
      only via subprocess CLI, never the pure mapping itself.
    No hardware, vendor EXE, C-Gate server, decoded vendor spec, or fixture
    needed: both helpers take plain strings/SimpleNamespace only.
    """

    def test_dlt_cli_slot_variant_parses_and_refuses_syntax(self):
        from cbus_toolkit.dlt_cli import _slot_variant

        self.assertEqual(_slot_variant("3=2"), (3, 2))
        self.assertEqual(_slot_variant(" 1 = 4 "), (1, 4))
        self.assertEqual(_slot_variant("03=02"), (3, 2))
        for bad in ("3", "3=", "=2", "a=2", "3=b", "3.0=2", "", "  =  ", "3==2", "page_fallback=yes"):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                ValueError, r"SLOT=VARIANT"
            ):
                _slot_variant(bad)

    def test_dlt_cli_display_settings_maps_yes_no_and_empty(self):
        from types import SimpleNamespace as Namespace

        from cbus_toolkit.dlt_cli import display_settings

        self.assertEqual(
            display_settings(Namespace(indicator_mode=None, invert_display=None, show_clock=None)), {}
        )
        self.assertEqual(
            display_settings(Namespace(indicator_mode="on", invert_display="yes", show_clock="no")),
            {"indicator_mode": "on", "invert_display": True, "show_clock": False},
        )
        self.assertEqual(
            display_settings(Namespace(indicator_mode="off", invert_display="no", show_clock="yes")),
            {"indicator_mode": "off", "invert_display": False, "show_clock": True},
        )
        self.assertEqual(
            display_settings(Namespace(indicator_mode="normal", invert_display=None, show_clock="yes")),
            {"indicator_mode": "normal", "show_clock": True},
        )


class P5P6Round7bDltNarrowTests(unittest.TestCase):
    """Round 7b (P6 issues 45-49, 103): two remaining pure-offline slices.

    Each method pins a branch with zero prior test refs (verified via
    grep -rn across tests/ before writing):
    - ClassicDltControls.show missing FLAG reports None
      (dlt_controls.py:87-90): grep -rn "block_dynamic_updates.*None"
      tests/*.py -> 0 hits; grep -rn "enable_dynamic_labels_raw"
      tests/*.py -> only test_dlt_labels.py:84 (== 1). Round 2 pinned
      control_snapshot missing FLAG as a refusal, but never the show
      None bypass which reports unknown state without refusing.
    - dlt_indicators._operations shape guards (dlt_indicators.py:57-66):
      grep -rn "Supply 1" tests/*.py -> 0 hits; grep -rn
      "Each indicator operation" tests/*.py -> 0 hits; grep -rn
      "Unknown classic DLT indicator" tests/*.py -> 0 hits.
      test_dlt_indicators.py:123-130 covers the same inputs with generic
      pytest.raises only, never the message.
    No hardware, vendor EXE, C-Gate server, or decoded vendor spec needed:
    show uses the shared synthetic classic-DLT fixture; _operations takes
    plain lists/dicts only.
    """

    def test_dlt_controls_show_missing_flag_returns_none(self):
        from cbus_toolkit.dlt_controls import ClassicDltControls
        from test_dlt_labels import session as dlt_session

        editor = ClassicDltControls(dlt_fixture(), "KEYBL5")
        values = dlt_session().values()
        full = editor.show(values)
        self.assertFalse(full["block_dynamic_updates"])
        self.assertEqual(full["enable_dynamic_labels_raw"], 1)
        self.assertEqual(len(full["slots"]), 8)
        missing = dict(values)
        del missing["EnableDynamicLabels"]
        shown = editor.show(missing)
        self.assertIsNone(shown["block_dynamic_updates"])
        self.assertIsNone(shown["enable_dynamic_labels_raw"])
        self.assertEqual(len(shown["slots"]), 8)
        self.assertEqual(
            [row["variant"] for row in shown["slots"]],
            [row["variant"] for row in full["slots"]],
        )

    def test_dlt_indicators_operations_shape_guards_pin_messages(self):
        from cbus_toolkit.dlt_indicators import MAX_OPERATIONS, _operations
        from cbus_toolkit.dlt_labels import DltLabelError as IndicatorOpsError

        self.assertEqual(
            _operations([{"control": "page_fallback", "value": True}]),
            (("page_fallback", True),),
        )
        self.assertEqual(
            _operations(({"control": "duration_seconds", "value": 5},)),
            (("duration_seconds", 5),),
        )
        for bad in (
            [],
            None,
            "x",
            {},
            [{"control": "page_fallback", "value": True}] * (MAX_OPERATIONS + 1),
        ):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                IndicatorOpsError, r"Supply 1\.\.64 ordered indicator operations"
            ):
                _operations(bad)
        for bad in (
            [{"control": "page_fallback"}],
            [{"value": True}],
            [{"control": "page_fallback", "value": True, "extra": 1}],
            ["x"],
            [None],
        ):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                IndicatorOpsError, "Each indicator operation requires exactly"
            ):
                _operations(bad)
        with self.assertRaisesRegex(IndicatorOpsError, "Unknown classic DLT indicator"):
            _operations([{"control": "brightness", "value": True}])


class P5P6Round7P5NarrowTests(unittest.TestCase):
    """Round 7 P5 (issues 38-44): three genuinely-missing pure-offline slices.

    Each method pins branches with zero prior direct/message refs (verified via
    grep -rn across tests/ before writing):
    - key_options_cli.native_options (key_options_cli.py:100-111): grep -rn
      "key_options_cli.*native_options" tests/*.py -> 0 hits (the single
      "native_options" hit is dlt_cli.native_options in
      test_cli_dlt_indicators.py:33). Pure argparse registration, mirrors the
      round-2 offline_options pin; no spec, file, or I/O needed.
    - conversion._arguments move guards (conversion.py:43-46) plus thermostat
      _safe (thermostat_settings.py:577-581): grep -rn "Move source and
      destination must differ" tests/*.py -> 0 hits and grep -rn "same
      project" tests/*.py -> 0 hits (test_conversion.py:46-48 covers the same
      inputs via check_move with a generic ValueError only); grep -rn
      "thermostat_settings.*_safe" tests/*.py -> 0 hits (exercised only
      indirectly via _changed). Both are fixture-free value helpers failing
      before any C-Gate I/O (client.commands stays [] for conversion;
      _safe takes plain strings only).
    - sensors.snapshot + wireless_gateway.snapshot missing/invalid guards
      (sensors.py:194-204, wireless_gateway.py:244-256): grep -rn "Missing
      current sensor parameter" / "Invalid current sensor parameter" /
      "Missing current wireless gateway parameter" / "Invalid current wireless
      gateway parameter" tests/*.py -> 0 hits each. Mirrors the round-3/4
      dlt_display/dlt_indicators _snapshot pins. Fixtures are the shared
      synthetic SENPILL and WGATE layouts; sensors.snapshot propagates
      MacroError (a ValueError) for non-numeric text, so the Invalid pin uses
      out-of-range "999".
    No hardware, vendor EXE, C-Gate server, or decoded vendor spec needed.
    """

    def test_key_options_native_registers_all_actions(self):
        import argparse

        from cbus_toolkit import key_options_cli as key_cli

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="remote_action")
        key_cli.native_options(sub)
        self.assertEqual(set(sub.choices), set(key_cli.NATIVE_ACTIONS))
        self.assertEqual(len(sub.choices), 6)
        power_dests = {action.dest for action in sub.choices["power-up"]._actions}
        self.assertIn("broadcast", power_dests)
        self.assertIn("enable_blocks", power_dests)
        micro_dests = {action.dest for action in sub.choices["key-micro-functions"]._actions}
        self.assertIn("key_number", micro_dests)
        self.assertIn("jp", micro_dests)

    def test_conversion_move_guards_and_thermostat_safe(self):
        from cbus_toolkit.conversion import NativeConversions

        class RecordingClient:
            def __init__(self):
                self.commands = []

            def command(self, command):
                self.commands.append(command)
                line = "200 yes"
                return CGateResponse((line,), line, 200)

        client = RecordingClient()
        converter = NativeConversions(client)
        with self.assertRaisesRegex(ValueError, "same project"):
            converter._arguments("//TEST/254/p/20", destination="//OTHER/254/p/20")
        with self.assertRaisesRegex(ValueError, "must differ"):
            converter._arguments("//TEST/254/p/20", destination="//TEST/254/p/20")
        with self.assertRaisesRegex(ValueError, "must differ"):
            converter._arguments("//TEST/254/p/20", destination="//test/254/p/20")
        self.assertEqual(client.commands, [])
        self.assertEqual(ts_settings._safe("12"), 12)
        self.assertEqual(ts_settings._safe("0x10"), 16)
        self.assertEqual(ts_settings._safe(" 255 "), 255)
        for bad in ("bogus", "", "256", None, 12, True):
            with self.subTest(bad=bad):
                self.assertIsNone(ts_settings._safe(bad))

    def test_sensor_wireless_snapshot_guards_pin_messages(self):
        from cbus_toolkit.wireless_gateway import WirelessGatewayEditor

        sensor = Multisensor(sensor_fixture())
        defaults = sensor_fixture().defaults()
        missing = dict(defaults)
        del missing["PIRDark"]
        with self.assertRaisesRegex(SensorError, "Missing current sensor parameter"):
            sensor.snapshot(missing)
        with self.assertRaisesRegex(SensorError, "Missing current sensor parameter"):
            sensor.snapshot({})
        bad = dict(defaults)
        bad["PIRDark"] = "999"
        with self.assertRaisesRegex(SensorError, "Invalid current sensor parameter"):
            sensor.snapshot(bad)
        editor = WirelessGatewayEditor(wgate_fixture())
        wvals = wgate_fixture().defaults()
        wmissing = dict(wvals)
        del wmissing["MapWirelessRemotes"]
        with self.assertRaisesRegex(
            WirelessGatewayError, "Missing current wireless gateway parameter"
        ):
            editor.snapshot(wmissing)
        with self.assertRaisesRegex(
            WirelessGatewayError, "Missing current wireless gateway parameter"
        ):
            editor.snapshot({})
        winvalid = dict(wvals)
        winvalid["MapWirelessRemotes"] = "bogus"
        with self.assertRaisesRegex(
            WirelessGatewayError, "Invalid current wireless gateway parameter"
        ):
            editor.snapshot(winvalid)


class P5P6Round8NarrowTests(unittest.TestCase):
    """Round 8 (P5 issues 39/42/44): three genuinely-missing pure-offline slices.

    Each method pins a branch with zero prior direct refs (verified via
    grep -rn across tests/ before writing):
    - wireless_gateway.verify_native_schema happy + declaration/invalid
      refusals (wireless_gateway.py:160-168): grep -rn
      "verify_native_schema" tests/*.py -> only the sensors Round3 pin
      (test_p5p6_narrow_slices.py:525-552) and the sensors.py definition;
      zero calls to wireless_gateway.verify_native_schema. Fake
      Session.info('*') keeps it pure-offline (synthetic WGATE layout, no
      C-Gate/vendor EXE). Mirrors the round-3 sensors pin.
    - thermostat_settings.form_save direct replay
      (thermostat_settings.py:78-87): grep -rn "thermostat_settings import"
      tests/*.py -> only NativeThermostatSettings/admitted/plan_settings/
      _quoted_group_tag imports, never form_save; grep -rn
      "thermostat_settings.form_save" tests/*.py -> 0 hits.
      test_thermostat_post_load.py covers form_save_fans/scalars/
      temperatures individually and test_thermostat_settings.py covers
      plan_settings (which calls form_save internally), but nothing calls
      thermostat_settings.form_save directly. Plain int mapping + family
      string only; no spec store, C-Gate, or vendor EXE.
    - key_options_cli._editor guard + classic/coupler dispatch
      (key_options_cli.py:114-130): grep -rn "key_options_cli.*_editor"
      / "key_cli._editor" tests/*.py -> 0 hits (the only "_editor(" hits
      are the unrelated power_up_editor factory and edlt/iope editors).
      Synthetic XML roundtrip via UnitSpecStore keeps it pure-offline; no
      vendor spec dir needed.
    No hardware, vendor EXE, C-Gate server, or decoded vendor spec needed.
    """

    def test_wireless_verify_native_schema_accepts_and_refuses_offline(self):
        from test_macros import Session

        from cbus_toolkit.wireless_gateway import (
            FIELDS,
            WirelessGatewayError,
            verify_native_schema,
        )

        spec = wgate_fixture()
        live = Session(spec)
        self.assertIsNone(verify_native_schema(live, spec, FIELDS, WirelessGatewayError))

        class DoctypeReply:
            lines = ("347-<!DOCTYPE Parameters>",)

        class DoctypeSession:
            def info(self, _name):
                return DoctypeReply()

        with self.assertRaisesRegex(WirelessGatewayError, "Unsupported native schema"):
            verify_native_schema(DoctypeSession(), spec, FIELDS, WirelessGatewayError)

        class BrokenReply:
            lines = ("347-<Parameters><Param>",)

        class BrokenSession:
            def info(self, _name):
                return BrokenReply()

        with self.assertRaisesRegex(WirelessGatewayError, "Invalid native parameter schema"):
            verify_native_schema(BrokenSession(), spec, FIELDS, WirelessGatewayError)

    def test_thermostat_form_save_direct_replay_branches(self):
        from test_thermostat_settings import snapshot as thermo_snapshot

        ints = {
            name: int(value, 0)
            for name, value in thermo_snapshot(
                SendInterval=7, HeatingPlantFanOnDelay=13, DisplayBacklightIdleBrightness=1
            ).items()
        }
        prog = ts_settings.form_save(dict(ints), "programmable")
        self.assertEqual(prog["SendInterval"], 2)
        self.assertEqual(prog["HeatingPlantFanOnDelay"], 12)
        self.assertEqual(prog["DisplayBacklightIdleBrightness"], 2)
        values = dict(ints)
        values["HeatingPlantFanOnDelay"] = 21
        self.assertEqual(
            ts_settings.form_save(values, "programmable")["HeatingPlantFanOnDelay"], 24
        )
        for plant, damper, expected in ((2, 1, 2), (0, 1, 0)):
            with self.subTest(plant=plant):
                staged = dict(ints)
                staged["InternalPlantType"] = plant
                staged["DamperModulationEnable"] = damper
                self.assertEqual(
                    ts_settings.form_save(staged, "programmable")["DamperModulationEnable"],
                    expected,
                )
        basic = ts_settings.form_save(dict(ints), "basic")
        self.assertNotIn("SendInterval", basic)
        self.assertNotIn("TimeUnits", basic)
        self.assertIn("TimeUnits", prog)
        plain = ts_settings.form_save(dict(ints), "programmable")
        self.assertNotIn("TemperatureOffset", plain)
        celsius = ts_settings.form_save(
            dict(ints), "programmable", temperature_preference="celsius"
        )
        self.assertIn("TemperatureOffset", celsius)
        self.assertEqual(len(celsius) - len(plain), 15)
        frozen = dict(ints)
        ts_settings.form_save(frozen, "programmable")
        self.assertEqual(frozen, ints)

    def test_key_editor_requires_spec_dir_and_dispatches_classic_and_coupler(self):
        from cbus_toolkit import key_options_cli as key_cli
        from cbus_toolkit.input_power_up import COUPLER_LAYOUTS, CouplerPowerUp
        from cbus_toolkit.macros import ClassicKeys
        from test_input_options import fixture as input_fixture
        from test_macros import fixture as macro_fixture

        for action in ("custom-plan", "key-micro-functions", "power-up-plan", "neo-indicator-plan"):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, "spec-dir"):
                key_cli._editor(action, None, "KEY4.xml")

        def spec_to_xml(spec):
            parts = [
                '<?xml version="1.0"?><UnitSpecification><Type>'
                + spec.metadata.get("Type", "X")
                + "</Type><MinVersion>0</MinVersion><MaxVersion>9</MaxVersion><Parameters>"
            ]
            for name, parameter in spec.parameters.items():
                parts.append("<Param>")
                for key, value in parameter.fields.items():
                    parts.append(f"<{key}>{value}</{key}>")
                parts.append("</Param>")
            parts.append("</Parameters></UnitSpecification>")
            return "".join(parts)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "KEY4.xml").write_text(spec_to_xml(macro_fixture()))
            (root / "BCN4B.xml").write_text(
                spec_to_xml(input_fixture("BCN4B.xml", "BCN4B", COUPLER_LAYOUTS))
            )
            self.assertIsInstance(key_cli._editor("custom-plan", root, "KEY4.xml"), ClassicKeys)
            self.assertIsInstance(
                key_cli._editor("key-micro-functions", root, "KEY4.xml"), ClassicKeys
            )
            self.assertIsInstance(
                key_cli._editor("power-up-plan", root, "BCN4B.xml"), CouplerPowerUp
            )


class P5P6Round9NarrowTests(unittest.TestCase):
    """Round 9 (P5 issues 38-44): three highest-value pure-offline leftovers.

    Each method pins branches with zero prior message/dispatch refs (verified
    via grep -rn across tests/ before writing):
    - wireless_gateway.py:213 unit-type refusal
      (WirelessGatewayPlan.from_dict): grep -rn "Plan unit type is not
      admitted" tests/*.py -> 0 hits. test_wireless_gateway.py:241-243 pins
      format-mismatch, unit-type-mismatch and expected-AttributeError with a
      generic assertRaises only; Round4 P5 pins non-dict/missing-key/
      changes-bad-shape/firmware shapes but never the unit-type message.
      conversion.py:133 _convert backup-same-project: grep -rn "Backup
      project" tests/*.py -> 0 hits. test_conversion.py:50 covers
      convert_catalog backup TEST with a generic ValueError only; Round2
      pins align backup-same-project and Round7 pins move same-project/differ
      guards, but never the _convert backup guard, which fails before any
      C-Gate I/O (client.commands stays []).
    - sensors.py:186,192 __init__ guards: grep -rn "Use SENPILL_ST7" /
      "Unsupported sensor parameter layout" tests/*.py -> 0 hits.
      test_sensors.py:165,170 covers the same inputs with a generic
      assertRaises only. Both messages are pinned here with the shared
      synthetic SENPILL layout.
    - key_options_cli._editor remaining dispatches
      (key_options_cli.py:119-135): Round8 pins the spec-dir guard plus
      classic (custom-plan/key-micro-functions) and coupler (power-up-plan
      BCN4B) branches only. grep for ExtendedKeys, NeoIndicatorOptions,
      NeoIndicatorStyles, NeoIndicatorEditor, KeyPowerUpBroadcast dispatches in
      tests/test_p5p6_narrow_slices.py -> 0 hits (only a docstring
      mention). Synthetic XML roundtrip via UnitSpecStore keeps it
      pure-offline; no vendor spec dir needed.
    No hardware, vendor EXE, C-Gate server, or decoded vendor spec needed.
    """

    def test_wireless_unit_type_and_conversion_backup_guard_messages(self):
        from cbus_toolkit.wireless_gateway import PLAN_FORMAT, UNIT_TYPE, WirelessGatewayPlan

        base = {"format": PLAN_FORMAT, "unit_type": UNIT_TYPE, "expected": {}, "changes": {}}
        for bad in ({**base, "unit_type": "WGATE5N"}, {"format": PLAN_FORMAT, "expected": {}, "changes": {}}):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                WirelessGatewayError, "Plan unit type is not admitted"
            ):
                WirelessGatewayPlan.from_dict(bad)

        from cbus_toolkit.conversion import NativeConversions

        class RecordingClient:
            def __init__(self):
                self.commands = []

            def command(self, command):
                self.commands.append(command)
                line = "200 yes"
                return CGateResponse((line,), line, 200)

        client = RecordingClient()
        converter = NativeConversions(client)
        prepared = converter._arguments(
            "//TEST/254/p/20", unit_type="DIMDU4", catalog_number="L5504D2U"
        )
        for backup in ("TEST", "test"):
            with self.subTest(backup=backup), self.assertRaisesRegex(
                ValueError, "Backup project must differ from the conversion project"
            ):
                converter._convert(prepared, backup_project=backup)
        self.assertEqual(client.commands, [])

    def test_sensor_init_guards_pin_messages(self):
        from dataclasses import replace

        spec = sensor_fixture()
        with self.assertRaisesRegex(SensorError, r"Use SENPILL_ST7\.xml"):
            Multisensor(replace(spec, filename="SENPILLA.xml"))
        bad = replace(
            spec.get("PIRDark"),
            fields=dict(spec.get("PIRDark").fields, Address="55"),
        )
        with self.assertRaisesRegex(SensorError, "Unsupported sensor parameter layout: PIRDark"):
            Multisensor(replace(spec, parameters=dict(spec.parameters, PIRDark=bad)))

    def test_key_editor_dispatches_remaining_branches(self):
        from cbus_toolkit import key_options_cli as key_cli
        from cbus_toolkit.extended_macros import LAYOUTS as EXT_LAYOUTS
        from cbus_toolkit.extended_macros import ExtendedKeys
        from cbus_toolkit.input_power_up import BROADCAST_LAYOUTS, KeyPowerUpBroadcast
        from cbus_toolkit.neo_indicator_editor import LAYOUTS as EDITOR_LAYOUTS
        from cbus_toolkit.neo_indicator_editor import NeoIndicatorEditor
        from cbus_toolkit.neo_indicators import OPTION_LAYOUTS, STYLE_LAYOUTS, NeoIndicatorOptions
        from cbus_toolkit.neo_indicators import NeoIndicatorStyles
        from cbus_toolkit.unitspec import ParameterSpec, UnitSpec

        def make_spec(filename, unit_type, layouts):
            parameters = {}
            for name, shape in layouts.items():
                if len(shape) == 6:
                    kind, address, count, bits, offset, skip = shape
                else:
                    address, count, bits, offset, skip = shape
                    kind = "int"
                fields = {
                    "Name": name, "Type": kind, "Address": str(address),
                    "ArraySize": str(count), "BitSize": str(bits),
                    "BitAddress": str(offset), "ArraySkip": str(skip),
                    "DefaultValue": " ".join(["0"] * count),
                }
                parameters[name] = ParameterSpec(name, kind, "synthetic.xml", fields)
            return UnitSpec(filename, {"Type": unit_type}, ("synthetic.xml",), parameters)

        def spec_to_xml(spec):
            parts = [
                '<?xml version="1.0"?><UnitSpecification><Type>'
                + spec.metadata.get("Type", "X")
                + "</Type><MinVersion>0</MinVersion><MaxVersion>9</MaxVersion><Parameters>"
            ]
            for name, parameter in spec.parameters.items():
                parts.append("<Param>")
                for key, value in parameter.fields.items():
                    parts.append(f"<{key}>{value}</{key}>")
                parts.append("</Param>")
            parts.append("</Parameters></UnitSpecification>")
            return "".join(parts)

        specs = {
            "KEYM4.xml": make_spec("KEYM4.xml", "KEYM4", EXT_LAYOUTS),
            "KEYB4.xml": make_spec("KEYB4.xml", "KEYB4", OPTION_LAYOUTS),
            "KEYV2.xml": make_spec("KEYV2.xml", "KEYV2", STYLE_LAYOUTS),
            "KEYM8.xml": make_spec("KEYM8.xml", "KEYM8", EDITOR_LAYOUTS),
            "KEYBC4.xml": make_spec("KEYBC4.xml", "KEYBC4", BROADCAST_LAYOUTS),
        }
        cases = (
            ("neo-custom-plan", "KEYM4.xml", ExtendedKeys),
            ("neo-key-micro-functions", "KEYM4.xml", ExtendedKeys),
            ("neo-indicator-plan", "KEYB4.xml", NeoIndicatorOptions),
            ("neo-indicators", "KEYB4.xml", NeoIndicatorOptions),
            ("neo-style-plan", "KEYV2.xml", NeoIndicatorStyles),
            ("neo-indicator-styles", "KEYV2.xml", NeoIndicatorStyles),
            ("power-up-plan", "KEYBC4.xml", KeyPowerUpBroadcast),
            ("power-up", "KEYBC4.xml", KeyPowerUpBroadcast),
            ("neo-indicator-editor-plan", "KEYM8.xml", NeoIndicatorEditor),
            ("neo-indicator-editor", "KEYM8.xml", NeoIndicatorEditor),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, spec in specs.items():
                (root / name).write_text(spec_to_xml(spec), encoding="utf-8")
            for action, filename, expected in cases:
                with self.subTest(action=action):
                    self.assertIsInstance(key_cli._editor(action, root, filename), expected)


class P5P6Round10NarrowTests(unittest.TestCase):
    """Round 10 (P5 issues 41/44): integer-domain + assignment-dict guards.

    Each method pins branches with zero prior message refs (verified via
    grep -rn across tests/ before writing):
    - sensors.py:271,275,284,291,300,304 _integer domains: grep -rn "Timer
      seconds must be|Group must be|Margin percent must be|Target lux must
      be|Occupancy enable group must be|enabled_when must be" tests/*.py ->
      0 hits each. test_sensors.py:153-159 covers the same inputs with a
      generic assertRaises(ValueError) only; Round4 P5 pins only Virtual-key
      /Block messages. Synthetic SENPILL fixture; fails before any I/O.
    - wireless_gateway.py:368-378 _assign dict guards plus parse_assignment
      text/integer messages: grep -rn "key function must be|application must
      be primary|Key assignment must be text|numbers must be integers"
      tests/*.py -> 0 hits each. test_wireless_gateway.py:111-114 covers
      parse_assignment bad cases (including non-string 7) with a generic
      assertRaises only; no test ever passes a dict assignment, so the
      _assign dict branches are never exercised. Synthetic WGATE fixture /
      plain strings only; fails before any I/O.
    No hardware, vendor EXE, C-Gate server, or decoded vendor spec needed.
    """

    def test_sensor_integer_domains_pin_messages(self):
        spec = sensor_fixture()
        sensor = Multisensor(spec)
        defaults = spec.defaults()
        with self.assertRaisesRegex(SensorError, "Timer seconds must be"):
            sensor.plan(defaults, key=3, event="night", group=17, timer_seconds=99999)
        with self.assertRaisesRegex(SensorError, "Timer seconds must be"):
            sensor.plan(defaults, key=3, event="night", group=17, timer_seconds=True)
        with self.assertRaisesRegex(SensorError, "Group must be"):
            sensor.plan(defaults, key=3, event="night", group=999)
        with self.assertRaisesRegex(SensorError, "Margin percent must be"):
            sensor.plan(defaults, margin_percent=101)
        with self.assertRaisesRegex(SensorError, "Target lux must be"):
            sensor.plan(defaults, target_lux=9999)
        with self.assertRaisesRegex(SensorError, "Occupancy enable group must be"):
            sensor.plan(defaults, enable_group=999)
        with self.assertRaisesRegex(SensorError, "enabled_when must be on or off"):
            sensor.plan(defaults, enabled_when="bogus")

    def test_wireless_assign_dict_and_parse_messages(self):
        from cbus_toolkit.wireless_gateway import WirelessGatewayEditor
        from test_wireless_gateway import remote_switch

        editor = WirelessGatewayEditor(wgate_fixture())
        values = remote_switch().values()
        with self.assertRaisesRegex(WirelessGatewayError, "key function must be"):
            editor.plan(values, remote=1, serial=1, keys={1: {"function": "bogus"}})
        with self.assertRaisesRegex(WirelessGatewayError, "key function must be"):
            editor.plan(values, remote=1, serial=1, keys={1: {}})
        with self.assertRaisesRegex(
            WirelessGatewayError, "application must be primary or secondary"
        ):
            editor.plan(
                values,
                remote=1,
                serial=1,
                keys={1: {"function": "group", "group": 1, "application": "bogus"}},
            )
        with self.assertRaisesRegex(WirelessGatewayError, "Key assignment must be text"):
            parse_assignment(7)
        with self.assertRaisesRegex(
            WirelessGatewayError, "Key assignment numbers must be integers"
        ):
            parse_assignment("scene-set:x")


class P5P6Round11NarrowTests(unittest.TestCase):
    """Round 11 (P5 issue 44): slot/scene-dict/parse-fallback guards.

    Each method pins branches with zero prior message refs (verified via
    grep -rn across tests/ before writing):
    - wireless_gateway.py:354 _integer slot domain: grep -rn "Slot must"
      tests/*.py -> 0 hits (only lowercase "slot" in comments/show-view
      field names, never the "Slot must be an integer in 1..16" message).
      test_wireless_gateway.py:161-170 pins Remote/Key/group/also-selected/
      require-a-remote messages but never passes a bad slot, so the Slot
      branch is never exercised. Synthetic WGATE fixture; fails before any
      I/O.
    - wireless_gateway.py:388 _integer scene domain for dict assignments:
      grep -rn "scene must be" tests/*.py -> 0 hits (existing "scene 2 has
      no trigger group" / "scene 3 is not configured" pins are the later
      _assign save-guard messages, not the _integer domain message; no test
      ever passes a dict assignment with a scene value, so the branch is
      never exercised). Same synthetic fixture; fails before any I/O.
    - wireless_gateway.py:156 parse_assignment fallback: grep -rn "must be
      group:G" tests/*.py -> 0 hits and grep -rn "Key assignment must be
      group" tests/*.py -> 0 hits. test_wireless_gateway.py:111-114 covers
      the same bad inputs ("scene:1", "group", "group:1:2:3") with a generic
      assertRaises only; Round10 pins only the text/integer messages. Plain
      strings only; fails before any I/O.
    No hardware, vendor EXE, C-Gate server, or decoded vendor spec needed.
    """

    def test_wireless_slot_and_scene_dict_domains_pin_messages(self):
        from cbus_toolkit.wireless_gateway import WirelessGatewayEditor
        from test_wireless_gateway import remote_switch

        editor = WirelessGatewayEditor(wgate_fixture())
        values = remote_switch().values()
        for slots in ({17: "group:1"}, {0: "group:1"}, {True: "group:1"}):
            with self.subTest(slots=slots), self.assertRaisesRegex(
                WirelessGatewayError, "Slot must be an integer in 1\\.\\.16"
            ):
                editor.plan(values, remote=1, serial=1, slots=slots)
        for scene in (99, True, 0, 16):
            with self.subTest(scene=scene), self.assertRaisesRegex(
                WirelessGatewayError, "scene must be an integer in 1\\.\\.15"
            ):
                editor.plan(
                    values,
                    remote=1,
                    serial=1,
                    keys={1: {"function": "scene-set", "scene": scene}},
                )

    def test_wireless_parse_fallback_pin_message(self):
        for bad in ("group", "scene:1", "bogus", "group:1:2:3"):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                WirelessGatewayError, r"Key assignment must be group:G"
            ):
                parse_assignment(bad)


class P5P6Round12NarrowTests(unittest.TestCase):
    """Round 12 (P5 issue 43): conversion CHECK transport-error guard.

    Pins the single highest-value remaining pure-offline branch among the
    round-12 candidates (verified via grep -rn across tests/ before writing):
    - conversion._check unexpected response (conversion.py:60-61): grep -rn
      "Unexpected native conversion check response" tests/*.py -> 0 hits.
      test_conversion.py covers only code 200 (allowed) and 301 (rejected)
      via its RecordingClient; no test ever returns another code, so the
      ConversionError branch is never exercised.
    - sensors/wireless verify_native_schema duplicate/type-mismatch
      (sensors.py:142-148, wireless_gateway.py:173-179): grep -rn "Duplicate
      native parameter schema" / "Native parameter type mismatch" tests/*.py
      -> 0 hits each. Defensive against a native server emitting a corrupt
      schema that never occurs in practice; happy + declaration/invalid
      paths are already pinned by Round3/Round8. Lower value than a
      transport error that C-Gate can genuinely return (bad project, bad
      args, server failure).
    - key_options_cli offline() snapshot-identity branches
      (key_options_cli.py:168-198): grep -rn "Snapshot identity differs from
      the explicit" / "Snapshot format differs from the selected editor" /
      "Snapshot format or unit type differs" tests/*.py -> 0 hits each.
      Six narrow UI-validation sub-branches needing temp files plus a spec
      roundtrip; similar snapshot guards are already heavily pinned in
      cli.py/dlt_cli.py. Lower signal per branch than the single transport
      guard pinned here.
    A non-200/301 CHECK reply must raise instead of being misread as a
    rejection; the check fails before any CONVERTUNIT CONVERT or backup
    I/O. No hardware, vendor EXE, C-Gate server, or decoded spec needed:
    a recording fake client returns 400 for CONVERTUNIT CHECK and 200 for
    PROJECT USE only.
    """

    def test_conversion_check_unexpected_response_raises_before_mutation(self):
        from cbus_toolkit.conversion import ConversionError

        class UnexpectedClient:
            def __init__(self):
                self.commands = []

            def command(self, command):
                self.commands.append(command)
                if command.startswith("CONVERTUNIT CHECK"):
                    line = "400 bad-request"
                    return CGateResponse((line,), line, 400)
                line = "200 ok"
                return CGateResponse((line,), line, 200)

        for call in (
            lambda converter: converter.check_catalog("//TEST/254/p/20", "DIMDU4", "L5504D2U"),
            lambda converter: converter.check_move("//TEST/254/p/20", "//TEST/254/p/21"),
        ):
            client = UnexpectedClient()
            converter = NativeConversions(client)
            with self.subTest(call=call), self.assertRaisesRegex(
                ConversionError, "Unexpected native conversion check response"
            ):
                call(converter)
            self.assertEqual(
                client.commands,
                [
                    "PROJECT USE TEST",
                    client.commands[1],
                ],
            )
            self.assertTrue(client.commands[1].startswith("CONVERTUNIT CHECK "))
            self.assertFalse(
                any(
                    command.startswith("CONVERTUNIT CONVERT") or command.startswith("PROJECT SAVE")
                    for command in client.commands
                )
            )


if __name__ == "__main__":
    unittest.main()
