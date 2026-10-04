"""Independent retained-literal acceptance for the owned temperature boundary.

These tests execute owned Python only. Private live-store edits exercise the
serializer boundary; they do not introduce public slider or timing callbacks.
"""
from copy import copy, deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest

from cbus_toolkit import thermostat_quick_zone_controls as owner_module
from cbus_toolkit import thermostat_settings as settings_module
from cbus_toolkit.thermostat_post_load import form_save_temperatures
from cbus_toolkit.thermostat_quick_zone_controls import prepare_quick_zone_save
from cbus_toolkit.thermostat_remote_references import snapshot_project, validate_remote_plan
from cbus_toolkit.thermostat_settings import NativeThermostatSettings, plan_settings
from cbus_toolkit.thermostat_templates import ThermostatTemplateError, NativeThermostatTemplateError, _unit_record
from cbus_toolkit.unitspec import UnitSpecStore
from test_thermostat_quick_zone_controls import model
from test_thermostat_quick_zone_controls_backends import source_seed, pp_names
from test_thermostat_remote_references import project
from test_thermostat_settings import _spec

ALIASES = ('PC_TSA', 'PC_TSA5', 'PC_TSB', 'PC_TSB5')
CAPTURE_SHA = '188050a51a4324b0039dba68383a66d528baabcfe88210b3634ba1f372fd31d0'
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
GUARDS = {'GuardMinimumUpperTemperature': 126, 'GuardLowerTemperature': 127,
          'GuardUpperTemperature': 126, 'GuardMaximumUpperTemperature': 127}


@pytest.fixture(scope='module')
def captured():
    folder = Path(os.environ.get('CBUS_TEMPERATURE_CAPTURE_RESEARCH',
                                 str(Path(__file__).resolve().parents[1] / 'research')))
    raw = (folder / 'fixtures/thermostat-temperature-vectors.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == CAPTURE_SHA
    fixture = json.loads(raw)
    lookup = {}
    for scope in ('extended_original_emulator', 'native_windows_original'):
        for index, preference, value, expected in fixture[scope]:
            key = fixture['methods'][index], preference, value
            if key in lookup:
                assert lookup[key] == expected
            lookup[key] = expected
    assert len(lookup) == 28924
    return lookup


def load_literal(raw, captured):
    return {field: captured[load, False, raw[field] - 256 if signed and raw[field] >= 128 else raw[field]]
            for field, (load, _, signed, _) in RULES.items()}


def save_literal(live, captured):
    result = {}
    for field, (_, save, signed, cap) in RULES.items():
        value = captured[save, False, live[field]]
        value = min(value, cap) if cap is not None else value
        result[field] = value & 255 if signed else value
    return result


@pytest.mark.parametrize('kind', ALIASES)
def test_owner_complete_load_once_and_repeat_encode_once(kind, captured):
    codec = owner_module.temperature_model
    with patch.object(codec, 'decode_temperature_fields', wraps=codec.decode_temperature_fields) as decode, \
            patch.object(codec, 'encode_temperature_fields', wraps=codec.encode_temperature_fields) as encode:
        m = model(kind, changes=GUARDS | {'TemperatureUnits': 1})
        original = deepcopy(m.source)
        loaded = load_literal(original, captured)
        assert {n: m.values[n] for n in RULES} == loaded
        assert m.values is m.output.values is m.plant.values
        assert decode.call_count == 1 and encode.call_count == 0
        first = m.issue_save()
        expected = save_literal(loaded, captured)
        assert {n: prepare_quick_zone_save(m, first)[n] for n in RULES} == expected
        assert {n: m.values[n] for n in RULES} == loaded
        second = m.issue_save()
        assert {n: prepare_quick_zone_save(m, second)[n] for n in RULES} == expected
        assert decode.call_count == 1 and encode.call_count == 2
        assert m.source == original
        diagnostic = m.as_dict()['temperature_model']
        assert diagnostic['raw'] == {n: original[n] for n in RULES}
        assert diagnostic['loaded'] == diagnostic['live'] == loaded
        assert diagnostic['encoded'] == expected
        assert diagnostic['device_units_used_as_preference'] is False
        assert diagnostic['load_conversions_are_not_control_notifications'] is True


@pytest.mark.parametrize('kind', ALIASES)
def test_distinct_new_load_differs_from_repeated_serialization(kind):
    m = model(kind, changes=GUARDS)
    assert m.values['GuardMinimumUpperTemperature'] == m.values['GuardLowerTemperature'] == 52
    first = prepare_quick_zone_save(m, m.issue_save())
    assert {n: first[n] for n in GUARDS} == {
        'GuardMinimumUpperTemperature': 128, 'GuardLowerTemperature': 128,
        'GuardUpperTemperature': 127, 'GuardMaximumUpperTemperature': 127}
    assert prepare_quick_zone_save(m, m.issue_save())['GuardLowerTemperature'] == 128
    reloaded = model(kind, changes={n: first[n] for n in RULES})
    assert reloaded.values['GuardMinimumUpperTemperature'] == reloaded.values['GuardLowerTemperature'] == -12
    second = prepare_quick_zone_save(reloaded, reloaded.issue_save())
    assert {n: second[n] for n in GUARDS} == {
        'GuardMinimumUpperTemperature': 129, 'GuardLowerTemperature': 129,
        'GuardUpperTemperature': 127, 'GuardMaximumUpperTemperature': 127}


@pytest.mark.parametrize('kind', ALIASES)
def test_owned_live_edit_encodes_directly_without_reloading(kind, captured):
    m = model(kind)
    raw = deepcopy(m.source)
    m.values['GuardLowerTemperature'] = 52
    expected = save_literal({n: m.values[n] for n in RULES}, captured)
    assert expected['GuardLowerTemperature'] == 128
    assert {n: prepare_quick_zone_save(m, m.issue_save())[n] for n in RULES} == expected
    assert m.values['GuardLowerTemperature'] == 52 and m.source == raw


@pytest.mark.parametrize('field,value', [
    ('GuardLowerTemperature', True), ('GuardLowerTemperature', 1.5),
    ('GuardLowerTemperature', 2**31), ('GuardLowerTemperature', -(2**31)-1),
    ('GuardLowerTemperature', None), ('EvapComfortStartTemp', 128),
    ('TemperatureSendDifferential', -1), ('EvapComfortStepSize', 128),
], ids=['bool','float','high-int32','low-int32','missing-live','unsigned-whole-overflow',
        'unsigned-negative','unsigned-half-overflow'])
def test_invalid_live_state_refuses_without_issuing_save(field, value):
    m = model()
    m.values[field] = value
    with pytest.raises(ThermostatTemplateError):
        m.issue_save()
    assert m._issued_save is None


@pytest.mark.parametrize('mutation', ['preference', 'raw-source', 'replaced-store', 'post-issue-value'])
def test_original_owner_seal_rejects_mutation(mutation):
    m = model(changes=GUARDS)
    saved = m.issue_save()
    if mutation == 'preference':
        m.temperature_preference = 'fahrenheit'
    elif mutation == 'raw-source':
        m.source['GuardLowerTemperature'] = 1
    elif mutation == 'replaced-store':
        m.values = dict(m.values)
    else:
        m.values['GuardLowerTemperature'] = 51
    with pytest.raises(ThermostatTemplateError):
        prepare_quick_zone_save(m, saved)


def test_save_clone_and_foreign_owner_are_not_authority():
    first, second = model(changes=GUARDS), model(changes=GUARDS)
    saved = first.issue_save()
    for owner, value in ((first, replace(saved)), (second, saved), (copy(first), saved)):
        with pytest.raises(ThermostatTemplateError):
            prepare_quick_zone_save(owner, value)


@pytest.fixture
def store(tmp_path):
    for kind in ('THERMOSTATA', 'THERMOSTATB'):
        alias = 'PC_TSB' if kind.endswith('B') else 'PC_TSA'
        (tmp_path / (kind + '.xml')).write_text(_spec(kind, pp_names(alias)))
    return UnitSpecStore(tmp_path)


@pytest.mark.parametrize('kind', ALIASES)
@pytest.mark.parametrize('raw_value,accepted,saved', [(120, True, 120), (126, False, 128)],
                         ids=['raw-survives','raw-rewritten'])
def test_sealed_planner_preserves_raw_set_survival(kind, raw_value, accepted, saved, store):
    m = model(kind, changes={'GuardMinimumUpperTemperature': raw_value})
    issued = m.issue_save()
    raw = {n: str(v) for n, v in m.source.items()}
    before = raw | {'GuardMinimumUpperTemperature': '0'}
    kw = dict(temperature_preference='celsius', _control_owner=m, _control_save=issued)
    if accepted:
        planned = plan_settings(store, kind, before, {'GuardMinimumUpperTemperature': raw_value}, **kw)
        assert planned.expected['GuardMinimumUpperTemperature'] == saved
    else:
        with pytest.raises(ThermostatTemplateError, match='GuardMinimumUpperTemperature=128'):
            plan_settings(store, kind, before, {'GuardMinimumUpperTemperature': raw_value}, **kw)


@pytest.mark.parametrize('bad_pair', ['missing-owner', 'missing-save', 'clone-save', 'foreign-owner',
                                    'raw-mismatch', 'preference-mismatch'])
def test_planner_cannot_bypass_issued_owner_or_raw_snapshot(store, bad_pair):
    m = model(changes=GUARDS)
    issued = m.issue_save()
    kw = dict(temperature_preference='celsius', _control_owner=m, _control_save=issued)
    raw = {n: str(v) for n, v in m.source.items()}
    if bad_pair == 'missing-owner': kw['_control_owner'] = None
    elif bad_pair == 'missing-save': kw['_control_save'] = None
    elif bad_pair == 'clone-save': kw['_control_save'] = replace(issued)
    elif bad_pair == 'foreign-owner': kw['_control_owner'] = model(changes=GUARDS)
    elif bad_pair == 'raw-mismatch': raw['GuardLowerTemperature'] = '126'
    else: kw['temperature_preference'] = 'fahrenheit'
    with pytest.raises(ThermostatTemplateError):
        plan_settings(store, 'PC_TSA5', raw, {}, **kw)


def test_unsealed_temperature_deferral_refuses_and_legacy_roundtrip_survives(store, captured):
    raw = source_seed('PC_TSA5') | GUARDS
    original = deepcopy(raw)
    expected = save_literal(load_literal(raw, captured), captured)
    assert form_save_temperatures(raw, temperature_preference='celsius') == expected
    assert raw == original
    with pytest.raises(ThermostatTemplateError, match='deferred'):
        plan_settings(store, 'PC_TSA5', {n: str(v) for n, v in raw.items()}, {},
                      temperature_preference='celsius', _defer_model_owned=('GuardLowerTemperature',))


class NoWire:
    def command(self, *args, **kwargs):
        raise AssertionError('Offline planning unexpectedly attempted native I/O')


def offline_native(kind, raw, store, monkeypatch):
    document = project(kind, {56: [40, 41, 42, 43, 70, 255], 172: [1],
                              203: [30, 31, 32, 33, 34, 255]}, raw)
    unit = ET.tostring(ET.fromstring(document).find('Project/Network/Unit'), encoding='unicode')
    identity, _, _ = _unit_record(unit, 20)
    native = NativeThermostatSettings(NoWire(), store)
    monkeypatch.setattr(native, '_operation', lambda *a, **k: None)
    monkeypatch.setattr(native, '_networks', lambda *a: ('//REMOTE/11',))
    monkeypatch.setattr(native, '_read', lambda *a: (unit, identity, dict(raw)))
    monkeypatch.setattr(native, '_xml', lambda *a: document)
    return native


@pytest.mark.parametrize('kind', ALIASES)
def test_native_planning_avoids_preliminary_temperature_roundtrip(kind, store, monkeypatch):
    raw = {n: str(v) for n, v in (source_seed(kind) | GUARDS).items()}
    native = offline_native(kind, raw, store, monkeypatch)
    codec = owner_module.temperature_model
    with patch.object(settings_module, 'form_save_temperatures', side_effect=AssertionError('raw roundtrip')), \
            patch.object(codec, 'decode_temperature_fields', wraps=codec.decode_temperature_fields) as decode, \
            patch.object(codec, 'encode_temperature_fields', wraps=codec.encode_temperature_fields) as encode:
        planned = native.plan('//REMOTE/11/p/20', {}, exclusive_project=True,
            temperature_preference='celsius', output_operations=[{'op': 'quick-zone-view'}])
        assert planned.settings.expected['GuardLowerTemperature'] == 128
        assert decode.call_count == encode.call_count == 1
        assert native.last_evidence['complete'] is True
        assert raw['GuardLowerTemperature'] == '127'
        # Validation builds another raw owner; it is not a second load of the
        # already-live owner or an additional server SAVE.
        assert validate_remote_plan(store, planned.remote) == planned.remote
        assert decode.call_count == encode.call_count == 2


@pytest.mark.parametrize('kind', ALIASES)
@pytest.mark.parametrize('edit', [{'GuardMinimumUpperTemperature': 126}, {'EvapComfortStartTemp': 254}],
                         ids=['raw-rewrite','unsigned-overflow'])
def test_native_refuses_raw_rewrite_and_overflow_before_mutation(kind, edit, store, monkeypatch):
    raw = {n: str(v) for n, v in source_seed(kind).items()}
    native = offline_native(kind, raw, store, monkeypatch)
    with pytest.raises(NativeThermostatTemplateError) as error:
        native.plan('//REMOTE/11/p/20', edit, exclusive_project=True,
                    temperature_preference='celsius', output_operations=[{'op': 'quick-zone-view'}])
    assert 'GuardMinimumUpperTemperature=128' in str(error.value) if 'GuardMinimumUpperTemperature' in edit \
        else 'EvapComfortStartTemp save result cannot be represented by one PP byte: 256' in str(error.value)
    state = native.last_evidence
    assert not state['complete'] and not state['outcome_uncertain']
    assert not state['backup_source_save_attempted'] and not state['pp_save_attempted']


@pytest.mark.parametrize('preference', [None, 'fahrenheit'])
def test_owner_initialization_limits_remain_explicit(preference):
    seed = model()
    with pytest.raises(ThermostatTemplateError, match='Settled quick-zone controls require source Celsius minimum15/maximum32/Guard0'):
        owner_module.ThermostatControlModel(seed.output, temperature_preference=preference)


def test_wrong_alias_original_issued_owner_is_refused(store):
    m = model('PC_TSA5', changes=GUARDS)
    raw = {n: str(v) for n, v in m.source.items()}
    with pytest.raises(ThermostatTemplateError, match='differs from raw settings inputs'):
        plan_settings(store, 'PC_TSA', raw, {}, temperature_preference='celsius',
                      _control_owner=m, _control_save=m.issue_save())
