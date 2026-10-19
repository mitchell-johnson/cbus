"""P5.04 focused SENPILL subset for #41: source/native/wheel, neighbors, refusals.

One narrow SENPILL slice with independent literal vectors. Pure-offline
except a single skipped-unless-provisioned native case. The original Toolkit
dialog was not executed and no physical PIR/lux behavior was observed; #41
stays OPEN. SENPILL 2.3.10..2.3.99, SENPIROA/SENPIRIA/SENPIRIB, SENLL/SENLLA,
SENPILLA/SENPIRIC and older classes remain future work.
"""
from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from uuid import uuid4

import cbus_toolkit.sensors as sensor_module
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.sensors import (
    EVENTS,
    EXPIRY,
    LAYOUTS,
    PROFILE,
    Multisensor,
    SensorApplyError,
    SensorError,
    margin_percent,
    profile_refusal,
    saved_margin,
)
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec
from test_macros import Session


# Independent literal layout: (name, address, count, bits, bit, skip, defaults).
# Matches the SENPILL_ST7 PP table used by Multisensor; not derived from code.
ROWS = [
    ("JPCommand", 104, 8, 4, 4, 1, [7, 13, 13, 0, 0, 0, 0, 0]),
    ("SRCommand", 104, 8, 4, 0, 1, [0, 7, 15, 0, 0, 0, 0, 0]),
    ("LPCommand", 105, 8, 4, 4, 1, [0, 7, 7, 0, 0, 0, 0, 0]),
    ("LRCommand", 105, 8, 4, 0, 1, [0, 0, 15, 0, 0, 0, 0, 0]),
    ("PIRLightMovement", 50, 1, 8, 0, 0, [1]),
    ("PIRDarkMovement", 51, 1, 8, 0, 0, [2]),
    ("PIRDark", 52, 1, 8, 0, 0, [4]),
    ("BlockAllocation", 54, 8, 8, 0, 0, [2, 2, 4, 8, 16, 32, 64, 128]),
    ("GroupAddress", 80, 8, 8, 0, 0, [255] * 8),
    ("Application", 33, 2, 8, 0, 0, [56, 255]),
    ("SecondApplicationBlocks", 69, 1, 8, 0, 0, [0]),
    ("SceneKeySelector", 96, 8, 1, 7, 0, [0] * 8),
    ("TimerHighByte", 136, 8, 8, 0, 0, [1] * 8),
    ("TimerLowByte", 144, 8, 8, 0, 0, [44] * 8),
    ("TimerExpiryCommand", 72, 8, 4, 0, 0, [15] * 8),
    ("BlockBankSwitchActive", 72, 8, 1, 5, 0, [0] * 8),
    ("PECTargetLux", 27, 1, 8, 0, 0, [70]),
    ("PECMarginLux", 28, 1, 8, 0, 0, [4]),
    ("PIREnablerGroup", 88, 1, 8, 0, 0, [255]),
    ("PIREnablerGroupLogic", 99, 1, 1, 6, 0, [0]),
    ("SingleJoinEnablerGroup", 90, 1, 8, 0, 0, [255]),
    ("DualJoinEnablerGroup", 91, 1, 8, 0, 0, [255]),
    ("PECFunctionActive", 96, 1, 1, 6, 0, [0]),
    ("PECFunctionBlock", 96, 1, 3, 3, 0, [0]),
    ("BroadcastActive", 70, 1, 3, 5, 0, [0]),
    ("BroadcastBlock", 70, 1, 3, 0, 0, [0]),
    ("PotentiometerAFunction", 101, 1, 2, 3, 0, [1]),
    ("PotentiometerBFunction", 101, 1, 2, 5, 0, [0]),
    ("PotentiometerATimerBlock", 102, 1, 3, 3, 0, [0]),
    ("PotentiometerBTimerBlock", 103, 1, 3, 3, 0, [0]),
]

# Focused P5.04 case: key 3, night, block 3, group 31, 513 s ramp_off,
# 550 lux at 10%, enable group 23 off. All expected bytes are literal.
FOCUSED_OPTIONS = {
    "key": 3,
    "event": "night",
    "block": 3,
    "group": 31,
    "timer_seconds": 513,
    "expiry": "ramp_off",
    "target_lux": 550,
    "margin_percent": 10,
    "enable_group": 23,
    "enabled_when": "off",
    "disable_potentiometer_override": True,
}
# Literal planned changes for the focused case from the ROWS defaults.
FOCUSED_CHANGES = {
    "SRCommand": (0, 7, 7, 0, 0, 0, 0, 0),
    "LRCommand": (0, 0, 0, 0, 0, 0, 0, 0),
    "PIRDarkMovement": (6,),
    "PIRDark": (0,),
    "GroupAddress": (255, 255, 31, 255, 255, 255, 255, 255),
    "TimerHighByte": (1, 1, 2, 1, 1, 1, 1, 1),
    "TimerLowByte": (44, 44, 1, 44, 44, 44, 44, 44),
    "TimerExpiryCommand": (15, 15, 9, 15, 15, 15, 15, 15),
    "PECTargetLux": (55,),
    "PECMarginLux": (6,),
    "PIREnablerGroup": (23,),
    "PIREnablerGroupLogic": (1,),
    "PotentiometerAFunction": (0,),
}


def fixture():
    parameters = {}
    for name, address, count, bits, bit, skip, values in ROWS:
        kind = "bit" if name in ("PIREnablerGroupLogic", "PECFunctionActive") else "int"
        fields = {
            "Name": name,
            "Type": kind,
            "Address": str(address),
            "ArraySize": str(count),
            "BitSize": str(bits),
            "BitAddress": str(bit),
            "ArraySkip": str(skip),
            "DefaultValue": " ".join(map(str, values)),
        }
        parameters[name] = ParameterSpec(name, kind, "literal-p504-senpill-fixture.xml", fields)
    return UnitSpec("SENPILL_ST7.xml", {"Type": "SENPILL"}, ("literal-p504-senpill-fixture.xml",), parameters)


def native_backend():
    if os.environ.get("CBUS_NATIVE_SERVICE_BACKEND") == "local":
        return "local" if os.environ.get("CBUS_LOCAL_CGATE_VENDOR") and os.environ.get("CBUS_CGATE_JAVA") else None
    return "host" if os.environ.get("CBUS_CGATE_TEST_HOST") else None


class SourceProfileAndVectorsTest(unittest.TestCase):
    """Source case: admitted SENPILL profile and literal dialog vectors."""

    def setUp(self):
        self.spec = fixture()
        self.sensor = Multisensor(self.spec)

    def test_profile_event_and_layout_literals_match_source(self):
        # Literal profile gate: unit, firmware band, catalogues, spec file.
        self.assertEqual(dict(PROFILE), {"unit_type": "SENPILL", "firmware": ("2.0.01", "2.3.9"),
                                         "catalog_numbers": ("5753PEIRL", "SLC5753PEIRL"),
                                         "spec_filename": "SENPILL_ST7.xml"})
        self.assertEqual(dict(EVENTS), {"day": (7, 0, 0, 0), "night": (13, 7, 7, 0),
                                        "any": (13, 7, 0, 7), "sunset": (13, 15, 7, 15),
                                        "disabled": (0, 0, 0, 0)})
        self.assertEqual(set(EXPIRY), {"idle", "off", "down", "ramp_off", "recall1", "recall2", "ramp_recall1"})
        self.assertEqual(len(LAYOUTS), 30)
        for name, address, count, bits, bit, skip, _ in ROWS:
            self.assertEqual(tuple(LAYOUTS[name]), (address, count, bits, bit, skip), name)
        self.assertIsNone(profile_refusal("SENPILL", "2.3.00", "5753PEIRL"))
        self.assertIsNone(profile_refusal("SENPILL", "2.1.00", "SLC5753PEIRL"))

    def test_focused_night_plan_literal_changes(self):
        plan = self.sensor.plan(self.spec.defaults(), **FOCUSED_OPTIONS)
        self.assertEqual(plan.key, 3)
        self.assertEqual(plan.event, "night")
        self.assertEqual(plan.block, 3)
        self.assertEqual(plan.shared_keys, ())
        self.assertEqual(dict(plan.changes), FOCUSED_CHANGES)
        final = dict(plan.expected)
        final.update(plan.changes)
        # Literal stage nibbles for key 3 night: JP/LP preserved, SR/LR templated.
        self.assertEqual(tuple(final[n][2] for n in ("JPCommand", "SRCommand", "LPCommand", "LRCommand")),
                         (13, 7, 7, 0))
        # Literal occupancy masks: night sets only the dark-motion bit.
        self.assertEqual((final["PIRLightMovement"], final["PIRDarkMovement"], final["PIRDark"]),
                         ((1,), (6,), (0,)))
        self.assertEqual(final["GroupAddress"][2], 31)
        self.assertEqual((final["TimerHighByte"][2], final["TimerLowByte"][2]), (2, 1))
        self.assertEqual(final["TimerExpiryCommand"][2], 9)
        self.assertEqual((final["PECTargetLux"], final["PECMarginLux"]), ((55,), (6,)))
        self.assertEqual((final["PIREnablerGroup"], final["PIREnablerGroupLogic"]), ((23,), (1,)))
        encoded = self.sensor.codec.encode_many(plan.changes).apply(MemoryImage.from_bytes(b"\xa5" * 256))
        # Group byte and timer bytes for block 3 are literal.
        self.assertEqual(encoded.read(80 + 2, 1), bytes((31,)))
        self.assertEqual(encoded.read(136 + 2, 1), bytes((2,)))
        self.assertEqual(encoded.read(144 + 2, 1), bytes((1,)))

    def test_x87_margin_literals(self):
        # Exact 10-lux steps with the original x87 save arithmetic.
        self.assertEqual(saved_margin(55, 10), 6)
        self.assertEqual(saved_margin(50, 59), 29)
        self.assertEqual(saved_margin(150, 21), 31)
        self.assertEqual(saved_margin(0, 30), 0)
        self.assertEqual(margin_percent(55, 6), 11)
        self.assertEqual(margin_percent(50, 7), 14)
        self.assertEqual(margin_percent(0, 9), 0)


class NeighborPreservationTest(unittest.TestCase):
    """Packed-byte neighbors and unrelated parameters stay unchanged."""

    def setUp(self):
        self.spec = fixture()
        self.sensor = Multisensor(self.spec)

    def test_bank_and_scene_bits_cleared_without_neighbor_damage(self):
        current = self.spec.defaults()
        current["BlockBankSwitchActive"] = "1 1 1 1 1 1 1 1"
        current["SceneKeySelector"] = "1 1 1 1 1 1 1 1"
        plan = self.sensor.plan(current, key=3, event="night", group=17, timer_seconds=300, expiry="ramp_off")
        self.assertEqual(plan.changes["BlockBankSwitchActive"], (1, 1, 0, 1, 1, 1, 1, 1))
        self.assertEqual(plan.changes["SceneKeySelector"], (1, 1, 0, 1, 1, 1, 1, 1))
        memory = self.sensor.codec.encode_many(plan.changes).apply(MemoryImage.from_bytes(b"\xff" * 256))
        self.assertEqual(memory.read(74, 1), b"\xd9")
        self.assertEqual(memory.read(98, 1), b"\x7f")

    def test_focused_apply_preserves_unrelated_and_packed_neighbors(self):
        session = Session(self.spec)
        session.unit_type, session.firmware, session.catalog_number = "SENPILL", "2.3.00", "5753PEIRL"
        session.current["Other"] = "unchanged"
        before = session.values()
        plan = self.sensor.plan(session.values(), **FOCUSED_OPTIONS)
        result = self.sensor.apply(session, plan)
        self.assertTrue(result["verified"])
        self.assertFalse(result["saved"])
        self.assertFalse(result["device_verified"])
        self.assertEqual(session.current["Other"], "unchanged")
        after = session.values()
        # Every parameter outside the workflow is untouched.
        unrelated = sorted(n for n in before if n not in LAYOUTS)
        self.assertEqual({n: after[n] for n in unrelated}, {n: before[n] for n in unrelated})
        # Packed neighbors: other keys, blocks, timers and applications.
        for name, index, expected in (("JPCommand", 0, 7), ("JPCommand", 3, 0), ("SRCommand", 0, 0),
                                      ("BlockAllocation", 0, 2), ("BlockAllocation", 3, 8),
                                      ("GroupAddress", 0, 255), ("TimerHighByte", 0, 1),
                                      ("TimerLowByte", 0, 44), ("TimerExpiryCommand", 0, 15),
                                      ("Application", 0, 56)):
            self.assertEqual(after[name].split()[index], str(expected), f"{name}[{index}]")
        # Stale re-apply is refused.
        with self.assertRaisesRegex(SensorError, "changed since"):
            self.sensor.apply(session, plan)


class NativeLikeRefusalTest(unittest.TestCase):
    """Native refusals: wrong class, band and catalogue leave values unchanged."""

    def setUp(self):
        self.spec = fixture()
        self.sensor = Multisensor(self.spec)

    def session(self):
        session = Session(self.spec)
        session.unit_type, session.firmware, session.catalog_number = "SENPILL", "2.3.00", "5753PEIRL"
        return session

    def test_refused_identities_raise_before_any_write(self):
        refused = (
            (("SENPILL", "2.3.10", "5753PEIRL"), "outside"),
            (("SENPILL", "2.0.00", "5753PEIRL"), "outside"),
            (("SENPILL", "2.3.00", "5753L"), "catalogue"),
            (("SENPIROA", "2.3.00", "5750WPL"), "PIR sensor class"),
            (("SENLL", "2.3.00", "5031PE"), "light-level"),
            (("SENPILLA", "2.4.00", "5754ODPEIR"), "TSENPILLA"),
        )
        for identity, reason in refused:
            with self.subTest(identity=identity):
                self.assertIn(reason, profile_refusal(*identity))
                session = self.session()
                session.unit_type, session.firmware, session.catalog_number = identity
                before = session.values()
                with self.assertRaisesRegex(SensorError, "Native session must"):
                    self.sensor.configure(session, key=3, event="night", group=31)
                # Refusal fires before any PP write.
                self.assertEqual(session.values(), before)
                self.assertEqual(session.calls, [])
        # Native session with a refused firmware/catalogue refuses apply.
        plan = self.sensor.plan(self.spec.defaults(), **FOCUSED_OPTIONS)
        for field, value in (("firmware", "2.4.00"), ("firmware", "2.3.10"),
                             ("catalog_number", "5753L"), ("unit_type", "SENPIRIB")):
            with self.subTest(field=field):
                session = self.session()
                setattr(session, field, value)
                before = session.values()
                with self.assertRaisesRegex(SensorError, "Native session"):
                    self.sensor.apply(session, plan)
                self.assertEqual(session.values(), before)
                self.assertEqual(session.calls, [])

    def test_partial_failure_does_not_retry_or_save(self):
        session = self.session()
        session.failure = "GroupAddress"
        plan = self.sensor.plan(session.values(), **FOCUSED_OPTIONS)
        with self.assertRaises(SensorApplyError) as error:
            self.sensor.apply(session, plan)
        self.assertEqual(error.exception.attempted[-1], "GroupAddress")
        self.assertEqual(sum(name == "GroupAddress" for name, _ in session.calls), 1)


class InstalledWheelParityTest(unittest.TestCase):
    """Installed-wheel case: same module, literals and pure plan either way."""

    def test_module_origin_and_literals_are_install_independent(self):
        origin = importlib.util.find_spec("cbus_toolkit.sensors").origin
        self.assertTrue(origin and origin.endswith("cbus_toolkit/sensors.py"), origin)
        self.assertEqual(Path(sensor_module.__file__).name, "sensors.py")
        self.assertEqual(sensor_module.PROFILE["unit_type"], "SENPILL")
        self.assertEqual(sensor_module.PROFILE["spec_filename"], "SENPILL_ST7.xml")
        self.assertEqual(sensor_module.EVENTS["night"], (13, 7, 7, 0))
        self.assertEqual(sensor_module.LAYOUTS["GroupAddress"], (80, 8, 8, 0, 0))
        self.assertEqual(sensor_module.LAYOUTS["TimerHighByte"], (136, 8, 8, 0, 0))

    def test_same_literal_plan_from_independent_spec_instances(self):
        first = Multisensor(fixture()).plan(fixture().defaults(), **FOCUSED_OPTIONS)
        second = Multisensor(fixture()).plan(fixture().defaults(), **FOCUSED_OPTIONS)
        self.assertEqual(dict(first.changes), FOCUSED_CHANGES)
        self.assertEqual(dict(second.changes), FOCUSED_CHANGES)
        self.assertEqual(dict(first.expected), dict(second.expected))
        self.assertEqual(first.as_dict()["format"], "cbus-st7-sensor-plan-v1")
        self.assertEqual(first.as_dict()["firmware_range"], ["2.0.01", "2.3.9"])


@unittest.skipUnless(native_backend() and os.environ.get("CBUS_UNITSPEC_DIR"),
                     "Select native C-Gate and unit specs for the focused SENPILL case")
class FocusedSenpillNativeTest(unittest.TestCase):
    """Native case: one admitted profile, focused vectors, save/reload, refusal."""

    @classmethod
    def setUpClass(cls):
        cls.service = None
        cls.host = os.environ.get("CBUS_CGATE_TEST_HOST")
        cls.port = int(os.environ.get("CBUS_CGATE_TEST_PORT", "20023"))
        if native_backend() == "local":
            from research.local_cgate import LocalCGate

            cls.service = LocalCGate(os.environ["CBUS_LOCAL_CGATE_VENDOR"])
            cls.addClassCleanup(cls.service.close)
            (cls.service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
            cls.service.start()
            cls.host, cls.port = "127.0.0.1", cls.service.port
        from cbus_toolkit.unitspec import UnitSpecStore

        cls.store = UnitSpecStore(os.environ["CBUS_UNITSPEC_DIR"])

    @staticmethod
    def raw_bytes(session, address, count):
        return bytes.fromhex(session.get_raw_data(address, count).lines[-1].split("RawData=", 1)[1])

    def test_focused_vectors_preservation_save_reload_and_refusal(self):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer

        project = "SP" + uuid4().hex[:6].upper()
        network = f"//{project}/254"
        sensor = Multisensor(self.store.load("SENPILL_ST7.xml"))
        with CGateClient(self.host, self.port, timeout=30) as client:
            client.command("PROJECT NEW " + project)
            try:
                client.command("PROJECT USE " + project)
                client.command("DBCREATENET 254 Sensor_Offline Cni 127.0.0.1:29999")
                client.command("NET LOAD DB " + project)
                client.command("PROJECT SAVE " + project)
                NativeDatabase(client).create_unit(network, 230, "Sensor_230", "SENPILL", "2.3.00",
                                                   catalog_number="5753PEIRL")
                programmer = Programmer(client)
                with programmer.load(network, "/db" + network + "/p/230") as session:
                    self.assertEqual((session.unit_type, session.firmware, session.catalog_number),
                                     ("SENPILL", "2.3.00", "5753PEIRL"))
                    session.reset_defaults()
                    baseline = session.values()
                    result = sensor.configure(session, **FOCUSED_OPTIONS)
                    self.assertEqual((result["firmware"], result["catalog_number"]), ("2.3.00", "5753PEIRL"))
                    self.assertEqual(tuple(int(v.split()[2], 0) for v in
                                           (session.values()["JPCommand"], session.values()["SRCommand"],
                                            session.values()["LPCommand"], session.values()["LRCommand"])),
                                     (13, 7, 7, 0))
                    self.assertEqual(self.raw_bytes(session, 51, 1), bytes((6,)))
                    self.assertEqual(self.raw_bytes(session, 80 + 2, 1), bytes((31,)))
                    self.assertEqual(self.raw_bytes(session, 136 + 2, 1)[0] * 256
                                     + self.raw_bytes(session, 144 + 2, 1)[0], 513)
                    self.assertEqual(self.raw_bytes(session, 27, 2), bytes((55, 6)))
                    after = session.values()
                    unrelated = sorted(n for n in after if n not in LAYOUTS)
                    self.assertEqual({n: after[n] for n in unrelated},
                                     {n: baseline[n] for n in unrelated})
                    expected = sensor.snapshot(after)
                    session.save_to_source()
                client.command("PROJECT SAVE " + project)
                with programmer.load(network, "/db" + network + "/p/230") as session:
                    self.assertEqual(sensor.snapshot(session.values()), expected)
                    self.assertEqual(sensor.plan(session.values(), **FOCUSED_OPTIONS).changes, {})
                NativeDatabase(client).create_unit(network, 231, "Refused_231", "SENPIRIA", "2.3.00",
                                                   catalog_number="5751L")
                with programmer.load(network, "/db" + network + "/p/231") as session:
                    before = session.values()
                    with self.assertRaisesRegex(SensorError, "Native session must"):
                        sensor.configure(session, key=3, event="night", group=31)
                    self.assertEqual(session.values(), before)
            finally:
                client.command("PROJECT CLOSE " + project)
                try:
                    client.command("PROJECT DELETE " + project)
                except Exception:  # noqa: BLE001 - deletion is best effort
                    pass


if __name__ == "__main__":
    unittest.main()
