"""Wave23 narrow offline pins for wireless unit globals guards (P5.07)."""
import pytest

from cbus_toolkit.wireless_unit_globals import (
    BEYOND_DIALOG,
    FIELDS,
    TOOLKIT_CONTROLS,
    WirelessGlobalsError,
    WirelessGlobalsPlan,
    check_profile,
    house_code_bytes,
    house_code_text,
    profile_refusal,
    spec_filename,
)


def test_profile_refusal_admits_range_rejects_ez_and_outside():
    assert profile_refusal("WRM8R1", "2.2.0") is None
    assert profile_refusal("WRM2D1", "2.0.0") is None
    assert profile_refusal("WRM4R2", "2.4.99") is None
    assert "EZ" in profile_refusal("WRM2D1EZ", "2.2.0")
    assert profile_refusal("UNKNOWN", "2.2.0") is not None
    assert profile_refusal("WRM8R1", "2.5.0") is not None
    assert profile_refusal("WRM8R1", "not-a-version") is not None


def test_house_code_round_trip_and_display_guard():
    assert house_code_text((0x01, 0x02, 0x03, 0x04)) == "04030201"
    assert house_code_bytes("04030201") == (0x01, 0x02, 0x03, 0x04)
    assert house_code_text(house_code_bytes("aBcDeF12")) == "abcdef12".lower()
    with pytest.raises(WirelessGlobalsError):
        house_code_bytes("1234567")
    with pytest.raises(WirelessGlobalsError):
        house_code_bytes("ZZZZZZZZ")
    with pytest.raises(WirelessGlobalsError):
        house_code_bytes(None)


def test_check_profile_and_plan_from_dict_guards():
    with pytest.raises(WirelessGlobalsError):
        check_profile("WRM2D1EZ", "2.2.0")
    with pytest.raises(WirelessGlobalsError):
        check_profile("WRM8R1", "2.5.0")
    with pytest.raises(WirelessGlobalsError):
        WirelessGlobalsPlan.from_dict({"format": "wrong-format"})
    with pytest.raises(WirelessGlobalsError):
        WirelessGlobalsPlan.from_dict(
            {"format": "cbus-wireless-unit-globals-plan-v1", "unit_type": "WRM2D1EZ",
             "expected": {}, "changes": {}}
        )
    with pytest.raises(WirelessGlobalsError):
        WirelessGlobalsPlan.from_dict(
            {"format": "cbus-wireless-unit-globals-plan-v1", "unit_type": "WRM8R1"}
        )


def test_spec_filename_and_control_sets_disjoint():
    assert spec_filename("WRM8R1") == "WRM8R1_2.xml"
    assert set(TOOLKIT_CONTROLS) <= set(FIELDS)
    assert set(BEYOND_DIALOG) <= set(FIELDS)
    assert not set(TOOLKIT_CONTROLS) & set(BEYOND_DIALOG)
