"""Pure original broadcast command, cache milestone and recovery contracts."""
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path

import pytest

from cbus_toolkit.dlt_broadcast import (DltBroadcastError, assess_broadcast, compile_broadcast,
                                       validate_broadcast_plan)


def request(**changes):
    value = {'format': 'cbus-classic-dlt-broadcast-request-v1', 'project': 'LAB',
             'network': 254, 'application': 56, 'application_oid': None,
             'group': 20, 'level': None, 'language': 1, 'variant': 1,
             'tag_type': 'TEXT', 'tag_value': 'Kitchen', 'already_broadcast': False, 'bitmap': None}
    value.update(changes)
    return value


def bitmap(width=64):
    return {'width': width, 'data_hex': (b'\x81\x00' * width).hex()}


def outcomes(plan, *entries):
    result = []
    for command, entry in zip(plan['commands'], entries):
        base = {'index': command['index'], 'command_sha256': command['sha256']}
        result.append({**base, 'outcome': 'response', 'responses': entry} if isinstance(entry, list)
                      else {**base, 'outcome': 'uncertain', 'reason': entry})
    return {'format': 'cbus-classic-dlt-broadcast-outcomes-v1',
            'plan_sha256': plan['plan_sha256'], 'attempts': result}


def test_text14_latin1_uppercasehex_and_default_dle_not_nul():
    plan = compile_broadcast(request(tag_value='Café ' + 'x' * 20)).as_dict()
    assert plan['commands'] == [{
        'index': 1, 'text': 'LIGHTING LABEL //LAB/254/56 1 20 - F0 00 436166E920787878787878787878',
        'sha256': hashlib.sha256(b'LIGHTING LABEL //LAB/254/56 1 20 - F0 00 436166E920787878787878787878').hexdigest(),
        'timeout_ms': 20000, 'type': '00', 'data': '436166E920787878787878787878'}]
    for value in ('', '<Default>'):
        clear = compile_broadcast(request(tag_value=value)).as_dict()
        assert clear['commands'][0]['text'].endswith(' F0 0 10')
        assert clear['commands'][0]['data'] == '10'
    assert compile_broadcast(request(tag_value='<default>')).as_dict()['commands'][0]['type'] == '00'
    controls = compile_broadcast(request(tag_value='\0\t\n\r')).as_dict()
    assert controls['commands'][0]['data'] == '00090A0D'
    assert '\n' not in controls['commands'][0]['text']


@pytest.mark.parametrize('value', ['漢字', 'x' * 14 + '漢', '😀', 'x' * 1023 + 'Ā'])
def test_complete_original_input_unicode_suppression_marks_without_delivery(value):
    plan = compile_broadcast(request(tag_value=value)).as_dict()
    assert plan['commands'] == [] and plan['events'] == [{'event': 'mark_broadcast', 'value': True}]
    report = assess_broadcast(plan, outcomes(plan))
    assert report['status'] == 'unicode_suppressed' and report['original_cache_marked'] is True
    assert report['native_accepted'] is False and report['io_performed'] is False


@pytest.mark.parametrize('changes,disposition,mark', [
    ({'already_broadcast': True}, 'already_broadcast', True),
    ({'group': None}, 'group_absent', False),
    ({'already_broadcast': True, 'group': None}, 'already_broadcast', True),
    ({'group': None, 'tag_type': 'FONT', 'tag_value': 'unprepared'}, 'group_absent', False),
])
def test_early_returns_preserve_cache_without_new_delivery_evidence(changes, disposition, mark):
    plan = compile_broadcast(request(**changes)).as_dict()
    assert plan['commands'] == plan['events'] == []
    assert plan['disposition'] == disposition and plan['planned_final_cache_marked'] is mark
    report = assess_broadcast(plan, outcomes(plan))
    assert report['original_cache_marked'] is mark and report['native_accepted'] is False


def test_trigger_level_enable_oid_target_and_variant_tokens():
    trigger = compile_broadcast(request(application=202, level=99, language=2, variant=4)).as_dict()
    assert trigger['commands'][0]['text'] == 'TRIGGER LABEL //LAB/254/202 2 20 99 F3 00 4B69746368656E'
    enable = compile_broadcast(request(application=203)).as_dict()
    assert enable['commands'][0]['text'].startswith('ENABLE LABEL //LAB/254/203 ')
    oid = 'ABCDEF01-2345-6789-abcd-0123456789ab'
    icon = compile_broadcast(request(tag_type='ICON', tag_value='65535', application_oid=oid)).as_dict()
    assert icon['commands'][0]['text'] == f'LIGHTING LABEL //LAB/!{oid} 1 20 - F0 ICON 65535'
    assert icon['application_oid_binding_verified'] is False


@pytest.mark.parametrize('kind,value', [('DYNAMIC', '258'), ('FONT', '258,Arial,12,0,0,0,0,0,0,Font')])
def test_prepared_dynamic_and_font_order_mark_between_commands(kind, value):
    pixels = bitmap()
    plan = compile_broadcast(request(tag_type=kind, tag_value=value, bitmap=pixels)).as_dict()
    assert [row['text'] for row in plan['commands']] == [
        'LIGHTING LABEL //LAB/254/56 1 20 - F0 DYNAMIC 258 64 16 10 ' + pixels['data_hex'],
        'LIGHTING LABEL //LAB/254/56 1 20 - F0 ICON 258']
    assert [row['timeout_ms'] for row in plan['commands']] == [30000, 20000]
    assert plan['events'] == [{'event': 'command', 'index': 1}, {'event': 'mark_broadcast', 'value': True},
                              {'event': 'command', 'index': 2}]
    unobserved = assess_broadcast(plan, outcomes(plan))
    assert unobserved['original_cache_marked'] is False
    assert unobserved['planned_final_cache_marked'] is True
    first = assess_broadcast(plan, outcomes(plan, ['200 OK.']))
    assert first['original_cache_marked'] is True and first['native_accepted'] is False
    assert first['commands_without_outcomes'] == [2]
    both = assess_broadcast(plan, outcomes(plan, ['200 OK.'], ['200 OK.']))
    assert both['native_accepted'] is True
    assert both['device_verified'] is both['rendering_verified'] is both['persistence_verified'] is False


def test_failure_and_uncertainty_before_and_after_mark_never_retry_or_resume():
    plan = compile_broadcast(request(tag_type='DYNAMIC', tag_value='1', bitmap=bitmap())).as_dict()
    cases = [
        (outcomes(plan, ['408 Operation failed Send failed']), False, 'error'),
        (outcomes(plan, ['200 OK.'], ['408 Operation failed Send failed']), True, 'error'),
        (outcomes(plan, 'timeout'), None, 'uncertain'),
        (outcomes(plan, ['200 OK.'], 'connection_lost'), True, 'uncertain'),
        (outcomes(plan, ['500 failure']), False, 'pending'),
    ]
    for supplied, mark, status in cases:
        report = assess_broadcast(plan, supplied)
        assert report['original_cache_marked'] is mark and report['status'] == status
        assert report['native_accepted'] is False
        assert report['recovery']['automatic_retry'] is report['recovery']['automatic_resume'] is False
        assert report['recovery']['physical_state_known'] is False
        assert report['outcome_provenance'] == 'caller-supplied; not independently observed or authenticated'
        assert report['io_performed'] is False
    for first in (['408 Operation failed Send failed'], ['500 failure'], 'timeout'):
        with pytest.raises(DltBroadcastError, match='incompatible'):
            assess_broadcast(plan, outcomes(plan, first, ['200 OK.']))


def test_bad_object_and_prefix_completion_do_not_establish_native_acceptance():
    plan = compile_broadcast(request()).as_dict()
    for response in ('401 BAD OBJECT', '200 OKextra', 'bad object'):
        report = assess_broadcast(plan, outcomes(plan, [response]))
        assert report['attempts'][0]['original_state'] == 'completed'
        assert report['original_cache_marked'] is True and report['native_accepted'] is False
    dynamic = compile_broadcast(request(tag_type='DYNAMIC', tag_value='1', bitmap=bitmap())).as_dict()
    report = assess_broadcast(dynamic, outcomes(dynamic, ['401 bad object'], ['200 OK.']))
    assert report['status'] == 'original_completed' and report['original_cache_marked'] is True
    assert report['native_accepted'] is False


RESULTS = json.loads((Path(__file__).resolve().parents[1] /
    'research/fixtures/classic-dlt-broadcast-results-original.json').read_text())


@pytest.mark.parametrize('row', RESULTS['observations'], ids=[str(i) for i in range(len(RESULTS['observations']))])
def test_response_reduction_matches_independent_original_callback_replay(row):
    plan = compile_broadcast(request()).as_dict()
    # Each prefix is compared to the original independently observed callback
    # state. This does not imply a transport would dispatch lines after finish.
    for count, original in enumerate(row['steps'], 1):
        report = assess_broadcast(plan, outcomes(plan, row['responses'][:count]))
        current = report['attempts'][0]
        assert current['original_state'] == original['state']
        assert (current['original_error'] is not None) is (original['exception'] is not None)
        assert report['original_cache_marked'] is (original['state'] == 'completed')


@pytest.mark.parametrize('changes', [
    {'variant': 0}, {'variant': 5}, {'variant': True}, {'language': True}, {'language': 256},
    {'application': 1}, {'application': 256}, {'network': '254'}, {'network': -1},
    {'group': -1}, {'level': 1}, {'application': 202, 'level': True},
    {'project': 'LAB\nOFF 1'}, {'project': 'LONGPROJECT'}, {'application_oid': '!injected'},
    {'application_oid': '//LAB/254/56'}, {'already_broadcast': 1}, {'tag_type': 'UNKNOWN'},
    {'tag_value': '\ud800'}, {'tag_value': 'x' * 1025}, {'tag_value': None},
    {'tag_type': 'ICON', 'tag_value': '01'}, {'tag_type': 'ICON', 'tag_value': '65536'},
    {'tag_type': 'ICON', 'tag_value': '1\nOFF 2'}, {'tag_type': 'ICON', 'tag_value': ''},
    {'tag_type': 'DYNAMIC', 'tag_value': '1'},
    {'tag_type': 'DYNAMIC', 'tag_value': '1,a,b,c,d,e,f,g,h,i', 'bitmap': bitmap()},
    {'tag_type': 'FONT', 'tag_value': '1,Face,12', 'bitmap': bitmap()},
    {'tag_type': 'FONT', 'tag_value': 'no-id,a,b,c,d,e,f,g,h,i', 'bitmap': bitmap()},
    {'tag_type': 'FONT', 'tag_value': '1,a,b,c,d,e,f,g,h,\ni', 'bitmap': bitmap()},
    {'bitmap': bitmap()}, {'bitmap': {'width': 64, 'data_hex': 'AA'}},
    {'bitmap': {'width': True, 'data_hex': 'AA'}}, {'bitmap': {'width': 0, 'data_hex': ''}},
    {'bitmap': {'width': 241, 'data_hex': 'AA' * 482}},
])
def test_unsafe_ambiguous_unprepared_and_unadmitted_inputs_refused(changes):
    with pytest.raises(DltBroadcastError):
        compile_broadcast(request(**changes))


def test_native_width_bounds_exact_bytes_and_bitmap_input_hash_binding():
    for width in (1, 64, 240):
        supplied = request(tag_type='DYNAMIC', tag_value='0', bitmap=bitmap(width))
        plan = compile_broadcast(supplied).as_dict()
        assert plan['commands'][0]['data'] == f'0 {width} 16 10 ' + bitmap(width)['data_hex']
    invalid = request(tag_type='DYNAMIC', tag_value='0', bitmap=bitmap())
    invalid['bitmap']['data_hex'] = 'AA ' * 128
    with pytest.raises(DltBroadcastError, match='hexadecimal'):
        compile_broadcast(invalid)


def test_plan_immutability_and_canonical_recompilation_include_types_and_commands():
    supplied = request()
    plan = compile_broadcast(supplied)
    supplied['tag_value'] = 'changed outside'
    assert plan.as_dict()['request']['tag_value'] == 'Kitchen'
    with pytest.raises(FrozenInstanceError):
        plan._json = '{}'
    assert validate_broadcast_plan(json.loads(json.dumps(plan.as_dict()))).as_dict() == plan.as_dict()
    for field, value in (('io_performed', 0), ('initial_cache_marked', 0), ('extra', 1),
                         ('plan_sha256', '0' * 64), ('commands', [])):
        forged = plan.as_dict()
        forged[field] = value
        with pytest.raises(DltBroadcastError, match='canonical'):
            validate_broadcast_plan(forged)
    forged = plan.as_dict()
    forged['commands'][0]['text'] += '\nOFF 1'
    with pytest.raises(DltBroadcastError, match='canonical'):
        assess_broadcast(forged, outcomes(forged))


def test_all_outcome_data_validated_exactly_before_reduction():
    plan = compile_broadcast(request()).as_dict()
    valid = outcomes(plan, ['200 OK.'])
    for key, replacement in [('index', True), ('index', 2), ('command_sha256', '0' * 64),
                             ('outcome', 'completed'), ('responses', []), ('responses', ['']),
                             ('responses', ['200 OK.\n400 Syntax Error']), ('responses', ['x' * 4097]),
                             ('responses', ['200 OK'] * 33), ('extra', True)]:
        forged = json.loads(json.dumps(valid))
        forged['attempts'][0][key] = replacement
        with pytest.raises(DltBroadcastError):
            assess_broadcast(plan, forged)
    wrong_plan = {**valid, 'plan_sha256': '0' * 64}
    with pytest.raises(DltBroadcastError, match='different broadcast plan'):
        assess_broadcast(plan, wrong_plan)
    with pytest.raises(DltBroadcastError, match='at most one'):
        assess_broadcast(plan, {**valid, 'attempts': valid['attempts'] * 2})
    with pytest.raises(DltBroadcastError, match='reason'):
        assess_broadcast(plan, outcomes(plan, 'maybe'))


def test_strict_native_receipt_qualification_is_narrower_than_original_callbacks():
    plan = compile_broadcast(request()).as_dict()
    for lines, accepted in [(['200 OK'], True), (['200 OK.'], True),
                            (['100-Continue', '200 OK.'], True),
                            (['401 bad object', '200 OK.'], False),
                            (['500 unexpected', '200 OK.'], False),
                            (['unframed information', '200 OK.'], False),
                            (['200 OKextra'], False), (['200 OK.', 'unknown'], False)]:
        report = assess_broadcast(plan, outcomes(plan, lines))
        assert report['native_accepted'] is accepted
        assert report['native_accepted_scope'] == 'supplied receipt lines qualify; not independent acceptance evidence'
