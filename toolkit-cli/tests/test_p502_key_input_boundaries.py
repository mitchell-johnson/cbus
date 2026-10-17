"""P5.02 (#39) pure-offline boundary pins for the key/input editor slice.

The audit-identified gap in ``key_options_cli.py``, ``extended_macros.py``
(``ExtendedKeys``), ``neo_indicators.py`` (``NeoIndicatorOptions``) and
``input_power_up.py`` (``CouplerPowerUp``, ``KeyPowerUpBroadcast``) is
join/IR/virtual key columns, per-unit indicator scope, NightlightColour and
power-up breadth. No committed receipt, fixture or document describes the
unadmitted behavior, so the Python model must not invent it. These pins lock
the refusal and preservation surfaces and name the exact next evidence needed,
following the KeyglHydraBoundaryTests pattern in tests/test_barcode_scanner.py.
They establish no original GUI, native-runtime or hardware acceptance.

Ordinary Neo editor Apply/OK/Cancel histories (EC1-EC4) stay open and are not
pinned here; parent-form save composition belongs to the save/program flows.
"""
import argparse
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import test_extended_macros as neo_tests
import test_input_options as input_tests
import test_macros as classic_tests
from cbus_toolkit import key_options_cli, macros
from cbus_toolkit import extended_macros as neo_macros
from cbus_toolkit import neo_indicator_editor
from cbus_toolkit.extended_macros import ExtendedKeys, PROFILES
from cbus_toolkit.input_power_up import (BROADCAST_LAYOUTS, COUPLER_LAYOUTS, CouplerPowerUp,
                                         KeyPowerUpBroadcast, power_up_editor)
from cbus_toolkit.macros import ClassicKeys, MacroError, _READ_FIELDS
from cbus_toolkit.neo_indicators import (OPTION_LAYOUTS, STYLE_LAYOUTS, NeoIndicatorOptions,
                                         NeoIndicatorStyles)
from cbus_toolkit.pp_editor import PPEditError
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec

ROOT = Path(__file__).resolve().parents[1]
PRESET_RECEIPT = json.loads((ROOT / "research/fixtures/key-preset-family-equivalence.json").read_text())
MACROS_DOC = (ROOT / "docs/macros.md").read_text()
EXTENDED_DOC = (ROOT / "docs/extended-macros.md").read_text()

# Identifiers a join/IR/virtual key-column proof would have to contain. The
# committed preset receipt pins MaximumKeyCount subsets and layouts only.
MISSING_COLUMN_EVIDENCE = ("TddKey4", "TddNeoPro", "TfrmKeyMicroFunctions", "ColumnCount",
                           "JoinKey", "VirtualKey", "IRKey", "JoinColumn", "VirtualColumn")
UNADMITTED_CLI_FLAGS = ("--join", "--virtual", "--ir-bank", "--scene", "--nightlight-colour")


def option_help(configure):
    parser = argparse.ArgumentParser(prog="cbus-toolkit keys")
    configure(parser)
    return parser.format_help()


def power_spec(filename, unit_type, layouts):
    return input_tests.fixture(filename, unit_type, layouts)


class JoinIrVirtualColumnBoundaryTests(unittest.TestCase):
    """Join/IR/virtual micro-function columns stay outside both key editors.

    Next: a static EXE/MAP source review of the hosting grids (classic
    ``TddKey4``, Neo ``TddNeoPro``/``TddKeyM8`` column counts) must pin the
    extra columns in a new committed receipt before either ``plan`` or
    ``plan_micro_functions`` admits keys beyond MaximumKeyCount. Original GUI
    history and physical buttons remain open under #39.
    """

    def test_committed_preset_receipt_holds_no_key_grid_column_evidence(self):
        # Next: research/key_preset_families.py (or a sibling review) must pin
        # the TddKey4/TddNeoPro column routines in this receipt first.
        self.assertEqual(PRESET_RECEIPT["format"], "cbus-key-preset-family-equivalence-v1")
        text = json.dumps(PRESET_RECEIPT)
        for identifier in MISSING_COLUMN_EVIDENCE:
            with self.subTest(identifier=identifier):
                self.assertNotIn(identifier, text)
        # The receipt's key-count bound is Toolkit MaximumKeyCount only.
        self.assertIn("MaximumKeyCount", PRESET_RECEIPT["virtual_slots"])

    def test_docs_record_join_ir_virtual_columns_as_unadmitted(self):
        # The committed docs keep these columns in their out-of-scope lists;
        # admitting them first requires original-instruction evidence.
        self.assertIn("no join or virtual columns", MACROS_DOC)
        self.assertIn("Join, IR and", EXTENDED_DOC)
        self.assertIn("virtual key columns are not admitted", EXTENDED_DOC)

    def test_key_editor_modules_expose_no_join_virtual_column_surface(self):
        # Next: the grid column routines in macros.py / extended_macros.py,
        # only after the receipt above pins them. InfraRedBank below is a
        # preserved parameter, not an editable key column.
        for module in (macros, neo_macros):
            with self.subTest(module=module.__name__):
                leaked = [name for name in dir(module)
                          if "join" in name.lower() or "virtual" in name.lower()]
                self.assertEqual(leaked, [])

    def test_classic_keys_stop_at_maximum_key_count_and_preserve_infrared_bank(self):
        spec = classic_tests.fixture("KEYIR4", extra=(("InfraRedBank", 0x60, 1, 8, 0, 0, [3]),))
        keys = ClassicKeys(spec)
        current = spec.defaults()
        for method in (keys.plan, keys.plan_micro_functions):
            with self.subTest(method=method.__name__):
                with self.assertRaisesRegex(MacroError, "4 physical key"):
                    if method.__name__ == "plan":
                        method(current, key=5, preset="on")
                    else:
                        method(current, key=5, stages={"jp": 1})
        plan = keys.plan(current, key=4, preset="dimmer", group=9, block=4)
        self.assertLessEqual(set(plan.changes), set(_READ_FIELDS))
        session = classic_tests.Session(spec)
        keys.apply(session, keys.plan(session.values(), key=4, preset="dimmer", group=9, block=4))
        self.assertEqual(session.current["InfraRedBank"], "3")
        self.assertEqual([name for name, _ in session.calls if name == "InfraRedBank"], [])

    def test_neo_keys_stop_at_maximum_key_count(self):
        for filename, unit_type, count in (("KEYM4.xml", "KEYM4", 4), ("KEYV1.xml", "KEYV1", 1)):
            with self.subTest(spec=filename):
                keys = ExtendedKeys(neo_tests.fixture(filename, unit_type))
                current = keys.spec.defaults()
                with self.assertRaisesRegex(MacroError, f"{count} supported physical key"):
                    keys.plan(current, key=count + 1, preset="on")
                with self.assertRaisesRegex(MacroError, f"{count} supported physical key"):
                    keys.plan_micro_functions(current, key=count + 1, stages={"jp": 1})


class NightlightColourSplitBoundaryTests(unittest.TestCase):
    """NightlightColour belongs to the per-unit panel, not the bulk pages.

    The bulk Indicator Options and Styles/Colours workflows preserve the raw
    NightlightColour byte; only ``NeoIndicatorEditor`` (``TfrmNeoInputIndicators8``,
    30 ordinary profiles at firmware 2.5.00) edits it, and only where its
    nightlight_colour radio is visible and enabled.

    Next: a static source review of the bulk pages (``TfrmNeoIndicatorOptions``,
    ``TfrmNeoLED`` before-save) must pin whether those wizards touch
    NightlightColour before ``neo_indicators.py`` models it.
    """

    def test_bulk_layouts_exclude_nightlight_colour_fields(self):
        for layouts in (OPTION_LAYOUTS, STYLE_LAYOUTS):
            with self.subTest(layouts=dict(layouts)):
                self.assertNotIn("NightlightColour", layouts)
                self.assertNotIn("EnableNightlightControl", layouts)

    def test_bulk_plans_never_emit_nightlight_fields(self):
        option_cases = (("KEYM4.xml", "KEYM4"), ("KEYB4.xml", "KEYB4"), ("KEYA3.xml", "KEYA3"))
        option_sets = ({"brightness": "fixed", "brightness_percent": 50},
                       {"brightness": "group", "brightness_group": 255},
                       {"brightness": "first_block"},
                       {"key_press_level": 9, "key_press_seconds": 4, "nightlight": True,
                        "ignore_first_key_press": True, "timer_flash": False, "id_backlight": True})
        for filename, unit_type in option_cases:
            options = NeoIndicatorOptions(power_spec(filename, unit_type, OPTION_LAYOUTS))
            current = options.spec.defaults()
            for settings in option_sets:
                with self.subTest(spec=filename, settings=settings):
                    try:
                        plan = options.plan(current, **settings)
                    except PPEditError:
                        continue
                    self.assertLessEqual(set(plan.changes), set(OPTION_LAYOUTS))
        for filename, unit_type in (("KEYM4.xml", "KEYM4"), ("KEYV2.xml", "KEYV2")):
            styles = NeoIndicatorStyles(power_spec(filename, unit_type, STYLE_LAYOUTS))
            with self.subTest(spec=filename):
                plan = styles.plan(styles.spec.defaults(), colour="blue", style="status_dual")
                self.assertLessEqual(set(plan.changes), set(STYLE_LAYOUTS))

    def test_bulk_group_255_keeps_the_unused_sentinel(self):
        options = NeoIndicatorOptions(power_spec("KEYM4.xml", "KEYM4", OPTION_LAYOUTS))
        plan = options.plan(options.spec.defaults(), brightness="group", brightness_group=255)
        self.assertEqual(plan.changes, {"IndicatorBrightness": (0,)})
        self.assertEqual(plan.as_dict()["brightness"], {"source": "group", "percent": None, "group": 255})

    def test_bulk_apply_preserves_the_nightlight_colour_byte(self):
        layouts = dict(OPTION_LAYOUTS)
        layouts["NightlightColour"] = ("bit", 0x34, 1, 1, 2, 0)
        parameters = {}
        for name, (kind, address, count, bits, offset, skip) in layouts.items():
            default = "1" if name == "NightlightColour" else input_tests.DEFAULTS[name]
            fields = {"Name": name, "Type": kind, "Address": str(address), "ArraySize": str(count),
                      "BitSize": str(bits), "BitAddress": str(offset), "ArraySkip": str(skip),
                      "DefaultValue": default}
            parameters[name] = ParameterSpec(name, kind, "fixture.xml", fields)
        spec = UnitSpec("KEYB4.xml", {"Type": "KEYB4"}, ("fixture.xml",), parameters)
        options = NeoIndicatorOptions(spec)
        session = classic_tests.Session(spec)
        result = options.configure(session, key_press_level=9, key_press_seconds=4, nightlight=True)
        self.assertTrue(result["verified"])
        self.assertEqual(session.current["NightlightColour"], "1")
        self.assertEqual([name for name, _ in session.calls if name == "NightlightColour"], [])

    def test_per_unit_editor_owns_the_nightlight_colour_control(self):
        # The admitted per-unit surface keeps the split explicit: bulk plans
        # above preserve the byte, this panel edits it through ordered
        # callbacks. Its visibility/enabled rules are pinned in
        # tests/test_neo_indicator_editor.py.
        self.assertIn("NightlightColour", neo_indicator_editor.LAYOUTS)
        self.assertIn("nightlight_colour", neo_indicator_editor.GLOBAL_CONTROLS)

    def test_cli_bulk_options_expose_no_nightlight_colour_flag(self):
        for configure in (key_options_cli._indicator_options, key_options_cli._style_options):
            with self.subTest(configure=configure.__name__):
                text = option_help(configure)
                for flag in UNADMITTED_CLI_FLAGS:
                    self.assertNotIn(flag, text)


class PowerUpBreadthBoundaryTests(unittest.TestCase):
    """Power-up broadcast covers six units; every other family is refused.

    Coupler bytes follow the bistable-key rule, broadcast flags follow the
    unit-wide checkbox. IOPE occupancy controllers use a different enable rule
    owned by #40 (``iope_settings.py``) and stay refused here.

    Next: a ``GroupAddressBroadcastPropertyEnabled`` source review must pin any
    further unit before ``power_up_editor`` admits it; the IOPE rule must land
    in ``iope_settings.py`` first.
    """

    def test_coupler_keyv1sp_single_key_plan_stays_offline(self):
        spec = power_spec("KEYV1SP.xml", "KEYV1SP", COUPLER_LAYOUTS)
        editor = CouplerPowerUp(spec)
        self.assertEqual(editor.key_count, 1)
        current = dict(spec.defaults(), BistableSwitchBlock="1", BlockAllocation="5 0 0 0 0 0 0 0",
                       GroupAssertOnPowerup="0")
        self.assertEqual(editor.bistable_blocks(editor.snapshot(current)), {1, 3})
        plan = editor.plan(current, enable=[1, 3])
        self.assertEqual(plan.changes["GroupAssertOnPowerup"], (0b101,))
        # A mask bit for the nonexistent second key contributes no blocks.
        missing = dict(current, BistableSwitchBlock="2")
        self.assertEqual(editor.bistable_blocks(editor.snapshot(missing)), set())
        with self.assertRaisesRegex(PPEditError, "not used by a bistable key"):
            editor.plan(missing, enable=[1])
        with self.assertRaisesRegex(PPEditError, "not used by a bistable key"):
            editor.plan(current, enable=[2])

    def test_power_up_editor_admits_exactly_the_six_documented_units(self):
        for filename, unit_type, editor_type in (("BCN2B.xml", "BCN2B", CouplerPowerUp),
                                                 ("BCN4B.xml", "BCN4B", CouplerPowerUp),
                                                 ("KEYV1SP.xml", "KEYV1SP", CouplerPowerUp),
                                                 ("KEYBC2.xml", "KEYBC2", KeyPowerUpBroadcast),
                                                 ("KEYBC4.xml", "KEYBC4", KeyPowerUpBroadcast),
                                                 ("DINAUX4.xml", "DINAUX4", KeyPowerUpBroadcast)):
            with self.subTest(unit=unit_type):
                layouts = COUPLER_LAYOUTS if issubclass(editor_type, CouplerPowerUp) else BROADCAST_LAYOUTS
                self.assertIsInstance(power_up_editor(power_spec(filename, unit_type, layouts)), editor_type)

    def test_power_up_editor_refuses_all_other_key_families(self):
        refused = [("KEY1.xml", "KEY1"), ("KEY2.xml", "KEY2"), ("KEY4.xml", "KEY4"),
                   ("KEYIR1.xml", "KEYIR1"), ("KEYIR4.xml", "KEYIR4"), ("KEYAUX4.xml", "KEYAUX4"),
                   ("BCNC4A.xml", "BCNC4A"), ("BCNC4B.xml", "BCNC4B"),
                   ("IOPE1R1.xml", "IOPE1R1"), ("IOPE2R2.xml", "IOPE2R2"), ("IOPE2C4.xml", "IOPE2C4"),
                   ("BCN4B_A.xml", "BCN4B"), ("KEYBC4_A.xml", "KEYBC4")]
        refused.extend((filename, filename[:-4]) for filename in PROFILES)
        for filename, unit_type in refused:
            with self.subTest(unit=unit_type or filename):
                with self.assertRaises(PPEditError):
                    power_up_editor(power_spec(filename, unit_type, BROADCAST_LAYOUTS))

    def test_cli_power_up_options_cover_only_the_two_admitted_shapes(self):
        text = option_help(key_options_cli._power_up_options)
        for flag in ("--enable-block", "--disable-block", "--broadcast"):
            self.assertIn(flag, text)
        for flag in UNADMITTED_CLI_FLAGS:
            self.assertNotIn(flag, text)


class SceneBindingBoundaryTests(unittest.TestCase):
    """Scene keys are read-only for micro-functions; presets clear one bit.

    Classic presets have no scene-key surface at all: the committed receipt's
    classic workflow omits SceneKeySelector while the Neo workflow owns it.
    Persistent scene tables and trigger bindings need their own source proof.

    Next: a scene-table source review must pin stored-scene bindings before
    either key editor models them; original scene GUI history stays open.
    """

    def test_classic_workflow_has_no_scene_key_surface(self):
        # Next: a scene-table receipt must pin classic stored scenes first.
        self.assertNotIn("SceneKeySelector", _READ_FIELDS)
        self.assertNotIn("SceneKeySelector", PRESET_RECEIPT["families"]["classic"]["workflow_parameters"])
        self.assertIn("SceneKeySelector", PRESET_RECEIPT["families"]["neo"]["workflow_parameters"])

    def test_neo_preset_clears_while_micro_functions_refuse_scene_keys(self):
        keys = ExtendedKeys(neo_tests.fixture())
        scene = dict(keys.spec.defaults(), SceneKeySelector="0 1 0 0 0 0 0 0")
        with self.assertRaisesRegex(MacroError, "read-only"):
            keys.plan_micro_functions(scene, key=2, stages={"jp": 1})
        plan = keys.plan(scene, key=2, preset="dimmer")
        self.assertEqual(plan.changes["SceneKeySelector"], (0,) * 8)

    def test_cli_stage_options_expose_no_scene_surface(self):
        text = option_help(key_options_cli._stage_options)
        for flag in ("--scene", "--join", "--virtual"):
            self.assertNotIn(flag, text)


class KeyOptionsCliRoutingTests(unittest.TestCase):
    """Pure-offline routing and validation inside key_options_cli.py."""

    def test_micro_function_domain_listing_needs_no_spec(self):
        result, status = key_options_cli.offline(SimpleNamespace(action="micro-functions"))
        self.assertEqual(status, 0)
        self.assertEqual(result["stages"], ["JPCommand", "SRCommand", "LPCommand", "LRCommand"])
        self.assertEqual(len(result["micro_functions"]), 16)

    def test_stage_value_parsing_accepts_names_decimals_and_hex(self):
        args = SimpleNamespace(key_number=2, jp="on", sr="0x3", lp=None, lr="15")
        method, options = key_options_cli._settings("custom-plan", args, None)
        self.assertEqual(method, "micro_functions")
        self.assertEqual(options, {"key": 2, "stages": {"jp": "on", "sr": 3, "lr": 15}})

    def test_settings_refusals(self):
        coupler = CouplerPowerUp(power_spec("BCN4B.xml", "BCN4B", COUPLER_LAYOUTS))
        broadcast = KeyPowerUpBroadcast(power_spec("KEYBC4.xml", "KEYBC4", BROADCAST_LAYOUTS))
        base = {"key_number": 1, "jp": None, "sr": None, "lp": None, "lr": None, "enable_blocks": [],
                "disable_blocks": [], "broadcast": None, "brightness": None, "brightness_percent": None,
                "brightness_group": None, "key_press_level": None, "key_press_seconds": None,
                "nightlight": None, "ignore_first_key_press": None, "timer_flash": None,
                "id_backlight": None, "colour": "blue", "style": None}
        with self.subTest(case="coupler broadcast"):
            args = SimpleNamespace(**{**base, "broadcast": True})
            with self.assertRaisesRegex(ValueError, "not --broadcast"):
                key_options_cli._settings("power-up-plan", args, coupler)
        with self.subTest(case="broadcast unit blocks"):
            args = SimpleNamespace(**{**base, "enable_blocks": [1], "broadcast": True})
            with self.assertRaisesRegex(ValueError, "--broadcast or --no-broadcast only"):
                key_options_cli._settings("power-up-plan", args, broadcast)
        with self.subTest(case="broadcast unit missing switch"):
            args = SimpleNamespace(**base)
            with self.assertRaisesRegex(ValueError, "--broadcast or --no-broadcast only"):
                key_options_cli._settings("power-up-plan", args, broadcast)
        with self.subTest(case="indicator without options"):
            args = SimpleNamespace(**base)
            with self.assertRaisesRegex(ValueError, "at least one indicator option"):
                key_options_cli._settings("neo-indicator-plan", args, None)
        method, options = key_options_cli._settings(
            "power-up-plan", SimpleNamespace(**{**base, "broadcast": False}), broadcast)
        self.assertEqual((method, options), ("plan", {"broadcast": False}))

    def test_controls_guards(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            path = folder / "controls.json"
            path.write_text('[{"led": 1, "style": "always_on"}]')
            self.assertEqual(key_options_cli._controls(path), [{"led": 1, "style": "always_on"}])
            path.write_text('{"led": 1}')
            with self.assertRaisesRegex(ValueError, "JSON array"):
                key_options_cli._controls(path)
            path.write_text('{"a": 1, "a": 2}')
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                key_options_cli._controls(path)

    def test_editor_resolution_requires_a_spec_dir(self):
        # Every offline and native plan action shares this gate before any
        # vendor specification is read.
        for action in (*key_options_cli.OFFLINE_ACTIONS[1:], "key-micro-functions",
                       "neo-key-micro-functions", "power-up", "neo-indicators",
                       "neo-indicator-styles", "neo-indicator-editor"):
            with self.subTest(action=action):
                with self.assertRaisesRegex(ValueError, "--spec-dir"):
                    key_options_cli._editor(action, None, "KEYM4.xml")


if __name__ == "__main__":
    unittest.main()
