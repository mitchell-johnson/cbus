"""Bounded classic DLT display controls and full-byte preservation guards."""
from dataclasses import replace
import json

import pytest

from cbus_toolkit.dlt_display import (ADDRESS, FIELDS, LAYOUT, ClassicDltDisplay, DltDisplayPlan)
from cbus_toolkit.dlt_labels import DltLabelApplyError, DltLabelError
from cbus_toolkit.dlt_profiles import PROFILES
from cbus_toolkit.unitspec import ParameterSpec
from test_dlt_labels import fixture as label_fixture
from test_macros import Session


def fixture(filename='KEYL5.xml', spec_type='KEYL5'):
    result = label_fixture(filename, spec_type)
    for name, (bit, bits, kind) in LAYOUT.items():
        fields = {'Name': name, 'Type': kind, 'Address': str(ADDRESS), 'BitAddress': str(bit),
                  'DefaultValue': '1' if name == 'IndicatorMode' else '0'}
        if kind == 'int':
            fields.update(BitSize=str(bits), MinValue='0', MaxValue=str((1 << bits) - 1))
        result.parameters[name] = ParameterSpec(name, kind, 'synthetic-dlt-display.xml', fields)
    return result


def session(unit_type='KEYBL5', firmware='2.1.00', catalog='5085DL'):
    result = Session(fixture(PROFILES[unit_type].spec_filename, 'KEYDL4' if unit_type == 'KEYDL4' else 'KEYL5'))
    result.unit_type, result.firmware, result.catalog_number = unit_type, firmware, catalog
    return result


@pytest.mark.parametrize('raw,mode', [(0, 'off'), (1, 'normal'), (2, 'on'), (3, 'on')])
def test_indicator_loading_and_explicit_canonical_save(raw, mode):
    editor = ClassicDltDisplay(fixture(), 'KEYBL5')
    values = {**fixture().defaults(), 'IndicatorMode': str(raw)}
    assert editor.show(values)['controls']['indicator_mode'] == mode
    plan = editor.plan(values, settings={'indicator_mode': mode})
    assert plan.as_dict()['after']['indicator_mode'] == mode
    assert dict(plan.changes) == ({'IndicatorMode': (2,)} if raw == 3 else {})


def test_all_controls_inverse_clock_raw3_omission_and_immutable_plan():
    live = session()
    live.current.update(IndicatorMode='3', InvertDisplay='0', HideClock='1', DisableKeySlider='1', EnableScheduling='1')
    live.current['35bit2'] = '1'
    editor = ClassicDltDisplay(live.spec, live.unit_type)
    values = live.values()
    plan = editor.plan(values, settings={'invert_display': True, 'show_clock': True})
    assert set(plan.expected) == set(FIELDS)
    assert dict(plan.changes) == {'InvertDisplay': (1,), 'HideClock': (0,)}
    assert plan.as_dict()['raw_preview']['changed_mask'] == 0x30
    assert plan.as_dict()['raw_preview']['owned_mask'] == 0x30
    roundtrip = DltDisplayPlan.from_dict(json.loads(json.dumps(plan.as_dict())))
    assert roundtrip == plan
    result = editor.apply(live, roundtrip)
    assert result['after'] == {'indicator_mode': 'on', 'invert_display': True, 'show_clock': True}
    assert result['verified'] and not result['saved'] and not result['device_verified']
    assert result['raw_verification_scope'] == 'staged-pp-session-before-save'
    assert editor.show(live.values())['raw_projection_scope'] == 'named-pp-fields'
    assert live.current['IndicatorMode'] == '3'
    assert all(live.current[name] == values[name] for name in values if name not in plan.changes)
    with pytest.raises(TypeError):
        plan.settings['show_clock'] = False
    with pytest.raises(TypeError):
        plan.expected['HideClock'] = (0,)


@pytest.mark.parametrize('settings', [{}, {'page_fallback': True}, {'indicator_mode': 'ON'}, {'indicator_mode': 2},
                                      {'invert_display': 1}, {'show_clock': 0}, {'show_clock': None}])
def test_invalid_settings(settings):
    with pytest.raises(DltLabelError):
        ClassicDltDisplay(fixture(), 'KEYBL5').plan(fixture().defaults(), settings=settings)


def test_schema_identity_stale_and_forged_plans_fail_before_writes():
    live = session()
    editor = ClassicDltDisplay(fixture(), live.unit_type)
    plan = editor.plan(live.values(), settings={'show_clock': False}, identity=('KEYBL5', '2.1.00', '5085DL'))
    for bad in (replace(plan, changes={'HideClock': (False,)}), replace(plan, changes={'HideClock': (1.0,)}),
                replace(plan, changes={'DisableKeySlider': (1,)}), replace(plan, settings={'show_clock': True}),
                replace(plan, identity=('KEYBL5', '3.0.00', '5085DL'))):
        with pytest.raises(DltLabelError):
            editor.apply(live, bad)
        assert not live.calls
    live.current['EnableScheduling'] = '1'
    with pytest.raises(DltLabelError, match='changed since'):
        editor.apply(live, plan)
    live.current['EnableScheduling'] = '0'
    field = live.spec.parameters['HideClock']
    live.spec.parameters['HideClock'] = replace(field, fields={**field.fields, 'BitAddress': '4'})
    with pytest.raises(DltLabelError, match='layout mismatch'):
        editor.apply(live, plan)
    assert not live.calls


def test_unknown_and_tampered_serialized_fields_are_not_authority():
    editor = ClassicDltDisplay(fixture(), 'KEYBL5')
    plan = editor.plan(fixture().defaults(), settings={'show_clock': False}).as_dict()
    for key, value in [('saved', True), ('saved', 0), ('device_verified', True), ('extra', 1),
                       ('before', {}), ('changes', {'HideClock': [True]}),
                       ('requested', {'show_clock': 0}), ('catalog_number', '5085DL')]:
        with pytest.raises(DltLabelError):
            DltDisplayPlan.from_dict({**plan, key: value})


def test_native_raw_preserves_undeclared_bit7_and_neighbors():
    live = session()
    live.current.update(IndicatorMode='3', DisableKeySlider='1', EnableScheduling='1', HideClock='1', InvertDisplay='1')
    live.current['35bit2'] = '1'
    class Reply:
        def __init__(self, raw): self.lines = ('347 RawData=' + bytes([raw]).hex(),)
    def read(start, count):
        assert (start, count) == (0x35, 1)
        return Reply(0x80 | sum(int(live.current[name]) << bit for name, (bit, _, _) in LAYOUT.items()))
    live.get_raw_data = read
    editor = ClassicDltDisplay(live.spec, live.unit_type)
    result = editor.configure(live, settings={'indicator_mode': 'normal', 'invert_display': False, 'show_clock': True})
    assert result['display_raw_before'] == 0xFF and result['display_raw_after'] == 0xCD
    assert result['raw_bytes_verified']


def test_raw_mismatch_before_and_neighbor_change_after_are_refused():
    live = session()
    editor = ClassicDltDisplay(live.spec, live.unit_type)
    class Reply:
        def __init__(self, raw): self.lines = ('347 RawData=' + bytes([raw]).hex(),)
    live.get_raw_data = lambda start, count: Reply(0x80)
    with pytest.raises(DltLabelError, match='disagree'):
        editor.configure(live, settings={'invert_display': True})
    assert not live.calls
    raw = iter((0x81, 0xD1))
    live.get_raw_data = lambda start, count: Reply(next(raw))
    with pytest.raises(DltLabelApplyError, match='unrelated bits'):
        editor.configure(live, settings={'invert_display': True})
    assert live.calls == [('InvertDisplay', '1')]


def test_partial_failure_is_unsaved_without_retry_or_rollback():
    live = session()
    live.failure = 'HideClock'
    editor = ClassicDltDisplay(live.spec, live.unit_type)
    with pytest.raises(DltLabelApplyError) as result:
        editor.configure(live, settings={'invert_display': True, 'show_clock': False})
    assert result.value.attempted == ('InvertDisplay', 'HideClock')
    assert not result.value.details['saved']
    assert live.calls == [('InvertDisplay', '1'), ('HideClock', '1')]


@pytest.mark.parametrize('field,value', [('IndicatorMode', '4'), ('HideClock', '2'), ('35bit2', '0 1'), ('InvertDisplay', [False])])
def test_invalid_raw_fields(field, value):
    editor = ClassicDltDisplay(fixture(), 'KEYBL5')
    with pytest.raises(DltLabelError):
        editor.plan({**fixture().defaults(), field: value}, settings={'show_clock': True})
