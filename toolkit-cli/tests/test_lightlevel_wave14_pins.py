"""Wave-14 offline pins for SENLL ST7 profile/threshold guards (P5.04 #41).

Narrow scope: pure profile + threshold helpers from
cbus_toolkit.light_level_sensors only. No session, spec XML, I/O, or save path.
"""

import pytest

from cbus_toolkit.light_level_sensors import (
    MAX_TARGET,
    MAX_TARGET_LUX,
    PROFILE,
    check_profile,
    indicator_state,
    profile_refusal,
    target_byte,
)
from cbus_toolkit.sensors import SensorError


def test_wave14_profile_accepts_admitted_senll_identity():
    assert profile_refusal('SENLL', '2.0.01', '5031PE') is None
    assert profile_refusal('SENLL', '2.4.99', 'SLC5031PEWP,GY') is None
    assert check_profile('SENLL', '2.2.00', '5031PE') == ('SENLL', '2.2.00', '5031PE')


def test_wave14_profile_refuses_class_firmware_and_catalog():
    senlla = profile_refusal('SENLLA', '2.2.00', '5031PE')
    assert senlla is not None and 'TSENLLA' in senlla
    old_firmware = profile_refusal('SENLL', '1.0.00', '5031PE')
    assert old_firmware is not None and 'TST7SENLL' in old_firmware
    above_band = profile_refusal('SENLL', '2.5.00', '5031PE')
    assert above_band is not None
    bad_catalog = profile_refusal('SENLL', '2.2.00', 'NOPE')
    assert bad_catalog is not None and 'catalogue' in bad_catalog.lower()
    with pytest.raises(SensorError):
        check_profile('SENLLA', '2.2.00', '5031PE')
    with pytest.raises(SensorError):
        check_profile('SENLL', '2.2.00', 'NOPE')


def test_wave14_target_byte_thresholds():
    assert MAX_TARGET == 200
    assert MAX_TARGET_LUX == 2000
    assert target_byte(0) == 0
    assert target_byte(1) == 1
    assert target_byte(10) == 1
    assert target_byte(11) == 2
    assert target_byte(2000) == 200
    with pytest.raises(SensorError):
        target_byte(2001)
    with pytest.raises(SensorError):
        target_byte(-1)


def test_wave14_indicator_state_thresholds():
    assert indicator_state(5) == 'enable'
    assert indicator_state(2) == 'on_off'
    assert indicator_state(1) == 'light_level'
    assert indicator_state(0) == 'light_level'
    assert indicator_state(255) == 'light_level'
    assert set(PROFILE['bands'])
