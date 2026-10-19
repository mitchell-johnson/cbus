"""P5.03 (#40) smallest safe relay subset: RELDN4 full offline lifecycle.

Narrow scope: one admitted DIN relay profile (RELDN4, firmware 2.7.00)
with a synthetic spec and loopback-style PP session. No hardware,
vendor EXE, C-Gate server, or decoded vendor spec is required; every
refusal fires before any session write.

Covers for RELDN4 only: targeted plan with literal vectors, apply with
verified readback and raw PP byte assertions, stale-plan refusal,
unrelated-parameter preservation, Toolkit-save projection plus
save/reload idempotence, and profile/tab refusals. Other profiles,
RELDN8SP, RELAY4/DIMMER4, logic-engine code, and physical behaviour
stay open under #40.
"""

import json

import pytest

from cbus_toolkit.din_output_settings import (
    FIRMWARE,
    DinOutputEditor,
    DinPlan,
    DinSettingsApplyError,
    DinSettingsError,
    check_profile,
    level_to_percent,
    percent_to_level,
    profile_refusal,
)
from cbus_toolkit.memory import MemoryImage
from cbus_toolkit.unitspec import ParameterSpec, UnitSpec

from cbus_toolkit.din_output_settings import LAYOUTS, PROFILES


def fixture(unit_type="RELDN4"):
    """Synthetic spec with the admitted RELDN4 layout plus unrelated params."""
    profile = PROFILES[unit_type]
    rows = dict(LAYOUTS[profile.spec_filename])
    count = rows["LevelStoreEnable"][1]
    defaults = {
        "InterLockingChannel": [0],
        "LogicLevelStoreEnable": [1] * 4,
        "RestrikeDelay": [60],
        "GroupAddress": [255] * 16,
        "LightLevel": [0] * 16,
        "LevelStoreEnable": [1] * count,
        "PowerUpDelay": [5] * count,
        "MinDimmingLevel": [0] * count,
        "MaxDimmingLevel": [255] * rows["MaxDimmingLevel"][1],
    }
    parameters = {}
    for name, (address, size, bits, bit, skip, kind) in rows.items():
        fields = {
            "Name": name,
            "Type": kind,
            "Address": str(address),
            "ArraySize": str(size),
            "BitAddress": str(bit),
            "ArraySkip": str(skip),
            "DefaultValue": " ".join(map(str, defaults.get(name, [0] * size))),
        }
        if kind == "int":
            fields.update(
                BitSize=str(bits),
                MinValue="0",
                MaxValue="1" if bits == 1 else "255",
            )
        parameters[name] = ParameterSpec(
            name, kind, "literal-din-fixture.xml", fields
        )
    for name, address, value in (
        ("UnitAddress", 32, "255"),
        ("AreaGroupAddress", 67, "255"),
    ):
        parameters[name] = ParameterSpec(
            name,
            "int",
            "literal-din-fixture.xml",
            {"Name": name, "Type": "int", "Address": str(address),
             "DefaultValue": value},
        )
    return UnitSpec(
        profile.spec_filename,
        {"Type": unit_type},
        ("literal-din-fixture.xml",),
        parameters,
    )


class _Session:
    """Minimal native-like PP session over the synthetic spec."""

    def __init__(self, spec):
        import xml.etree.ElementTree as ET

        self._et = ET
        self.unit_type = spec.unit_type
        self.firmware = FIRMWARE
        self.catalog_number = None
        self.spec = spec
        self.current = spec.defaults()
        self.calls = []
        self.failure = None

    def values(self):
        return dict(self.current)

    def info(self, name):
        root = self._et.Element("Parameters")
        for parameter in self.spec.parameters.values():
            node = self._et.SubElement(root, "Param")
            for key, value in parameter.fields.items():
                self._et.SubElement(node, key).text = value
        reply_text = self._et.tostring(root, encoding="unicode")

        class _Reply:
            lines = ("347-" + reply_text, "344 End XML")

        return _Reply()

    def set(self, name, value):
        self.calls.append((name, value))
        if self.failure == name:
            self.failure = None
            self.current[name] = value
            raise RuntimeError("simulated failed write")
        self.current[name] = value


def _live():
    return _Session(fixture("RELDN4"))


def test_reldn4_plan_literal_vectors():
    """Single RELDN4 channel plan pins exact stored bytes and conversions."""
    editor = DinOutputEditor(fixture("RELDN4"), "RELDN4")
    current = fixture("RELDN4").defaults()
    # PercentToLevel literals: 40% -> 102, 50% -> 127, 100% -> 255.
    assert percent_to_level(40) == 102
    assert percent_to_level(50) == 127
    assert percent_to_level(100) == 255
    assert level_to_percent(102) == 40
    plan = editor.plan(
        current,
        channel=1,
        min_percent=40,
        level_store=False,
        recovery_percent=50,
        restrike=True,
        interlock=4,
    )
    assert plan.changes["MinDimmingLevel"] == (102, 0, 0, 0)
    assert plan.changes["LightLevel"][0] == 127
    assert plan.changes["LevelStoreEnable"] == (0, 1, 1, 1)
    assert plan.changes["RestrikeChannel"] == (1, 0, 0, 0)
    assert plan.changes["InterLockingChannel"] == (3,)
    # Raw PP bytes: Min ch1 at 0x60, LightLevel ch1 at 0x00,
    # Restrike ch1 is bit 6 of 0x32, Interlock count 4 stores index 3.
    before = editor.codec.encode_many(plan.expected).apply(
        MemoryImage.from_bytes(bytes(256))
    )
    after = editor.codec.encode_many(plan.changes).apply(before)
    assert after.byte(0x60) == 102
    assert after.byte(0x00) == 127
    assert after.byte(0x32) == 0x40
    assert after.byte(0x30) == 3


def test_reldn4_logic_plan_literal_bytes():
    """Logic association + Or pins the shared 0x32 byte (bits 0 and 7)."""
    editor = DinOutputEditor(fixture("RELDN4"), "RELDN4")
    current = fixture("RELDN4").defaults()
    current["GroupAddress"] = " ".join(["255"] * 12 + ["30", "255", "255", "255"])
    plan = editor.plan(
        current, channel=1, logic_groups=[1], logic_function="or"
    )
    assert plan.changes["LogicGA13Associations"] == (1, 0, 0, 0)
    assert plan.changes["LogicFunction"] == (1, 0, 0, 0)
    before = editor.codec.encode_many(plan.expected).apply(
        MemoryImage.from_bytes(bytes(256))
    )
    after = editor.codec.encode_many(plan.changes).apply(before)
    assert after.byte(0x32) == 0x81
    assert after.byte(0x50 + 12) == 30


def test_reldn4_apply_readback_and_raw_bytes():
    """Apply stages, verifies readback, and preserves unrelated params."""
    editor = DinOutputEditor(fixture("RELDN4"), "RELDN4")
    live = _live()
    live.current["UnitAddress"] = "12"
    live.current["AreaGroupAddress"] = "7"
    plan = editor.plan(
        live.values(),
        channel=1,
        min_percent=40,
        level_store=False,
        recovery_percent=50,
        restrike=True,
        interlock=4,
    )
    result = editor.apply(live, plan)
    assert result["verified"] is True
    assert result["saved"] is False
    assert result["unit_type"] == "RELDN4"
    assert set(name for name, _ in live.calls) == set(plan.changes)
    expected = dict(plan.expected)
    expected.update(plan.changes)
    assert editor.snapshot(live.values()) == expected
    # Raw readback of the staged session matches the literal plan.
    image = editor.codec.encode_many(expected).apply(
        MemoryImage.from_bytes(bytes(256))
    )
    assert image.byte(0x60) == 102
    assert image.byte(0x00) == 127
    assert image.byte(0x32) == 0x40
    assert image.byte(0x30) == 3
    # Unrelated parameters survive the apply untouched.
    assert live.current["UnitAddress"] == "12"
    assert live.current["AreaGroupAddress"] == "7"
    # Serialized plan round-trips and stale detection fires after apply.
    clone = DinPlan.from_dict(json.loads(json.dumps(plan.as_dict())))
    assert clone == plan
    with pytest.raises(DinSettingsError, match="changed since"):
        editor.apply(live, plan)


def test_reldn4_toolkit_save_projection_and_reload_idempotent():
    """Toolkit-save normalizes owned fields once; a second save is empty."""
    live = _live()
    live.current.update(
        {
            "GroupAddress": " ".join(str(40 + n) for n in range(16)),
            "LightLevel": " ".join(str(10 + n) for n in range(16)),
        }
    )
    editor = DinOutputEditor(live.spec, "RELDN4")
    plan = editor.plan(live.values(), toolkit_save=True)
    assert plan.toolkit_save is True
    assert plan.as_dict()["format"] == "cbus-din-output-settings-plan-v2"
    final = dict(plan.expected)
    final.update(plan.changes)
    # Level-store channels rewrite to 255; tail pads; interlock masked.
    assert final["LightLevel"] == (
        255, 255, 255, 255, 0, 0, 0, 0, 0, 0, 0, 0, 22, 23, 24, 25
    )
    assert final["GroupAddress"][4:12] == (255,) * 8
    assert final["InterLockingChannel"] == (0,)
    assert plan.pre_save_changes == {}
    result = editor.apply(live, plan)
    assert result["verified"] is True
    assert editor.snapshot(live.values()) == final
    second = editor.plan(live.values(), toolkit_save=True)
    assert second.changes == {}
    assert second.pre_save_changes == {}
    assert second.save_normalization == {}


def test_reldn4_refusals_leave_session_unchanged():
    """Profile and tab guards refuse before any PP write."""
    editor = DinOutputEditor(fixture("RELDN4"), "RELDN4")
    current = fixture("RELDN4").defaults()
    # Profile refusals.
    assert "nine channels" in profile_refusal("RELDN8SP", FIRMWARE)
    assert "2.7.00" in profile_refusal("RELDN4", "2.6.00")
    with pytest.raises(DinSettingsError, match="Native session"):
        check_profile("RELDN4", "2.6.00", subject="Native session")
    # Relay Turn On binds only the minimum threshold.
    with pytest.raises(DinSettingsError, match="minimum threshold"):
        editor.plan(current, channel=1, max_percent=50)
    # Interlock domain for 4 channels.
    with pytest.raises(DinSettingsError, match="Interlock"):
        editor.plan(current, interlock=1)
    # Restrike delay needs an enabled restrike channel.
    with pytest.raises(DinSettingsError, match="restrike delay until"):
        editor.plan(current, restrike_delay=100)
    # Logic group without a group address is refused (UnusedGroupInLogic).
    with pytest.raises(DinSettingsError, match="Logic group 1 is associated"):
        editor.plan(current, channel=1, logic_groups=[1])
    # Recovery slider disabled while level store is set.
    with pytest.raises(DinSettingsError, match="disables the recovery"):
        editor.plan(current, channel=1, recovery_percent=50)
    # Channel out of range for the 4-channel profile.
    with pytest.raises(DinSettingsError, match="Channel must"):
        editor.plan(current, channel=5, min_percent=10)
    # Failed plan performs no writes.
    live = _live()
    before = live.values()
    with pytest.raises(DinSettingsError):
        editor.plan(before, channel=1, max_percent=50)
    assert live.values() == before
    assert live.calls == []
    # Partial-failure apply reports attempted params and stays unsaved.
    live2 = _live()
    plan = editor.plan(
        live2.values(), channel=1, min_percent=10, interlock=2
    )
    live2.failure = "MinDimmingLevel"
    with pytest.raises(DinSettingsApplyError) as error:
        editor.apply(live2, plan)
    assert "MinDimmingLevel" in error.value.attempted
    assert error.value.details["saved"] is False
