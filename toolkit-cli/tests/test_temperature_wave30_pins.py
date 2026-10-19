"""Wave 30 offline pins for thermostat temperature guards with zero prior refs.

Pins Int32 shift-wrap and clamp guards in thermostat_temperature.py using
inputs with no prior repository references: a WholeDegrees shift that wraps
to INT32_MIN, QuarterDegrees wraps that land on the -127 floor clamp from
both signs, and a TempOffset shift wrap that carries no clamp.
"""

from cbus_toolkit.thermostat_temperature import convert_temperature


def test_whole_degrees_shift_wraps_to_int32_min():
    assert convert_temperature('WholeDegreesTempToCGateTemp', 1610612736, units='celsius') == -2147483648


def test_quarter_degrees_wrap_hits_floor_clamp():
    assert convert_temperature('QuarterDegreesTempOffsetToCGateTemp', 536870912, units='celsius') == -127


def test_quarter_degrees_negative_wrap_hits_floor_clamp():
    assert convert_temperature('QuarterDegreesTempOffsetToCGateTemp', -536870912, units='celsius') == -127


def test_temp_offset_shift_wraps_without_clamp():
    assert convert_temperature('TempOffsetToCGateTemp', 536870912, units='celsius') == -2147483648
