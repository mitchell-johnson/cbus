"""Independent comparison with original instructions and input-boundary review."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from cbus_toolkit.dlt_broadcast import (DltBroadcastError, assess_broadcast,
                                       compile_broadcast, validate_broadcast_plan)

FIXTURES = Path(__file__).resolve().parents[1] / 'research/fixtures'
ORIGINAL = json.loads((FIXTURES / 'classic-dlt-broadcast-original.json').read_text())
RESULTS = json.loads((FIXTURES / 'classic-dlt-broadcast-results-original.json').read_text())


def request(**changes):
    result = {'format': 'cbus-classic-dlt-broadcast-request-v1', 'project': 'LAB',
              'network': 254, 'application': 56, 'application_oid': None, 'group': 20,
              'level': None, 'language': 1, 'variant': 1, 'tag_type': 'TEXT',
              'tag_value': 'Kitchen', 'already_broadcast': False, 'bitmap': None}
    result.update(changes)
    return result


def outcome(plan, rows):
    return {'format': 'cbus-classic-dlt-broadcast-outcomes-v1',
            'plan_sha256': plan['plan_sha256'], 'attempts': rows}


def response(command, lines):
    return {'index': command['index'], 'command_sha256': command['sha256'],
            'outcome': 'response', 'responses': lines}


@pytest.mark.parametrize('row', ORIGINAL['observations'])
def test_portable_compiler_matches_every_admitted_original_case(row):
    source, expected = row['input'], row['result']
    supplied = request(application={'TRIGGER': 202, 'ENABLE': 203}.get(source['application_type'], 56),
                       language=source['language'], group=source['group'] if source['group_present'] else None,
                       level=source['level'], variant=source['variant'],
                       tag_type=('TEXT', 'ICON', 'DYNAMIC', 'FONT')[source['tag_type']],
                       tag_value=source['value'], already_broadcast=source['already_broadcast'],
                       bitmap={'width': source['image_size'], 'data_hex': source['dynamic_data']}
                       if source['tag_type'] in (2, 3) else None)
    if source['application_id'].startswith('!'):
        supplied['application_oid'] = source['application_id'][1:]
    malformed = (source['variant'] not in range(1, 5) or
                 source['application_id'] == '!1234' or
                 source['tag_type'] == 2 and ',' in source['value'] or
                 source['tag_type'] == 3 and source['value'].count(',') != 9)
    if malformed:
        # The source probe intentionally includes raw model shapes which are
        # invalid native command tokens or outside the admitted UUID contract.
        with pytest.raises(DltBroadcastError):
            compile_broadcast(supplied)
        return
    plan = compile_broadcast(supplied).as_dict()
    commands = expected['commands']
    if not source['fail_command']:
        assert len(plan['commands']) == len(commands)
        assert plan['planned_final_cache_marked'] == expected['broadcast_marked']
    for emitted, observed in zip(plan['commands'], commands):
        assert emitted['text'] == (' '.join((observed['application_type'], 'LABEL',
            '//LAB/' + observed['application_id'], observed['language'], observed['group'],
            observed['level'], observed['variant'], observed['type'], observed['data'])))
        assert emitted['timeout_ms'] == (30000 if observed['type'] == 'DYNAMIC' else 20000)
    if source['fail_command']:
        attempts = [response(command, ['408 Operation failed Send failed'] if
                    command['index'] == source['fail_command'] else ['200 OK'])
                    for command in plan['commands'][:source['fail_command']]]
        assessed = assess_broadcast(plan, outcome(plan, attempts))
        assert assessed['original_cache_marked'] == expected['broadcast_marked']
        assert assessed['status'] == 'error'
        assert not assessed['native_accepted']


@pytest.mark.parametrize('row', RESULTS['observations'])
def test_response_fold_matches_independently_replayed_original_parser(row):
    plan = compile_broadcast(request()).as_dict()
    assessed = assess_broadcast(plan, outcome(plan, [response(plan['commands'][0], row['responses'])]))
    expected = row['steps'][-1]
    assert assessed['attempts'][0]['original_state'] == expected['state']
    assert assessed['original_cache_marked'] == (expected['state'] == 'completed')
    if expected['exception'] is None:
        assert assessed['attempts'][0]['original_error'] is None
    else:
        assert assessed['attempts'][0]['original_error'] is not None
    assert not assessed['io_performed'] and not assessed['device_verified']


@pytest.mark.parametrize('field,value', [
    ('network', True), ('application', 56.0), ('language', '1'), ('group', False),
    ('level', True), ('variant', False), ('already_broadcast', 1),
    ('project', 'LAB/254'), ('project', 'LAB\x00TAIL'), ('application_oid', '!1234'),
    ('application_oid', '00112233-4455-6677-8899-aabbccddeeff\n'),
    ('tag_value', '\ud800'), ('tag_type', ['TEXT']),
])
def test_strict_types_and_tokens_before_compilation(field, value):
    with pytest.raises(DltBroadcastError):
        compile_broadcast(request(**{field: value}))


@pytest.mark.parametrize('bitmap', [
    {'width': True, 'data_hex': '0000'}, {'width': 1.0, 'data_hex': '0000'},
    {'width': 0, 'data_hex': ''}, {'width': 241, 'data_hex': '00' * 482},
    {'width': 1, 'data_hex': '00'}, {'width': 1, 'data_hex': '00 00'},
    {'width': 1, 'data_hex': '0000', 'height': 16},
])
def test_prepared_image_must_have_exact_shape(bitmap):
    with pytest.raises(DltBroadcastError):
        compile_broadcast(request(tag_type='DYNAMIC', tag_value='258', bitmap=bitmap))


def test_font_context_never_becomes_a_raw_command_token():
    value = '258,Face with spaces,12,0,0,0,0,0,0,word ! ; $ ( )'
    plan = compile_broadcast(request(tag_type='FONT', tag_value=value,
                                    bitmap={'width': 1, 'data_hex': '00a5'})).as_dict()
    assert [row['data'] for row in plan['commands']] == ['258 1 16 10 00a5', '258']
    assert all('Face' not in row['text'] and '$' not in row['text'] for row in plan['commands'])


def test_canonical_plan_and_outcomes_do_not_alias_caller_objects():
    supplied = request(tag_type='DYNAMIC', tag_value='1', bitmap={'width': 1, 'data_hex': 'abcd'})
    model = compile_broadcast(supplied)
    saved = model.as_dict()
    supplied['bitmap']['data_hex'] = '0000'
    copied = model.as_dict()
    copied['commands'][0]['text'] = 'injected'
    assert model.as_dict() == saved
    forged = deepcopy(saved)
    forged['initial_cache_marked'] = 0  # Python equality must not admit bool/int aliasing.
    with pytest.raises(DltBroadcastError):
        validate_broadcast_plan(forged)
    observed = outcome(saved, [response(saved['commands'][0], ['200 OK'])])
    assessed = assess_broadcast(model, observed)
    assessed['attempts'][0]['responses'].append('400 Syntax Error')
    assert observed['attempts'][0]['responses'] == ['200 OK']


def test_uncertainty_and_partial_bitmap_require_reconciliation_without_replay():
    plan = compile_broadcast(request(tag_type='DYNAMIC', tag_value='1',
                                    bitmap={'width': 1, 'data_hex': 'abcd'})).as_dict()
    first, second = plan['commands']
    for position, command in enumerate((first, second), 1):
        uncertain = {'index': position, 'command_sha256': command['sha256'],
                     'outcome': 'uncertain', 'reason': 'connection_lost'}
        attempts = [response(first, ['200 OK'])] if position == 2 else []
        result = assess_broadcast(plan, outcome(plan, attempts + [uncertain]))
        assert result['original_cache_marked'] is (None if position == 1 else True)
        assert not result['native_accepted']
        assert result['recovery']['automatic_retry'] is False
        assert result['recovery']['automatic_resume'] is False
        assert result['recovery']['physical_state_known'] is False
    partial = assess_broadcast(plan, outcome(plan, [response(first, ['200 OK'])]))
    assert partial['original_cache_marked'] is True
    assert partial['commands_without_outcomes'] == [2]
    assert not partial['native_accepted']
    with pytest.raises(DltBroadcastError):
        assess_broadcast(plan, outcome(plan, [response(first, ['500 failure']), response(second, ['200 OK'])]))


@pytest.mark.parametrize('lines', [
    ['200 OKextra'], ['bad object'], ['401 BAD OBJECT'], ['200 OK', '500 failure', '200 OK'],
    ['unframed', '200 OK'], ['408 Operation failed Send failed', '200 OK'],
])
def test_legacy_completion_does_not_establish_native_acceptance(lines):
    plan = compile_broadcast(request()).as_dict()
    result = assess_broadcast(plan, outcome(plan, [response(plan['commands'][0], lines)]))
    assert not result['native_accepted']
    assert not result['device_verified'] and not result['persistence_verified']
