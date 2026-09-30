"""Pure classic DLT broadcast CLI reports and untrusted JSON/file boundaries."""
import argparse
from copy import deepcopy
import hashlib
import json
import os

import pytest

from cbus_toolkit import dlt_broadcast_cli
from test_cli_dlt_controls import cli


def parse(*args):
    parser = argparse.ArgumentParser()
    dlt_broadcast_cli.options(parser.add_subparsers(dest='action', required=True))
    return parser.parse_args(['broadcast', *map(str, args)])


def request(**changes):
    value = {'format': 'cbus-classic-dlt-broadcast-request-v1', 'project': 'LAB', 'network': 254,
             'application': 56, 'application_oid': None, 'group': 1, 'level': None, 'language': 1,
             'variant': 1, 'tag_type': 'TEXT', 'tag_value': 'Kitchen', 'already_broadcast': False,
             'bitmap': None}
    value.update(changes)
    return value


def write_json(tmp_path, name, value):
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def compile_request(tmp_path, supplied=None, *, status=0):
    path = write_json(tmp_path, 'request.json', request() if supplied is None else supplied)
    return cli('dlt', 'broadcast', 'plan', '--input', path, status=status)


def outcomes(plan, attempts):
    return {'format': 'cbus-classic-dlt-broadcast-outcomes-v1',
            'plan_sha256': plan['plan_sha256'], 'attempts': attempts}


def response(command, lines=None):
    return {'index': command['index'], 'command_sha256': command['sha256'], 'outcome': 'response',
            'responses': ['200 OK'] if lines is None else lines}


def uncertain(command):
    return {'index': command['index'], 'command_sha256': command['sha256'],
            'outcome': 'uncertain', 'reason': 'timeout'}


def assess(tmp_path, plan, supplied, *, status=0):
    plan_file = write_json(tmp_path, 'plan.json', plan)
    observed_file = write_json(tmp_path, 'outcomes.json', supplied)
    return cli('dlt', 'broadcast', 'assess', '--plan', plan_file, '--outcomes', observed_file, status=status)


@pytest.mark.parametrize('payload', [
    '{"value":1,"value":2}', '{"nested":{"value":1,"value":2}}',
    '{"value":NaN}', '{"value":Infinity}', '{"value":-Infinity}',
    '{"value":1e9999}', '{"value":-1e9999}',
])
def test_strict_json_refuses_duplicate_and_nonfinite_values(tmp_path, payload):
    path = tmp_path / 'input.json'
    path.write_text(payload, encoding='utf-8')
    with pytest.raises(ValueError, match='Duplicate JSON key|Non-finite JSON number'):
        dlt_broadcast_cli._read_json(path)


def test_reader_is_bounded_and_requires_regular_files(tmp_path, monkeypatch):
    path = tmp_path / 'input.json'
    path.write_text(json.dumps({'value': 'input'}), encoding='utf-8')
    assert dlt_broadcast_cli._read_json(path) == {'value': 'input'}
    with pytest.raises(ValueError, match='regular file'):
        dlt_broadcast_cli._read_json(tmp_path)
    link = tmp_path / 'link.json'
    link.symlink_to(path)
    with pytest.raises((OSError, ValueError)):
        dlt_broadcast_cli._read_json(link)
    if hasattr(os, 'mkfifo'):
        fifo = tmp_path / 'fifo.json'
        os.mkfifo(fifo)
        with pytest.raises(ValueError, match='regular file'):
            dlt_broadcast_cli._read_json(fifo)
    monkeypatch.setattr(dlt_broadcast_cli, 'MAX_JSON_BYTES', 4)
    with pytest.raises(ValueError, match='size limit'):
        dlt_broadcast_cli._read_json(path)


def test_only_offline_plan_and_assess_options_are_available():
    assert parse('plan', '--input', 'request.json').broadcast_action == 'plan'
    assert parse('assess', '--plan', 'plan.json', '--outcomes', 'outcomes.json').broadcast_action == 'assess'
    for args in (('execute', '--input', 'request.json'), ('plan', '--input', 'request.json', '--host', '127.0.0.1'),
                 ('plan', '--input', 'request.json', '--output', 'result.json'),
                 ('assess', '--plan', 'plan.json')):
        with pytest.raises(SystemExit) as error:
            parse(*args)
        assert error.value.code == 2


def test_public_plan_compiles_exact_command_and_never_creates_output(tmp_path):
    path = write_json(tmp_path, 'request.json', request())
    before = path.read_bytes()
    plan = cli('dlt', 'broadcast', 'plan', '--input', path)
    command, = plan['commands']
    assert command['text'] == 'LIGHTING LABEL //LAB/254/56 1 1 - F0 00 4B69746368656E'
    assert command['index'] == 1 and command['timeout_ms'] == 20000
    assert command['sha256'] == hashlib.sha256(command['text'].encode('utf-8')).hexdigest()
    assert len(plan['plan_sha256']) == 64
    assert path.read_bytes() == before and list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize('changes', [
    {'project': 'LAB\nNET CLOSE'}, {'application_oid': '123\nNET CLOSE'}, {'group': True},
    {'variant': 1.0}, {'already_broadcast': 0}, {'extra': 'untrusted'},
    {'tag_type': 'DYNAMIC', 'tag_value': '2 99', 'bitmap': {'width': 1, 'data_hex': '0000'}},
])
def test_public_plan_rejects_invalid_request_types_and_command_tokens(tmp_path, changes):
    assert 'error' in compile_request(tmp_path, request(**changes), status=1)


def test_assess_rejects_forged_plan_and_mismatched_or_repeated_attempts(tmp_path):
    plan = compile_request(tmp_path)
    first = response(plan['commands'][0])
    report = outcomes(plan, [first])
    forged = deepcopy(plan)
    forged['commands'][0]['text'] += ' altered'
    forged['commands'][0]['sha256'] = hashlib.sha256(forged['commands'][0]['text'].encode('utf-8')).hexdigest()
    del forged['plan_sha256']
    forged['plan_sha256'] = hashlib.sha256(json.dumps(
        forged, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    report['plan_sha256'] = forged['plan_sha256']
    assert 'error' in assess(tmp_path, forged, report, status=1)
    report['plan_sha256'] = plan['plan_sha256']
    assert 'error' in assess(tmp_path, {**plan, 'plan_sha256': '0' * 64}, report, status=1)
    for changed in (
            {**report, 'plan_sha256': '0' * 64},
            outcomes(plan, [{**first, 'command_sha256': '0' * 64}]),
            outcomes(plan, [{**first, 'index': True}]),
            outcomes(plan, [{**first, 'index': 2}]),
            outcomes(plan, [first, first]),
            outcomes(plan, [{**first, 'responses': '200 OK'}]),
            {**report, 'device_verified': True}):
        assert 'error' in assess(tmp_path, plan, changed, status=1)


def test_supplied_receipt_acceptance_keeps_provenance_and_verification_boundaries(tmp_path):
    plan = compile_request(tmp_path)
    result = assess(tmp_path, plan, outcomes(plan, [response(plan['commands'][0])]))
    assert result['status'] == 'original_completed'
    assert result['native_accepted'] is True and result['original_cache_marked'] is True
    assert result['initial_cache_marked'] is False and result['planned_final_cache_marked'] is True
    assert result['outcome_provenance'] == 'caller-supplied; not independently observed or authenticated'
    assert result['native_accepted_scope'] == 'supplied receipt lines qualify; not independent acceptance evidence'
    for field in ('io_performed', 'device_verified', 'rendering_verified', 'persistence_verified',
                  'full_unit_save_workflow'):
        assert result[field] is False
    assert result['recovery']['automatic_retry'] is False
    assert result['recovery']['automatic_resume'] is False
    assert result['recovery']['physical_state_known'] is False


@pytest.mark.parametrize(('lines', 'basis'), [
    (['401 bad object'], 'bad_object_substring'), (['200 OKAY'], '200_OK_prefix'),
])
def test_original_completion_is_not_native_acceptance(tmp_path, lines, basis):
    plan = compile_request(tmp_path)
    result = assess(tmp_path, plan, outcomes(plan, [response(plan['commands'][0], lines)]))
    assert result['status'] == 'original_completed' and result['original_cache_marked'] is True
    assert result['attempts'][0]['original_completion_basis'] == basis
    assert result['native_accepted'] is False and result['device_verified'] is False
    assert result['recovery']['action'] == 'original_completion_is_not_native_acceptance; reconcile_before_replanning'


@pytest.mark.parametrize(('changes', 'status', 'cache'), [
    ({'tag_value': '12345678901234漢'}, 'unicode_suppressed', True),
    ({'group': None}, 'group_absent', False),
    ({'already_broadcast': True}, 'already_broadcast', True),
])
def test_no_command_dispositions_do_not_claim_native_acceptance(tmp_path, changes, status, cache):
    plan = compile_request(tmp_path, request(**changes))
    assert plan['commands'] == []
    result = assess(tmp_path, plan, outcomes(plan, []))
    assert result['status'] == status and result['original_cache_marked'] is cache
    assert result['native_accepted'] is False and result['device_verified'] is False


def test_planned_cache_mark_is_not_an_observed_completion(tmp_path):
    plan = compile_request(tmp_path)
    result = assess(tmp_path, plan, outcomes(plan, []))
    assert result['status'] == 'not_observed'
    assert result['planned_final_cache_marked'] is True and result['original_cache_marked'] is False
    assert result['native_accepted'] is False and result['commands_without_outcomes'] == [1]


def test_dynamic_partial_delivery_keeps_cache_and_never_automatically_resumes(tmp_path):
    plan = compile_request(tmp_path, request(tag_type='DYNAMIC', tag_value='1',
                                           bitmap={'width': 1, 'data_hex': '0000'}))
    first, second = plan['commands']
    assert [first['timeout_ms'], second['timeout_ms']] == [30000, 20000]
    assert first['text'].endswith(' DYNAMIC 1 1 16 10 0000')
    assert second['text'].endswith(' ICON 1')
    for attempts, cache in (([uncertain(first)], None), ([response(first), uncertain(second)], True),
                            ([response(first), response(second, ['402 Operation not supported'])], True)):
        result = assess(tmp_path, plan, outcomes(plan, attempts))
        assert result['original_cache_marked'] is cache
        assert result['native_accepted'] is False and result['device_verified'] is False
        assert result['recovery']['automatic_retry'] is False
        assert result['recovery']['automatic_resume'] is False
        assert result['recovery']['physical_state_known'] is False
    for failed in (uncertain(first), response(first, ['402 Operation not supported']),
                   response(first, ['100 Pending'])):
        assert 'error' in assess(tmp_path, plan, outcomes(plan, [failed, response(second)]), status=1)
