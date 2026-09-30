"""Ordered classic DLT Indicators controls, normalization and preservation."""
from dataclasses import replace
import json

import pytest

from cbus_toolkit.dlt_indicators import (ADDRESS, FIELDS, LAYOUT, OWNED, ClassicDltIndicators, DltIndicatorPlan)
from cbus_toolkit.dlt_labels import DltLabelApplyError, DltLabelError
from cbus_toolkit.dlt_profiles import PROFILES
from cbus_toolkit.unitspec import ParameterSpec
from test_dlt_labels import fixture as label_fixture
from test_macros import Session


def fixture(filename='KEYL5.xml', spec_type='KEYL5'):
    spec = label_fixture(filename, spec_type)
    for name, (address, bit, width, kind) in LAYOUT.items():
        default = '15' if name in ('TimerDuration', 'IndicatorPressedLevel') else (
            '1' if name in ('EnablePageFallback', 'EnableIndicatorPressedLevel') else '0')
        fields = {'Name': name, 'Type': kind, 'Address': str(address),
                  'BitAddress': str(bit), 'DefaultValue': default}
        if kind == 'int':
            fields.update(BitSize=str(width), MinValue='0', MaxValue=str((1 << width) - 1))
        spec.parameters[name] = ParameterSpec(name, kind, 'synthetic-dlt-indicators.xml', fields)
    return spec


def session(unit_type='KEYBL5', firmware='2.1.00', catalog='5085DL'):
    result = Session(fixture(PROFILES[unit_type].spec_filename, 'KEYDL4' if unit_type == 'KEYDL4' else 'KEYL5'))
    result.unit_type, result.firmware, result.catalog_number = unit_type, firmware, catalog
    return result


def operations(*pairs):
    return [{'control': key, 'value': value} for key, value in pairs]


def test_initialization_normalizes_legacy_duration_flags_and_nightlight_save():
    editor = ClassicDltIndicators(fixture(), 'KEYBL5')
    current = fixture().defaults()
    current.update(TimerDuration='0', EnableNightlight='1', FirstKeyThrowAway='1',
                   EnableNightlightOnUserKeys='1', EnableNightlightOnToggleKey='1')
    shown = editor.show(current)
    assert shown['controls'] == dict(page_fallback=False, pressed_enabled=False, duration_seconds=0,
                                    duration_selected_seconds=2, pressed_level=15, nightlight_keys=False,
                                    nightlight_toggle=False, first_key_throwaway=False)
    assert set(shown['initialization_changes']) == {'FirstKeyThrowAway',
        'EnablePageFallback', 'EnableIndicatorPressedLevel', 'EnableNightlightOnUserKeys', 'EnableNightlightOnToggleKey'}
    assert shown['save_normalizations'] == {'EnableNightlight': [0]}
    one = editor.show({**current, 'TimerDuration': '1'})
    assert one['controls']['duration_seconds'] == 2
    assert one['controls']['pressed_enabled'] and one['controls']['nightlight_keys']
    assert one['initialization_changes']['TimerDuration'] == [2]


def test_event_order_and_page_enabling_default():
    editor = ClassicDltIndicators(fixture(), 'KEYBL5')
    current = fixture().defaults()
    first = editor.plan(current, operations=operations(('page_fallback', False), ('pressed_enabled', False)))
    second = editor.plan(current, operations=operations(('pressed_enabled', False), ('page_fallback', False)))
    assert first.as_dict()['after']['duration_seconds'] == 0
    assert second.as_dict()['after']['duration_seconds'] == 15
    assert first.changes['TimerDuration'] == (0,) and 'TimerDuration' not in second.changes
    # Reopening the component subsequently normalizes both-disabled duration.
    reopened = editor.show({**current, **second.changes})
    assert reopened['controls']['duration_seconds'] == 0
    assert reopened['initialization_changes']['TimerDuration'] == [0]
    zero = {**current, 'TimerDuration': '0'}
    plan = editor.plan(zero, operations=operations(('page_fallback', True), ('duration_seconds', 5)))
    assert plan.as_dict()['steps'][0]['after']['duration_seconds'] == 15
    assert plan.as_dict()['after']['duration_seconds'] == 5
    assert plan.changes['TimerDuration'] == (5,)


def test_dependent_clearing_and_disabled_controls():
    editor = ClassicDltIndicators(fixture(), 'KEYBL5')
    current = fixture().defaults()
    steps = operations(('nightlight_keys', True), ('first_key_throwaway', True), ('nightlight_toggle', True),
                       ('nightlight_keys', False), ('pressed_enabled', False))
    plan = editor.plan(current, operations=steps).as_dict()
    assert plan['steps'][3]['after']['first_key_throwaway']
    assert not any(plan['after'][key] for key in ('nightlight_keys', 'nightlight_toggle', 'first_key_throwaway'))
    no_duration = {**current, 'TimerDuration': '0'}
    for key, value in (('duration_seconds', 2), ('pressed_level', 0), ('nightlight_keys', False),
                       ('nightlight_toggle', True), ('first_key_throwaway', False)):
        with pytest.raises(DltLabelError, match='disabled'):
            editor.plan(no_duration, operations=operations((key, value)))
    with pytest.raises(DltLabelError, match='disabled'):
        editor.plan(current, operations=operations(('first_key_throwaway', True)))


def test_preserving_transaction_serialization_and_full_raw_bytes():
    live = session()
    live.current.update(EnableNightlight='1', DisableTimerFlash='1', EnableNightlightControl='1')
    editor = ClassicDltIndicators(live.spec, live.unit_type)
    class Reply:
        def __init__(self, raw): self.lines = ('347 RawData=' + bytes(raw).hex(),)
    def raw(start, count):
        assert (start, count) == (ADDRESS, 2)
        result = [0, 0]
        for name, (address, bit, _, _) in LAYOUT.items():
            result[address - ADDRESS] |= int(live.current[name], 0) << bit
        return Reply(result)
    live.get_raw_data = raw
    before = live.values()
    request = operations(('duration_seconds', 5), ('pressed_level', 0), ('nightlight_keys', True),
                         ('first_key_throwaway', True))
    plan = editor.plan(before, operations=request, identity=(live.unit_type, live.firmware, live.catalog_number))
    request[0]['value'] = 12
    assert plan.as_dict()['requested'][0]['value'] == 5
    with pytest.raises(TypeError):
        plan.expected['TimerDuration'] = (6,)
    serialized = json.loads(json.dumps(plan.as_dict()))
    reloaded = DltIndicatorPlan.from_dict(serialized)
    assert reloaded == plan
    result = editor.apply(live, reloaded)
    assert result['verified'] and result['raw_bytes_verified']
    assert not result['saved'] and not result['device_verified']
    assert result['raw_before_hex'] == 'ff8f' and result['raw_after_hex'] == '05be'
    assert all(value == live.current[key] for key, value in before.items() if key not in OWNED)


@pytest.mark.parametrize('rows', [[], [{'control': 'page_fallback', 'value': 1}],
    [{'control': 'duration_seconds', 'value': 1}], [{'control': 'duration_seconds', 'value': 2.0}],
    [{'control': 'pressed_level', 'value': False}], [{'control': 'pressed_level', 'value': 16}],
    [{'control': 'brightness', 'value': True}], [{'control': 'page_fallback', 'value': True, 'extra': 1}],
    [{'control': 'page_fallback', 'value': True}] * 65])
def test_invalid_operations(rows):
    with pytest.raises(DltLabelError):
        ClassicDltIndicators(fixture(), 'KEYBL5').plan(fixture().defaults(), operations=rows)


def test_saved_plan_forgery_stale_identity_and_schema_fail_before_write():
    live = session()
    editor = ClassicDltIndicators(fixture(), live.unit_type)
    plan = editor.plan(live.values(), operations=operations(('duration_seconds', 5)))
    for forged in (replace(plan, changes={'TimerDuration': (False,)}),
                   replace(plan, changes={'TimerDuration': (5.0,)}),
                   replace(plan, changes={'DisableTimerFlash': (1,)}),
                   replace(plan, operations=(('duration_seconds', 6),)),
                   replace(plan, identity=('KEYML5', '2.1.00', '5055DL'))):
        with pytest.raises(DltLabelError):
            editor.apply(live, forged)
        assert not live.calls
    for key, value in (('saved', 0), ('changes', {'TimerDuration': [True]}), ('steps', []),
                       ('extra', True), ('requested', operations(('duration_seconds', 3)))):
        with pytest.raises(DltLabelError):
            DltIndicatorPlan.from_dict({**plan.as_dict(), key: value})
    live.current['EnableNightlightControl'] = '1'
    with pytest.raises(DltLabelError, match='changed since'):
        editor.apply(live, plan)
    live.current['EnableNightlightControl'] = '0'
    field = live.spec.parameters['TimerDuration']
    live.spec.parameters['TimerDuration'] = replace(field, fields={**field.fields, 'BitAddress': '4'})
    with pytest.raises(DltLabelError, match='layout mismatch'):
        editor.apply(live, plan)
    assert not live.calls


def test_raw_mismatch_and_partial_failure_never_save_retry_or_rollback():
    live = session()
    editor = ClassicDltIndicators(live.spec, live.unit_type)
    class Reply:
        lines = ('347 RawData=0000',)
    live.get_raw_data = lambda *_: Reply()
    with pytest.raises(DltLabelError, match='disagree'):
        editor.configure(live, operations=operations(('duration_seconds', 5)))
    assert not live.calls
    del live.get_raw_data
    live.failure = 'EnableNightlightOnUserKeys'
    with pytest.raises(DltLabelApplyError) as caught:
        editor.configure(live, operations=operations(('duration_seconds', 5), ('nightlight_keys', True)))
    assert caught.value.attempted == ('TimerDuration', 'EnableNightlightOnUserKeys')
    assert len(live.calls) == 2 and not caught.value.details['saved']
