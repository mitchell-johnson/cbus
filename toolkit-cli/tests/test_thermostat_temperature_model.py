"""Retained-literal independent codec tests using surviving captured original rows.

No original code, static verifier, service or controller is executed. Expected
data never imports the producer's arithmetic or field-rule table.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from cbus_toolkit.thermostat_temperature_model import (
    TEMPERATURE_FIELDS, TemperatureModelError,
    decode_temperature_fields, encode_temperature_fields,
)

RESEARCH = Path(os.environ.get('CBUS_TEMPERATURE_CAPTURE_RESEARCH',
                              str(Path(__file__).resolve().parents[1] / 'research')))
SOURCE_SHA = '188050a51a4324b0039dba68383a66d528baabcfe88210b3634ba1f372fd31d0'
MATRIX_SHA = 'e9314238899efbdb8c6b071bf5541adf54dfba80ddfc2980b9d6a598a5062528'
STATIC_SHA = '73b0cd96f23872695f1cd4b291b4d4c3f7360925d90185595d0520a382b831c4'

# Independent agent field/profile transcription, checked against the retained
# static evidence. It is intentionally not the producer's imported rule table.
RULES = {
    'MaximumSetTemperature': ('SimpleCGateTempToUnitTemp', 'SimpleUnitTempToCGateTemp', True, None),
    'MinimumSetTemperature': ('SimpleCGateTempToUnitTemp', 'SimpleUnitTempToCGateTemp', True, None),
    'GuardUpperTemperature': ('CGateTempToUnitTemp', 'UnitTempToCGateTemp', True, 127),
    'GuardMaximumUpperTemperature': ('CGateTempToUnitTemp', 'UnitTempToCGateTemp', True, 127),
    'GuardMinimumUpperTemperature': ('CGateTempToUnitTemp', 'UnitTempToCGateTemp', True, None),
    'GuardLowerTemperature': ('CGateTempToUnitTemp', 'UnitTempToCGateTemp', True, None),
    'GuardMaximumLowerTemperature': ('CGateTempToUnitTemp', 'UnitTempToCGateTemp', True, None),
    'GuardMinimumLowerTemperature': ('CGateTempToUnitTemp', 'UnitTempToCGateTemp', True, None),
    'SetbackLevel': ('CGateTempToTempOffsetWithShift', 'TempOffsetWithShiftToCGateTemp', True, None),
    'EvapStartProportionalTemperature': ('CGateTempToTempOffset', 'TempOffsetToCGateTemp', True, None),
    'EvapStopProportionalTemperature': ('CGateTempToTempOffset', 'TempOffsetToCGateTemp', True, None),
    'TemperatureOffset': ('CGate16thDegreeToQuarterDegreeTempOffset', 'QuarterDegreesTempOffsetToCGateTemp', True, None),
    'TemperatureSendDifferential': ('CGate16thDegreeToQuarterDegreeTempOffset', 'QuarterDegreesTempOffsetToCGateTemp', False, None),
    'EvapComfortStartTemp': ('CGateTempToWholeDegreesTemp', 'WholeDegreesTempToCGateTemp', False, None),
    'EvapComfortStepSize': ('CGateTempToHalfDegreesTempOffset', 'HalfDegreesTempOffsetToCGateTemp', False, None),
}


def pinned(relative, expected):
    raw = (RESEARCH / relative).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected
    return json.loads(raw)


@pytest.fixture(scope='module')
def captured():
    fixture = pinned('fixtures/thermostat-temperature-vectors.json', SOURCE_SHA)
    result = {}
    for index, fahrenheit, value, expected in fixture['extended_original_emulator']:
        key = fixture['methods'][index], fahrenheit, value
        assert key not in result
        result[key] = expected
    assert len(result) == 28840
    overlap = 0
    for index, fahrenheit, value, expected in fixture['native_windows_original']:
        key = fixture['methods'][index], fahrenheit, value
        if key in result:
            assert result[key] == expected
            overlap += 1
        result[key] = expected
    assert overlap == 1092
    assert len(result) == 28924
    return result


def expected_decode(raw, fahrenheit, captured):
    result = {}
    for field, (load, _save, signed, _cap) in RULES.items():
        incoming = raw[field] - 256 if signed and raw[field] >= 128 else raw[field]
        result[field] = captured[load, fahrenheit, incoming]
    return result


def expected_encode(live, fahrenheit, captured):
    result = {}
    for field, (_load, save, signed, cap) in RULES.items():
        value = captured[save, fahrenheit, live[field]]
        if cap is not None:
            value = min(value, cap)
        result[field] = value & 255 if signed else value
    return result


def test_retained_evidence_identity_and_complete_field_roster(captured):
    matrix = pinned('fixtures/thermostat-settings-temperature-roundtrip-vectors.json', MATRIX_SHA)
    report = pinned('experiments/2026-09-30/thermostat-settings-temperature-static.json', STATIC_SHA)
    assert len(report['checks']) == 87
    assert all(value is True for value in report['checks'].values())
    assert report['original_executed_this_run'] is False
    assert report['production_conversion_oracle_used'] is False
    assert isinstance(TEMPERATURE_FIELDS, tuple)
    assert len(TEMPERATURE_FIELDS) == 15
    assert set(TEMPERATURE_FIELDS) == set(RULES) == set(matrix['fields']) == set(report['fields'])
    joined = 0
    for profile_name, profile in matrix['profiles'].items():
        assert len(profile['rows']) == 512
        assert {(r[0], r[1]) for r in profile['rows']} == {(f, b) for f in (False, True) for b in range(256)}
        fields = [name for name, profile in matrix['fields'].items() if profile == profile_name]
        for field in fields:
            load, save, signed, cap = RULES[field]
            assert (profile['load_method'], profile['save_method'], profile['signed_input'],
                    profile['upper_127_cap_after_save_conversion']) == (load, save, signed, cap is not None)
        for fahrenheit, raw, loaded, converted, stored in profile['rows']:
            incoming = raw - 256 if profile['signed_input'] and raw >= 128 else raw
            assert loaded == captured[profile['load_method'], fahrenheit, incoming]
            assert converted == captured[profile['save_method'], fahrenheit, loaded]
            expected = min(converted, 127) if profile['upper_127_cap_after_save_conversion'] else converted
            assert stored == (expected & 255 if profile['signed_input'] else expected)
            joined += 1
    assert joined == 4608


@pytest.mark.parametrize('units,fahrenheit', [('celsius', False), ('fahrenheit', True)])
def test_decode_every_field_byte_and_ignore_device_preference(units, fahrenheit, captured):
    for raw_byte in range(256):
        raw = dict.fromkeys(RULES, raw_byte)
        expected = expected_decode(raw, fahrenheit, captured)
        for device_units in (0, 1):
            snapshot = dict(raw, TemperatureUnits=device_units, UnrelatedParameter=77)
            before = copy.deepcopy(snapshot)
            actual = decode_temperature_fields(snapshot, temperature_preference=units)
            assert actual == expected, (units, raw_byte, device_units)
            assert snapshot == before
            assert actual is not snapshot


@pytest.mark.parametrize('units,fahrenheit', [('celsius', False), ('fahrenheit', True)])
def test_encode_every_decoded_field_byte_without_second_load(units, fahrenheit, captured):
    refused = []
    for raw_byte in range(256):
        raw = dict.fromkeys(RULES, raw_byte)
        # The live input here comes from retained capture rows, not decode under test.
        live = expected_decode(raw, fahrenheit, captured)
        expected = expected_encode(live, fahrenheit, captured)
        original = copy.deepcopy(live)
        overflow = sorted(field for field, value in expected.items() if not 0 <= value <= 255)
        if overflow:
            with pytest.raises(TemperatureModelError):
                encode_temperature_fields(live, temperature_preference=units)
            refused.append((raw_byte, overflow))
        else:
            assert encode_temperature_fields(live, temperature_preference=units) == expected, (units, raw_byte)
        assert live == original
    assert refused == ([(254, ['EvapComfortStartTemp', 'EvapComfortStepSize']),
                        (255, ['EvapComfortStartTemp', 'EvapComfortStepSize'])]
                       if not fahrenheit else [(255, ['EvapComfortStartTemp', 'EvapComfortStepSize'])])


@pytest.mark.parametrize('field', list(RULES))
@pytest.mark.parametrize('units,fahrenheit', [('celsius', False), ('fahrenheit', True)])
def test_encode_direct_live_values_against_all_retained_save_observations(field, units, fahrenheit, captured):
    _load, save, signed, cap = RULES[field]
    baseline = expected_decode(dict.fromkeys(RULES, 0), fahrenheit, captured)
    baseline_saved = expected_encode(baseline, fahrenheit, captured)
    rows = [(value, expected) for (method, f, value), expected in captured.items()
            if method == save and f == fahrenheit]
    assert rows
    for value, converted in rows:
        live = dict(baseline)
        live[field] = value
        before = dict(live)
        limited = min(converted, cap) if cap is not None else converted
        stored = limited & 255 if signed else limited
        if not 0 <= stored <= 255:
            with pytest.raises(TemperatureModelError):
                encode_temperature_fields(live, temperature_preference=units)
        else:
            expected = dict(baseline_saved)
            expected[field] = stored
            assert encode_temperature_fields(live, temperature_preference=units) == expected, (field, units, value)
        assert live == before


def test_fahrenheit_live_edit_is_encoded_without_treating_it_as_raw(captured):
    live = expected_decode(dict.fromkeys(RULES, 3), True, captured)
    live.update(MinimumSetTemperature=50, MaximumSetTemperature=86)
    expected = expected_encode(live, True, captured)
    assert expected['MinimumSetTemperature'] == 10
    assert expected['MaximumSetTemperature'] == 30
    saved = encode_temperature_fields(live, temperature_preference='fahrenheit')
    assert saved == expected
    assert saved['MinimumSetTemperature'] != live['MinimumSetTemperature']


@pytest.mark.parametrize('raw_guard', [126, 127])
def test_exact_one_save_guard_cap_and_non_fixed_point(raw_guard, captured):
    raw = dict.fromkeys(RULES, 0)
    raw.update(GuardUpperTemperature=raw_guard, GuardMinimumUpperTemperature=raw_guard)
    first_live = expected_decode(raw, False, captured)
    first_expected = expected_encode(first_live, False, captured)
    assert first_expected['GuardUpperTemperature'] == 127
    assert first_expected['GuardMinimumUpperTemperature'] == 128
    first = encode_temperature_fields(first_live, temperature_preference='celsius')
    assert first == first_expected
    # Repeating encode on the same live model never silently redecodes it.
    assert encode_temperature_fields(first_live, temperature_preference='celsius') == first_expected
    # A separately requested new load/save is a different source operation.
    second_live = decode_temperature_fields(first, temperature_preference='celsius')
    assert second_live == expected_decode(first, False, captured)
    second = encode_temperature_fields(second_live, temperature_preference='celsius')
    assert second == expected_encode(second_live, False, captured)
    assert second['GuardMinimumUpperTemperature'] == 129


@pytest.mark.parametrize('units', ['celsius', 'fahrenheit'])
def test_all_fields_required_and_domain_refusals_leave_inputs_unchanged(units, captured):
    raw = dict.fromkeys(RULES, 0)
    live = expected_decode(raw, units == 'fahrenheit', captured)
    for field in RULES:
        missing_raw = dict(raw); del missing_raw[field]
        missing_live = dict(live); del missing_live[field]
        with pytest.raises(TemperatureModelError):
            decode_temperature_fields(missing_raw, temperature_preference=units)
        with pytest.raises(TemperatureModelError):
            encode_temperature_fields(missing_live, temperature_preference=units)
        for invalid in (True, False, None, '3', 1.0, -1, 256):
            altered = dict(raw); altered[field] = invalid
            original = copy.deepcopy(altered)
            with pytest.raises(TemperatureModelError):
                decode_temperature_fields(altered, temperature_preference=units)
            assert altered == original
        for invalid in (True, None, '3', 1.0, -(1 << 31) - 1, 1 << 31):
            altered = dict(live); altered[field] = invalid
            original = copy.deepcopy(altered)
            with pytest.raises(TemperatureModelError):
                encode_temperature_fields(altered, temperature_preference=units)
            assert altered == original


def test_mapping_and_explicit_preference_are_required(captured):
    raw = dict.fromkeys(RULES, 0)
    live = expected_decode(raw, False, captured)
    for invalid in (None, True, '', 'Celsius', 'Fahrenheit', 'kelvin', 0):
        with pytest.raises(TemperatureModelError):
            decode_temperature_fields(raw, temperature_preference=invalid)
        with pytest.raises(TemperatureModelError):
            encode_temperature_fields(live, temperature_preference=invalid)
    for invalid in (None, [], tuple(raw.items()), 'raw'):
        with pytest.raises(TemperatureModelError):
            decode_temperature_fields(invalid, temperature_preference='celsius')
        with pytest.raises(TemperatureModelError):
            encode_temperature_fields(invalid, temperature_preference='celsius')
