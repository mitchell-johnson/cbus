"""Wave 15 offline pins: eDLT display preference/registry/toolkit guards.

Narrow scope: only cbus_toolkit.edlt_display_model preference guards.
No Rust, DIN, light-level, templates, IOPE, scenes, barcode, thermostat,
or parity-register coverage.
"""

import pytest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_display_model import (
    REGISTRY_NAMES,
    TOOLKIT_DISPLAY_NAMES,
    EdltDisplayPreferences,
)


def test_wave15_registry_dword_sign_extension_guard():
    # 0xFFFFFFFF is (int)-1 -> not > 0 -> false; 1 -> true; 0 -> false.
    prefs = EdltDisplayPreferences.from_registry(
        {name: 0xFFFFFFFF for name in REGISTRY_NAMES}
    )
    assert prefs._flags() == (False,) * 5
    prefs = EdltDisplayPreferences.from_registry(
        {name: 1 for name in REGISTRY_NAMES}
    )
    assert prefs._flags() == (True,) * 5
    prefs = EdltDisplayPreferences.from_registry({"DisplayHexAddress": 1})
    assert prefs.display_hex is True
    assert prefs.display_address_value is False
    # C# (int) view: bools and out-of-DWORD-range values are rejected.
    for bad in (True, -(2**31) - 1, 2**32, 1.0, "1"):
        with pytest.raises(EdltError):
            EdltDisplayPreferences.from_registry({"DisplayHexAddress": bad})


def test_wave15_registry_absent_key_rejects_values_guard():
    with pytest.raises(EdltError):
        EdltDisplayPreferences.from_registry(
            {"DisplayHexAddress": 1}, key_present=False
        )
    # Absent key with no values keeps static defaults (all false).
    prefs = EdltDisplayPreferences.from_registry(key_present=False)
    assert prefs._flags() == (False,) * 5
    with pytest.raises(EdltError):
        EdltDisplayPreferences.from_registry(
            {"Bogus": 1}, key_present=True
        )


def test_wave15_toolkit_byte_boundary_guard():
    prefs = EdltDisplayPreferences.from_toolkit_display_values(
        {name: 255 for name in TOOLKIT_DISPLAY_NAMES}
    )
    assert prefs._flags() == (True,) * 5
    prefs = EdltDisplayPreferences.from_toolkit_display_values(
        {name: 0 for name in TOOLKIT_DISPLAY_NAMES}
    )
    assert prefs._flags() == (False,) * 5
    mixed = {name: (1 if i % 2 == 0 else 0)
             for i, name in enumerate(TOOLKIT_DISPLAY_NAMES)}
    prefs = EdltDisplayPreferences.from_toolkit_display_values(mixed)
    assert prefs.display_hex is True
    assert prefs.display_address_value is False
    for bad in (256, -1, "1", None, 1.0):
        with pytest.raises(EdltError):
            EdltDisplayPreferences.from_toolkit_display_values(
                {name: (bad if name == "tag_hex" else 0)
                 for name in TOOLKIT_DISPLAY_NAMES}
            )


def test_wave15_sort_by_address_kind_guard():
    prefs = EdltDisplayPreferences(
        False, False, True, False, True
    )
    assert prefs.sort_by_address("application") is True
    assert prefs.sort_by_address("group") is False
    assert prefs.sort_by_address("level") is True
    for bad in ("unit", "Application", "", None, 0):
        with pytest.raises(EdltError):
            prefs.sort_by_address(bad)
