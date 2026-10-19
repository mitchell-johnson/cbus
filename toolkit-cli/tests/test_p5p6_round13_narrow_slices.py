"""Round 13 narrow offline slices for P5 issues 38-44 and P6 issues 45-47, 49.

Each method pins ONE genuinely-missing pure-offline branch with a synthetic
fixture or plain values. Every pinned message was verified to have zero prior
refs via ``grep -rln`` across tests/ before writing (full message strings,
not substrings, except where noted). No hardware, vendor EXE, C-Gate server,
or decoded vendor spec is required; every refusal fires before any I/O.

Issue map (remaining gap + next file to change after each slice):
- #38 (P5.01): ``research/map_dialog_candidates._embedded_resources`` had zero
  refs; pinned here. Next: control->parameter receipts still need the vendor
  EXE digest; see research/map_dialog_candidates.py IMPLEMENTED_EDITORS.
- #39 (P5.02): ``neo_indicators`` brightness/key-press/nightlight/colour/
  style full messages had zero refs (only substrings were pinned in
  test_input_options.py); pinned here. Next: join/IR/virtual-key columns in
  key_options_cli.py / extended_macros.py.
- #40 (P5.03): ``din_output_settings.plan`` channel/logic-group/pair/
  relay/restrike/interlock guards had zero refs; pinned here. Next: IOPE
  scenes/input-functions/environment tabs in iope_settings.py.
- #41 (P5.04): ``pir_sensors`` key-mapping/shape/sharing/application/
  restore/power-up/polarity/snapshot guards had zero refs; pinned here.
  Next: SENLLA/SENPILLA/SENPIRIC classes (refused in sensors.py REFUSED and
  light_level_sensors.profile_refusal) need original class evidence.
- #42 (P5.05): ``thermostat_post_load`` group-sort/replay/family/
  installation/groups-shape/duplicate-tag/address-exhaustion/setback-source
  guards had zero refs; pinned here. Next: zone creation cross-checks and
  physical timing in thermostat_settings.py / thermostat_unit_load.py.
- #43 (P5.06): the 4 refused conversion directions (3x KEYM6->DLT via
  PAIR_REFUSALS plus RELDN4->RELDN8) had zero refs; pinned here as explicit
  documented refusals. Next: original factory evidence for KEYM6 targets and
  the 4-vs-8-element RELDN4 logic-field composition in
  toolkit_conversion_tweakers.py.
- #44 (P5.07): ``wireless_connection`` profile/byte/boolean/duplicate/
  missing/scalar/decimal/topology guards plus ``wireless_unit_globals``
  house-code text/bytes round trip had zero refs; pinned here. Next:
  Connection/Scenes save side effects and radio join in
  wireless_connection.py / wireless_scenes.py.
- #45 (P6.01): ``edlt_parent_add_dialog.normalize`` shape guards had zero
  refs; pinned here. Next: combined parent-widget lifecycle workflows in
  edlt_parent_transaction.py.
- #46 (P6.02): ``edlt_display_model`` preference/registry/toolkit-values/
  dword guards had zero refs; pinned here. Next: project/DLTP DYNAMIC and
  FONT image metadata in edlt_dltp_index.py / edlt_global_preparation.py.
- #47 (P6.03): ``dlt_profiles.refusal`` classic/eDLT mismatch,
  non-extrapolation, help-only catalogue, unknown-type and catalogue-shape
  branches had zero refs; pinned here. Next: per-operation equivalence
  evidence for non-5.5.00 eDLT operations and legacy Saturn/Neo/Decorator
  control recovery in dlt_profiles.py.
- #49 (P6.05): ``edlt_dynamic_label_control`` receipt/text/int/flag/event/
  operation validators had zero refs; pinned here. The device-cache
  readback proof of absence already lives in edlt_project_labels.py
  ('device_readback': False) and edlt_widget_groups.py
  ('dynamic_label_cache_readback': False); this slice pins the GUI-callback
  input boundary that must never become a cache read. Next: physical eDLT
  trace to settle the native capability disposition.
"""
from __future__ import annotations

import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from research import map_dialog_candidates as dialog_map
from test_din_output_settings import fixture as din_fixture
from test_input_options import fixture as input_fixture
from test_pir_sensors import fixture as pir_fixture

from cbus_toolkit.din_output_settings import DinOutputEditor, DinSettingsError
from cbus_toolkit.dlt_profiles import DltProfileError, refusal
from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_display_model import EdltDisplayPreferences
from cbus_toolkit.edlt_dynamic_label_control import (
    _flag,
    _int,
    _json,
    _text,
    normalize_events,
    normalize_operation,
)
from cbus_toolkit.edlt_parent_add_dialog import normalize as parent_normalize
from cbus_toolkit.neo_indicators import (
    OPTION_LAYOUTS,
    STYLE_LAYOUTS,
    NeoIndicatorOptions,
    NeoIndicatorStyles,
)
from cbus_toolkit.pir_sensors import PIRSensor
from cbus_toolkit.pp_editor import PPEditError
from cbus_toolkit.sensors import SensorError
from cbus_toolkit.thermostat_post_load import (
    _Groups,
    form_save_disabled_remotes,
    replay_post_load,
    validate_group_sort,
    ThermostatPostLoadError,
)
from cbus_toolkit.toolkit_conversion_tweakers import TweakerRefused, admitted, lookup
from cbus_toolkit.wireless_connection import (
    FrozenTopology,
    WirelessConnectionError,
    _address,
    _boolean,
    _byte,
    _field,
    check_profile as wireless_connection_profile,
)
from cbus_toolkit.wireless_unit_globals import (
    WirelessGlobalsError,
    house_code_bytes,
    house_code_text,
)

ROOT = Path(__file__).resolve().parents[1]


class P5P6Round13NarrowTests(unittest.TestCase):
    """Round 13 (P5 issues 38-44, P6 issues 45-47, 49). See module docstring."""

    def test_p501_embedded_resources_follow_dfm_nesting(self):
        """Issue #38: _embedded_resources had zero test refs.

        Pins the static form->frame expansion the P5.01 control denominator
        depends on, using the committed executable surface only.
        """
        executable = json.loads((ROOT / "docs/toolkit-executable-surface.json").read_text())
        self.assertEqual(
            dialog_map._embedded_resources(["TFRMARCHITECTURALDIMMER"], executable),
            [
                "TFRMARCHDIMMERCBUSDISABLE",
                "TFRMARCHDIMMERCHANNELS",
                "TFRMARCHDIMMERDIAGNOSTICLOG",
                "TFRMARCHDIMMERDMX",
                "TFRMARCHDIMMERFADETIMES",
                "TFRMARCHDIMMERLOGIC",
                "TFRMARCHDIMMERRECOVERY",
                "TFRMARCHDIMMERSCENES",
                "TFRMARCHDIMMERSPECIALSCENES",
                "TFRMARCHITECTURALDIMMER",
                "TFRMCBUSOUTPUTUNITERRORREPORTING",
                "TFRMCBUSOUTPUTUNITGLOBALSWITHLEARN",
                "TFRMCBUSUNITSTATUS",
                "TFRMDIMARXCHANNELSTATUS",
                "TFRMUNITGLOBALLEARNMODENEW",
                "TFRMUNITIDAREAFW2",
            ],
        )
        # Shared frames are listed once; unknown names are dropped silently.
        self.assertEqual(
            dialog_map._embedded_resources(["TFRMCOOLINGGROUPS", "TFRMDAMPERGROUPS"], executable),
            ["TFRMCOOLINGGROUPS", "TFRMDAMPERGROUPS", "TFRMTHERMOSTATEXTERNALRELAYS"],
        )
        self.assertEqual(dialog_map._embedded_resources(["TFRMSENPILL", "NOPE"], executable), ["TFRMSENPILL"])
        self.assertEqual(dialog_map._embedded_resources([], executable), [])
        self.assertEqual(
            dialog_map._embedded_resources(["TFRMSENPILL"], executable),
            dialog_map._embedded_resources(["TFRMSENPILL", "TFRMSENPILL"], executable),
        )

    def test_p502_neo_indicator_full_guard_messages(self):
        """Issue #39: neo_indicators full guard messages had zero refs.

        test_input_options.py pins only substrings ("key-press
        brightening", "nightlight enabled", "key_press_level", "duration")
        or generic PPEditError for these branches; the full messages below
        never appear in tests/.
        """
        options = NeoIndicatorOptions(input_fixture("KEYM4.xml", "KEYM4", OPTION_LAYOUTS))
        current = options.spec.defaults()
        cases = (
            ({"brightness": "bogus"}, "Brightness source must be fixed, group or first_block"),
            ({"brightness": "fixed"}, "A fixed level needs brightness_percent 0..100 and no group"),
            (
                {"brightness": "fixed", "brightness_percent": 101},
                "A fixed level needs brightness_percent 0..100 and no group",
            ),
            (
                {"brightness": "fixed", "brightness_percent": 50, "brightness_group": 1},
                "A fixed level needs brightness_percent 0..100 and no group",
            ),
            ({"brightness": "group"}, "Level of group needs brightness_group 0..255"),
            (
                {"brightness": "group", "brightness_group": 5, "brightness_percent": 10},
                "Level of group needs brightness_group 0..255",
            ),
            (
                {"brightness": "first_block", "brightness_percent": 5},
                "Level of first block takes no percent or group",
            ),
            ({"brightness_percent": 50}, "Select a brightness source"),
            ({"key_press_seconds": 16}, "Key-press duration is 1..15 seconds"),
            (
                {"key_press_seconds": 5},
                "Enabling key-press brightening needs key_press_level 0..15",
            ),
            ({"key_press_level": 16}, "Key-press level is 0..15"),
            (
                {"key_press_seconds": 0, "key_press_level": 5},
                "Toolkit sets the key-press level only with a 1..15 second duration",
            ),
            (
                {"key_press_seconds": 0, "nightlight": True},
                "Toolkit enables the nightlight only with key-press brightening",
            ),
            (
                {"ignore_first_key_press": True},
                "Toolkit ignores the first key press only with the nightlight enabled",
            ),
        )
        for kwargs, message in cases:
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(PPEditError, message):
                options.plan(dict(current), **kwargs)
        # Happy paths report the family nightlight bit and brightness source.
        plan = options.plan(dict(current), brightness="fixed", brightness_percent=50)
        self.assertEqual(plan.changes, {"IndicatorBrightness": (127,)})
        self.assertEqual(plan.as_dict()["nightlight_parameter"], "EnableNightlightOnPA6")
        styles = NeoIndicatorStyles(input_fixture("KEYV2.xml", "KEYV2", STYLE_LAYOUTS))
        styled = styles.spec.defaults()
        with self.assertRaisesRegex(PPEditError, "Colour must be blue or orange"):
            styles.plan(dict(styled), colour="red")
        with self.assertRaisesRegex(
            PPEditError, "Style must be always_off, always_on, status_on or status_dual"
        ):
            styles.plan(dict(styled), colour="blue", style="bogus")

    def test_p503_din_output_tab_guard_messages(self):
        """Issue #40: din_output_settings.plan tab guards had zero refs."""
        relay = DinOutputEditor(din_fixture("RELDN4"))
        relay_defaults = din_fixture("RELDN4").defaults()
        cases = (
            ({"min_level": 10}, "Channel settings require a channel"),
            ({"logic_group_address": 5}, "Logic recovery and group settings require a logic group"),
            (
                {"channel": 1, "min_level": 10, "min_percent": 50},
                "Use either min_level or min_percent",
            ),
            (
                {
                    "channel": 1,
                    "logic_group": 1,
                    "logic_recovery_level": 10,
                    "logic_recovery_percent": 50,
                },
                "Use either logic_recovery_level or logic_recovery_percent",
            ),
            (
                {"channel": 1, "max_level": 10},
                "The relay Turn On tab binds only the minimum threshold",
            ),
        )
        for kwargs, message in cases:
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(DinSettingsError, message):
                relay.plan(dict(relay_defaults), **kwargs)
        no_interlock = DinOutputEditor(din_fixture("RELDN8"))
        with self.assertRaisesRegex(DinSettingsError, "hides the interlock control for RELDN8"):
            no_interlock.plan(dict(din_fixture("RELDN8").defaults()), interlock=2)
        dimmer = DinOutputEditor(din_fixture("DIMDN4"))
        dimmer_defaults = din_fixture("DIMDN4").defaults()
        for kwargs in ({"channel": 1, "restrike": True}, {"channel": 1, "restrike_delay": 10}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(
                DinSettingsError, "Restrike settings exist only on relay units"
            ):
                dimmer.plan(dict(dimmer_defaults), **kwargs)
        self.assertEqual(
            relay.plan(dict(relay_defaults), channel=1, min_level=10).changes["MinDimmingLevel"][0], 10
        )

    def test_p504_pir_sensor_key_shape_and_snapshot_guards(self):
        """Issue #41: pir_sensors key/snapshot guards had zero refs."""
        sensor = PIRSensor(pir_fixture())
        defaults = pir_fixture().defaults()
        cases = (
            ({"keys": [1]}, "PIR keys must be a mapping from key 1..4"),
            ({"keys": {5: {}}}, "PIR keys must be a mapping from key 1..4"),
            ({"keys": {1: {"bogus": 1}}}, "Key options are block, group, timer_seconds and expiry"),
            (
                {"darkness_same_as_light": True, "keys": {2: {"block": 1}}},
                "Motion in Darkness follows Motion in Light",
            ),
            ({"keys": {1: {"block": 2, "group": 5}}}, "is shared by keys"),
            ({"keys": {4: {"group": 5}}}, "have functions other than their fixed PIR event"),
            ({"power_up": "bogus"}, "power_up must be disabled, enabled or resume"),
            ({"enabled_when": "off"}, "Enable polarity requires an assigned occupancy"),
        )
        for kwargs, message in cases:
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(SensorError, message):
                sensor.plan(dict(defaults), **kwargs)
        current = dict(defaults)
        current["BlockAllocation"] = "0 2 4 8 16 32 64 128"
        with self.assertRaisesRegex(SensorError, "Specify block 1..4 for key 1"):
            sensor.plan(current, keys={1: {"group": 5}})
        unlit = dict(defaults)
        unlit["Application"] = "10 255"
        with self.assertRaisesRegex(SensorError, "Lighting Type application in 48..95"):
            sensor.plan(unlit, keys={1: {"group": 5}})
        restored = sensor.plan(dict(defaults), keys={4: {"group": 5}}, restore_functions=True)
        self.assertEqual(restored.dialog["restored_functions"], [4])
        missing = dict(defaults)
        del missing["PIRLightMovement"]
        with self.assertRaisesRegex(SensorError, "Missing current PIR sensor parameter"):
            sensor.snapshot(missing)
        bad = dict(defaults)
        bad["PIRDark"] = "999"
        with self.assertRaisesRegex(SensorError, "Invalid current PIR sensor parameter"):
            sensor.snapshot(bad)
        self.assertEqual(len(sensor.snapshot(dict(defaults))), 51)

    def test_p505_thermostat_post_load_group_and_setback_guards(self):
        """Issue #42: thermostat_post_load group/setback guards had zero refs."""
        with self.assertRaisesRegex(
            ThermostatPostLoadError, "Group sort must be address-ascending or omitted"
        ):
            validate_group_sort("bogus")
        with self.assertRaisesRegex(ThermostatPostLoadError, "Group sort requires post-load replay"):
            validate_group_sort("address-ascending", post_load=False)
        self.assertIsNone(validate_group_sort(None))
        self.assertIsNone(validate_group_sort("address-ascending"))
        with self.assertRaisesRegex(ThermostatPostLoadError, "Unknown thermostat family"):
            replay_post_load({}, "bogus", 1, {})
        with self.assertRaisesRegex(ThermostatPostLoadError, "Installation must be 1..9"):
            replay_post_load({}, "programmable", 99, {})
        with self.assertRaisesRegex(
            ThermostatPostLoadError, "Groups must map byte addresses to tag text"
        ):
            replay_post_load({}, "programmable", 1, {1: 2})
        with self.assertRaisesRegex(
            ThermostatPostLoadError, "Explicit group sort requires an initially empty output application"
        ):
            replay_post_load({}, "programmable", 1, {5: "X"}, group_sort="address-ascending")
        with self.assertRaisesRegex(ThermostatPostLoadError, "Several output groups share tag"):
            _Groups({1: "Tag", 2: "TAG"}, "x").find("tag")
        self.assertEqual(_Groups({1: "Tag", 2: "Other"}, "x").find("TAG"), 1)
        with self.assertRaisesRegex(ThermostatPostLoadError, "No free output group address in 0..254"):
            _Groups({address: "t" for address in range(255)}, "").new_address_ascending()
        for values in ({"RemoteSetbackControlSource": 5}, {"RemoteSetbackControlSource": "x"}):
            with self.subTest(values=values), self.assertRaisesRegex(
                ThermostatPostLoadError, "RemoteSetbackControlSource must be 0..2"
            ):
                form_save_disabled_remotes(values, "basic")
        with self.assertRaisesRegex(ThermostatPostLoadError, "Unknown thermostat family"):
            form_save_disabled_remotes({"RemoteSetbackControlSource": 0}, "bogus")
        self.assertEqual(
            form_save_disabled_remotes({"RemoteSetbackControlSource": 0}, "basic"),
            {"RemoteSetbackOnGroup": 30, "RemoteSetbackOffGroup": 31},
        )

    def test_p506_four_refused_conversion_directions_stay_refused(self):
        """Issue #43: the 4 refused directions had zero test refs.

        The registry admits the tweaker class for each pair (so lookup stays
        meaningful), but ``admitted`` must refuse before any I/O until
        original-factory evidence exists. This pins the exact remaining gap.
        """
        self.assertEqual(lookup("KEYM6", "KEYDL4"), "TTweakerDLT")
        self.assertEqual(lookup("RELDN4", "RELDN8"), "TTweakerRELDNX_TO_8")
        for target in ("KEYDL4", "KEYML5", "KEYBL5"):
            with self.subTest(target=target):
                with self.assertRaisesRegex(
                    TweakerRefused, "KEYM6 has no recovered static Toolkit unit factory"
                ) as raised:
                    admitted("KEYM6", target)
                self.assertEqual(
                    (raised.exception.source_type, raised.exception.target_type), ("KEYM6", target)
                )
                self.assertEqual(raised.exception.tweaker_class, "TTweakerDLT")
        with self.assertRaisesRegex(TweakerRefused, "four elements") as raised:
            admitted("RELDN4", "RELDN8")
        self.assertEqual(
            (raised.exception.source_type, raised.exception.target_type), ("RELDN4", "RELDN8")
        )
        self.assertEqual(raised.exception.tweaker_class, "TTweakerRELDNX_TO_8")

    def test_p507_wireless_connection_profile_and_topology_guards(self):
        """Issue #44: wireless_connection guards + house-code round trip had zero refs."""
        self.assertEqual(
            wireless_connection_profile("WGATE5F", "2.3.00", "x"), ("WGATE5F", "2.3.00", "x")
        )
        for args in (
            ("WGATE5N", "2.2.89"),
            ("WGATE5X", "2.3.00"),
            ("WGATE5F", "bogus"),
            ("WGATE5F", "2.5.00"),
        ):
            with self.subTest(args=args), self.assertRaisesRegex(
                WirelessConnectionError, "Only WGATE5N/F Connection profiles"
            ):
                wireless_connection_profile(*args)
        for value in ("x", True, 255):
            with self.subTest(value=value), self.assertRaisesRegex(
                WirelessConnectionError, "Network must be an integer in 0..254"
            ):
                _byte(value, "Network")
        self.assertEqual(_byte(254, "Network"), 254)
        with self.assertRaisesRegex(WirelessConnectionError, "Sync must be a Boolean"):
            _boolean(1, "Sync")
        self.assertTrue(_boolean(True, "Sync"))
        duplicate = ET.fromstring("<Route><Address>12</Address><Address>13</Address></Route>")
        with self.assertRaisesRegex(WirelessConnectionError, "Ambiguous duplicate Address"):
            _field(duplicate, "Address")
        with self.assertRaisesRegex(WirelessConnectionError, "Missing Address"):
            _field(ET.fromstring("<Route><Level>1</Level></Route>"), "Address", required=True)
        scalar = ET.fromstring("<Route><Address><X/></Address></Route>")
        with self.assertRaisesRegex(WirelessConnectionError, "Address must be scalar"):
            _field(scalar, "Address")
        with self.assertRaisesRegex(WirelessConnectionError, "Address must be a decimal byte"):
            _address(ET.fromstring("<Route><Address>1x</Address></Route>"))
        with self.assertRaisesRegex(WirelessConnectionError, "Address must be an integer in 0..254"):
            _address(ET.fromstring("<Route><Address>300</Address></Route>"))
        self.assertEqual(_address(ET.fromstring("<Route><Address>12</Address></Route>")), 12)
        with self.assertRaisesRegex(WirelessConnectionError, "Topology source SHA-256 is invalid"):
            FrozenTopology("{}", "xyz")
        with self.assertRaisesRegex(WirelessConnectionError, "Invalid frozen topology"):
            FrozenTopology("{", "0" * 64)
        canonical = json.dumps({"networks": [], "project": "P"}, sort_keys=True, separators=(",", ":"))
        with self.assertRaisesRegex(WirelessConnectionError, "Frozen topology must be canonical"):
            FrozenTopology('{ "project" : "P" , "networks" : [] }', "0" * 64)
        with self.assertRaisesRegex(WirelessConnectionError, "Missing project networks"):
            FrozenTopology(canonical, "0" * 64)
        with self.assertRaisesRegex(WirelessConnectionError, "Unsupported project identity"):
            FrozenTopology(
                json.dumps({"networks": [1], "project": "P!"},
                           sort_keys=True, separators=(",", ":")),
                "0" * 64,
            )
        self.assertEqual(house_code_text((1, 2, 3, 4)), "04030201")
        self.assertEqual(house_code_bytes("04030201"), (1, 2, 3, 4))
        for bad in ("1234567", "123456789", "ZZZZZZZZ", "", 123, None):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                WirelessGlobalsError, "House code must be exactly eight hexadecimal digits"
            ):
                house_code_bytes(bad)

    def test_p601_parent_add_dialog_shape_guards(self):
        """Issue #45: edlt_parent_add_dialog.normalize guards had zero refs."""
        cases = (
            ({"op": "bogus"}, "Parent Add dialog contains unsupported fields"),
            (
                {"op": "add-corridor-dialog", "field": "nope"},
                "add-corridor-dialog field must be link_group, office_group or corridor_group",
            ),
            (
                {"op": "add-corridor-dialog", "field": "link_group", "address": 255},
                "Parent Add dialog address must be 0..254",
            ),
            (
                {"op": "add-corridor-dialog", "field": "link_group", "name": 5},
                "Parent Add dialog name must be text",
            ),
            (
                {"op": "add-corridor-dialog", "field": "link_group", "cancel": "yes"},
                "Parent Add dialog cancel must be boolean",
            ),
            (
                {"op": "add-corridor-dialog", "field": "link_group", "extra": 1},
                "Parent Add dialog contains unsupported fields",
            ),
        )
        for value, message in cases:
            with self.subTest(value=value), self.assertRaisesRegex(EdltError, message):
                parent_normalize(value)
        self.assertEqual(
            parent_normalize(
                {"op": "add-corridor-dialog", "field": "link_group", "address": 7,
                 "name": "T", "cancel": False}
            ),
            {"op": "add-corridor-dialog", "field": "link_group", "address": 7,
             "name": "T", "cancel": False},
        )

    def test_p602_edlt_display_preference_guards(self):
        """Issue #46: edlt_display_model guards had zero refs."""
        with self.assertRaisesRegex(EdltError, "Display preferences must be booleans"):
            EdltDisplayPreferences(display_hex="x")
        with self.assertRaisesRegex(EdltError, "Registry key presence must be boolean"):
            EdltDisplayPreferences.from_registry({}, key_present="yes")
        with self.assertRaisesRegex(EdltError, "Display registry values must use the five eDLT names"):
            EdltDisplayPreferences.from_registry({"X": 1})
        with self.assertRaisesRegex(EdltError, "An absent Preferences key cannot supply values"):
            EdltDisplayPreferences.from_registry({"DisplayHexAddress": 1}, key_present=False)
        self.assertFalse(any(EdltDisplayPreferences.from_registry({})._flags()))
        named = EdltDisplayPreferences.from_registry({"DisplayHexAddress": 1})
        self.assertEqual(
            (named.display_hex, named.display_address_value), (True, False)
        )
        with self.assertRaisesRegex(
            EdltError, "Toolkit display values must contain the five display names"
        ):
            EdltDisplayPreferences.from_toolkit_display_values({"tag_hex": True})
        with self.assertRaisesRegex(EdltError, "tag_override must be a boolean or byte integer"):
            EdltDisplayPreferences.from_toolkit_display_values(
                {"tag_hex": True, "tag_override": 300, "sort_applications": False,
                 "sort_groups": False, "sort_levels": False}
            )
        adapted = EdltDisplayPreferences.from_toolkit_display_values(
            {"tag_hex": True, "tag_override": 0, "sort_applications": 1,
             "sort_groups": False, "sort_levels": 255}
        )
        self.assertEqual(
            (adapted.display_hex, adapted.sort_applications_by_address, adapted.sort_levels_by_address),
            (True, True, True),
        )
        with self.assertRaisesRegex(EdltError, "Invalid eDLT display preference format or fields"):
            EdltDisplayPreferences.from_dict(
                {"format": "bogus", "registry_key_present": True, "values": {}}
            )
        from cbus_toolkit import edlt_display_model as display_model

        with self.assertRaisesRegex(EdltError, "must be one REG_DWORD integer"):
            display_model._dword(2**32, "X")
        self.assertEqual(display_model._dword(0xFFFFFFFF, "X"), -1)

    def test_p603_dlt_profile_refusal_branches(self):
        """Issue #47: dlt_profiles refusal branches had zero refs."""
        self.assertIn("without eDLT widgets", refusal("edlt-database-widgets", "KEYBL5"))
        self.assertIn(
            "is not extrapolated", refusal("edlt-label-clear", "KEYGL5", "5.4.00")
        )
        self.assertIn(
            "IsInternal", refusal("edlt-label-clear", "KEYGL5", "5.6.00")
        )
        self.assertIn(
            "does not exist in the C-Gate catalogue",
            refusal("edlt-database-widgets", "KEYGL5", "5.5.00", "5505ED"),
        )
        self.assertIn(
            "is not a DLT or eDLT unit type", refusal("edlt-database-widgets", "NOPE")
        )
        self.assertEqual(refusal("edlt-database-widgets", 5), "Unit type must be text")
        self.assertEqual(
            refusal("edlt-database-widgets", "KEYGL5", "5.5.00", 5), "Catalogue number must be text"
        )
        self.assertIsNone(refusal("edlt-database-widgets", "KEYGL5", "5.5.00", "5055EDL"))
        with self.assertRaises(DltProfileError):
            refusal("bogus-workflow", "KEYGL5")

    def test_p605_dynamic_label_control_input_boundary(self):
        """Issue #49: edlt_dynamic_label_control validators had zero refs.

        These pin the GUI-callback input boundary that must never become a
        device-cache read: text/JSON shape only, no bus traffic. The
        proof-of-absence markers ('device_readback': False in
        edlt_project_labels.py, 'dynamic_label_cache_readback': False in
        edlt_widget_groups.py) are covered by
        test_edlt_dynamic_cache_scope.py.
        """
        with self.assertRaisesRegex(EdltError, "need Unicode JSON-compatible"):
            _json(object())
        with self.assertRaisesRegex(EdltError, "control text must be a string"):
            _text(5)
        with self.assertRaisesRegex(EdltError, "NUL-free and at most 64 UTF-16 units"):
            _text("a\0b", input_text=True)
        with self.assertRaisesRegex(EdltError, "NUL-free and at most 64 UTF-16 units"):
            _text("x" * 65, input_text=True)
        self.assertEqual(_text("a\0b"), "a\0b")
        with self.assertRaisesRegex(EdltError, "must be -1 or a nonnegative signed integer"):
            _int(2**31)
        self.assertEqual((_int(-1), _int(0)), (-1, 0))
        with self.assertRaisesRegex(EdltError, "must be boolean"):
            _flag({"a": 1}, "a", False)
        with self.assertRaisesRegex(EdltError, "at most 512 ordered callbacks"):
            normalize_events([{}] * 513)
        with self.assertRaisesRegex(EdltError, "events require records"):
            normalize_events(["x"])
        with self.assertRaisesRegex(EdltError, "needs exact ordinal, identity and value"):
            normalize_events([{"event": "selected-row", "index": 0}])
        with self.assertRaisesRegex(EdltError, "Unsupported dynamic-label control event"):
            normalize_events([{"event": "bogus"}])
        with self.assertRaisesRegex(EdltError, "Invalid dynamic-label-control operation"):
            normalize_operation({"op": "x", "target": "label", "events": []})
        self.assertEqual(
            normalize_operation({"op": "dynamic-label-control", "target": "label",
                                 "events": [{"event": "leave"}]}),
            {"op": "dynamic-label-control", "target": "label", "events": [{"event": "leave"}]},
        )


if __name__ == "__main__":
    unittest.main()
